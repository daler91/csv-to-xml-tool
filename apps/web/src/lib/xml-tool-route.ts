import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";
import { workerFetch, workerClientError } from "@/lib/worker-client";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";

/**
 * Shared POST-handler factory for the ad-hoc XML tool routes
 * (/api/validate-xml, /api/fix-xml). Both take a multipart .xml upload +
 * schemaType, proxy the content to a worker endpoint, and write an audit
 * entry — only the worker path, accepted schema types, and audit details
 * differ.
 */

export interface XmlToolRouteOptions<T> {
  /** Worker endpoint, e.g. "/validate-xsd". */
  workerPath: string;
  /** Rate-limit bucket prefix, e.g. "validate-xml". */
  rateLimitPrefix: string;
  /** schemaType values this tool accepts. */
  schemaTypes: ReadonlySet<string>;
  /** 400 message for a schemaType outside the accepted set. */
  schemaTypeError: string;
  /** AuditEntry.action, e.g. "xml_validated". */
  auditAction: string;
  /** Tool-specific audit metadata derived from the worker result. */
  auditMetadata: (result: T) => Record<string, unknown>;
  /** 502 message when the worker is unreachable/failing. */
  unavailableError: string;
  /** Prefix for server-side error logging. */
  logLabel: string;
}

/**
 * Decodes an uploaded XML file honoring its BOM / encoding declaration
 * instead of assuming UTF-8 — legacy Windows tools commonly emit UTF-16,
 * which a plain utf-8 decode mangles into false validation failures.
 * The declaration is rewritten to UTF-8 because the content travels on
 * as UTF-8 text from here (JSON body to the worker, which stages it as
 * utf-8): keeping a stale "UTF-16" declaration would itself break lxml.
 */
export function decodeXmlUpload(bytes: Buffer): string {
  let text: string | null = null;

  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    text = tryDecode(bytes, "utf-16le");
  } else if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    text = tryDecode(bytes, "utf-16be");
  } else {
    // No BOM: trust an explicit non-UTF-8 encoding declaration if the
    // prolog is ASCII-readable (it is for every single-byte encoding and
    // for UTF-8).
    const prolog = bytes.subarray(0, 200).toString("latin1");
    const declared = /encoding=["']([A-Za-z0-9._-]+)["']/.exec(prolog)?.[1];
    if (declared && !/^utf-?8$/i.test(declared)) {
      text = tryDecode(bytes, declared.toLowerCase());
    }
  }

  text ??= bytes.toString("utf-8");
  // Strip a decoded BOM and restate the declaration as UTF-8.
  return restateDeclarationAsUtf8(text.replace(/^﻿/, ""));
}

/**
 * Rewrites the encoding pseudo-attribute of a leading XML declaration to
 * UTF-8, leaving the text untouched when there is no declaration or it names
 * no encoding. Done in two steps -- isolate the declaration, then substitute
 * inside it -- because the single regex this replaced
 * (`^(\s*<\?xml[^>]*?)\s+encoding=...`) had `[^>]*?` and `\s+` competing
 * for the same whitespace, which backtracks super-linearly on a long prolog
 * that never closes.
 */
function restateDeclarationAsUtf8(text: string): string {
  const declaration = /^\s*<\?xml[^>]*>/.exec(text)?.[0];
  if (!declaration) return text;
  const rewritten = declaration.replace(
    /\s+encoding=["'][^"']*["']/,
    ' encoding="UTF-8"'
  );
  return rewritten + text.slice(declaration.length);
}

function tryDecode(bytes: Buffer, encoding: string): string | null {
  try {
    return new TextDecoder(encoding, { fatal: false }).decode(bytes);
  } catch {
    // Unknown label — fall through to utf-8.
    return null;
  }
}

/**
 * A multipart part is a file when it exposes the Blob surface; a plain text
 * part sent under the "file" name is a string, and reading `.name` off it
 * used to throw and surface as a 500 "service may be busy".
 */
export function isUploadedFile(part: FormDataEntryValue | null): part is File {
  return (
    typeof part === "object" &&
    part !== null &&
    typeof (part as File).arrayBuffer === "function" &&
    typeof (part as File).name === "string"
  );
}

// Multipart framing (boundaries, part headers, the schema/converter fields)
// on top of the file itself. Generous; the file's own size is checked exactly
// once it is parsed.
const MULTIPART_OVERHEAD_BYTES = 64 * 1024;

/**
 * Rejects a request whose declared Content-Length cannot hold a file within
 * the cap, *before* `req.formData()` buffers the whole body. The size check
 * on `file.size` still runs afterwards; this one is what keeps the cap a
 * bound on memory rather than only on what reaches disk.
 */
export function declaredBodyTooLarge(req: Request): NextResponse | null {
  const declared = Number(req.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES) {
    return NextResponse.json(
      { error: "File size exceeds 50MB limit" },
      { status: 413 }
    );
  }
  return null;
}

export function createXmlToolRoute<T>(
  options: XmlToolRouteOptions<T>
): (req: Request) => Promise<NextResponse> {
  return async function POST(req: Request) {
    try {
      const user = await getRequiredUser();

      const { success, remaining } = await rateLimit(
        `${options.rateLimitPrefix}:${user.id}`,
        10,
        60
      );
      if (!success) {
        return NextResponse.json(
          { error: "Too many requests" },
          {
            status: 429,
            headers: { "X-RateLimit-Remaining": String(remaining) },
          }
        );
      }

      const tooLarge = declaredBodyTooLarge(req);
      if (tooLarge) return tooLarge;

      const formData = await req.formData();
      const file = formData.get("file");
      const schemaType = formData.get("schemaType");

      if (!isUploadedFile(file) || typeof schemaType !== "string" || !schemaType) {
        return NextResponse.json(
          { error: "File and schema type are required" },
          { status: 400 }
        );
      }
      if (!file.name.toLowerCase().endsWith(".xml")) {
        return NextResponse.json(
          { error: "Only XML files are accepted" },
          { status: 400 }
        );
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        return NextResponse.json(
          { error: "File size exceeds 50MB limit" },
          { status: 413 }
        );
      }
      if (!options.schemaTypes.has(schemaType)) {
        return NextResponse.json(
          { error: options.schemaTypeError },
          { status: 400 }
        );
      }

      const xmlContent = decodeXmlUpload(
        Buffer.from(await file.arrayBuffer())
      );

      let result: T;
      try {
        result = await workerFetch<T>(options.workerPath, {
          method: "POST",
          body: JSON.stringify({
            job_id: `adhoc-${randomUUID()}`,
            xml_content: xmlContent,
            schema_type: schemaType,
          }),
          timeoutMs: 60_000,
        });
      } catch (error) {
        const clientError = workerClientError(error);
        if (clientError) {
          return NextResponse.json({ error: clientError }, { status: 400 });
        }
        throw error;
      }

      await prisma.auditEntry.create({
        data: {
          userId: user.id,
          action: options.auditAction,
          metadata: {
            fileName: file.name,
            schemaType,
            ...options.auditMetadata(result),
          },
        },
      });

      return NextResponse.json(result);
    } catch (error) {
      if (error instanceof Error && error.message === "Unauthorized") {
        return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
      }
      console.error(`${options.logLabel}:`, error);
      return NextResponse.json(
        { error: options.unavailableError },
        { status: 502 }
      );
    }
  };
}
