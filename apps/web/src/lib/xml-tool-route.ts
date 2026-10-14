import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";
import { workerFetch, workerClientError } from "@/lib/worker-client";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";
import { decodeWindows1252 } from "@/lib/csv-decode";

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
 * An uploaded XML file whose bytes are not text in the encoding its BOM or
 * declaration names (UTF-8 when it names none): SBA's parser rejects such a
 * file outright, so it is refused here rather than repaired.
 */
export class XmlEncodingError extends Error {}

/**
 * Decodes an uploaded XML file honoring its BOM / encoding declaration
 * instead of assuming UTF-8 — legacy Windows tools commonly emit UTF-16,
 * which a plain utf-8 decode mangles into false validation failures.
 * The declaration is rewritten to UTF-8 because the content travels on
 * as UTF-8 text from here (JSON body to the worker, which stages it as
 * utf-8): keeping a stale "UTF-16" declaration would itself break lxml.
 *
 * Bytes that are not text in that encoding throw XmlEncodingError. They
 * used to be replaced with U+FFFD, so a file saved as Windows-1252 but
 * declared UTF-8 was reported valid, though SBA can't parse it, and the
 * auto-fix download carried the replacement characters.
 */
export function decodeXmlUpload(bytes: Buffer): string {
  let encoding = "utf-8";
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    encoding = "utf-16le";
  } else if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    encoding = "utf-16be";
  } else {
    // No BOM: trust an explicit non-UTF-8 encoding declaration if the
    // prolog is ASCII-readable (it is for every single-byte encoding and
    // for UTF-8). Only the XML declaration counts, not an attribute that
    // happens to be called "encoding"; XML allows spaces around the "=".
    const prolog = bytes.subarray(0, 200).toString("latin1");
    const declaration = /^\s*<\?xml[^>]*>/.exec(prolog)?.[0] ?? "";
    const declared = /\sencoding\s*=\s*["']([A-Za-z0-9._-]+)["']/.exec(declaration)?.[1];
    const known = declared ? canonicalEncoding(declared) : null;
    if (known && known !== "utf-8") encoding = known;
  }

  let text: string;
  try {
    // "ISO-8859-1", "latin1", "ascii" and "cp1252" are all windows-1252 to
    // the WHATWG decoder; decodeWindows1252 says why it isn't TextDecoder.
    text = encoding === "windows-1252"
      ? decodeWindows1252(bytes)
      : new TextDecoder(encoding, { fatal: true }).decode(bytes);
  } catch {
    const repaired = new TextDecoder(encoding).decode(bytes);
    const at = repaired.indexOf("\ufffd");
    const line = repaired.slice(0, Math.max(at, 0)).split("\n").length;
    throw new XmlEncodingError(
      `The file is not valid ${encoding.toUpperCase()} text (first unreadable character on ` +
        `line ${line}), so SBA could not read it either. Save it as UTF-8 and upload it again.`
    );
  }
  // Strip a decoded BOM and restate the declaration as UTF-8.
  return restateDeclarationAsUtf8(text.replace(/^\ufeff/, ""));
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
  // One whitespace character, not `\s+`: this search is unanchored, and a
  // greedy run over a long whitespace stretch would backtrack quadratically.
  // Any extra whitespace before the attribute is simply left in place.
  const rewritten = declaration.replace(
    /\sencoding\s*=\s*["'][^"']*["']/,
    ' encoding="UTF-8"'
  );
  return rewritten + text.slice(declaration.length);
}

/** The WHATWG name for an encoding label ("latin1" -> "windows-1252"), or null. */
function canonicalEncoding(label: string): string | null {
  try {
    return new TextDecoder(label).encoding;
  } catch {
    // Unknown label — read as utf-8.
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

const MAX_BODY_BYTES = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES;

function bodyTooLarge(): NextResponse {
  return NextResponse.json({ error: "File size exceeds 50MB limit" }, { status: 413 });
}

/**
 * Rejects a request whose declared Content-Length cannot hold a file within
 * the cap, before any of the body is read.
 */
export function declaredBodyTooLarge(req: Request): NextResponse | null {
  const declared = Number(req.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
    return bodyTooLarge();
  }
  return null;
}

/**
 * Parse a multipart upload without ever holding more than the upload cap.
 *
 * Checking Content-Length alone is not a bound on memory: a chunked request
 * carries no length (`Number(null)` is 0, so it passed), and `req.formData()`
 * then buffered the whole body before `file.size` was looked at. The body is
 * read here as a stream and abandoned the moment it passes the cap, so a
 * multi-gigabyte upload costs at most the cap -- in this process, which also
 * runs the conversion consumer. Returns the form data, or the 413 to send.
 */
export async function readCappedFormData(req: Request): Promise<FormData | NextResponse> {
  const declared = declaredBodyTooLarge(req);
  if (declared) return declared;
  if (!req.body) return req.formData();

  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    if (received > MAX_BODY_BYTES) {
      await reader.cancel().catch(() => {});
      return bodyTooLarge();
    }
    chunks.push(value);
  }
  // Re-parse the bytes with the request's own multipart boundary.
  return new Response(Buffer.concat(chunks), {
    headers: { "content-type": req.headers.get("content-type") ?? "" },
  }).formData();
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

      const formData = await readCappedFormData(req);
      if (formData instanceof NextResponse) return formData;
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

      let xmlContent: string;
      try {
        xmlContent = decodeXmlUpload(Buffer.from(await file.arrayBuffer()));
      } catch (error) {
        if (error instanceof XmlEncodingError) {
          return NextResponse.json({ error: error.message }, { status: 400 });
        }
        throw error;
      }

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
