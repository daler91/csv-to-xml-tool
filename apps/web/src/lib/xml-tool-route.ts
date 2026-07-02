import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";
import { workerFetch } from "@/lib/worker-client";
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
  return text
    .replace(/^﻿/, "")
    .replace(
      /^(\s*<\?xml[^>]*?)\s+encoding=["'][^"']*["']/,
      '$1 encoding="UTF-8"'
    );
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
 * A deterministic 4xx from the worker (e.g. unsupported schema type,
 * empty content) is the caller's problem, not an outage — surface the
 * worker's detail as a 400 instead of mislabeling it a transient 502.
 */
function workerClientError(error: unknown): string | null {
  if (!(error instanceof Error)) return null;
  const match = /^Worker error (4\d\d): ([\s\S]*)$/.exec(error.message);
  if (!match) return null;
  try {
    const detail = JSON.parse(match[2])?.detail;
    if (typeof detail === "string" && detail) return detail;
  } catch {
    // Non-JSON body — use a generic message below.
  }
  return "The file could not be processed";
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

      const formData = await req.formData();
      const file = formData.get("file") as File;
      const schemaType = formData.get("schemaType") as string;

      if (!file || !schemaType) {
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
