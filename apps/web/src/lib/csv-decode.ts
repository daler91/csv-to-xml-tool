/**
 * Decodes an uploaded CSV honoring what spreadsheet tools actually write.
 *
 * The bytes used to be read with a plain `"utf-8"`, which is not what Excel
 * on Windows produces for "CSV (Comma delimited)": that is the system code
 * page (cp1252 in the US), and every non-ASCII byte -- the é in José, the ñ
 * in Muñoz, an en dash in a street name -- became U+FFFD before the worker
 * saw it. The worker then recorded no issue, because the text it received
 * was valid UTF-8, so the corruption shipped silently in a federal filing.
 *
 * Order of trust:
 *   1. A UTF-16 BOM (Excel's "Unicode Text" export) → that encoding.
 *   2. Strict UTF-8. A UTF-8 BOM is preserved; the worker reads utf-8-sig.
 *   3. Anything that is not valid UTF-8 → windows-1252, which is a superset
 *      of ISO-8859-1 and what every Windows export that is not UTF-8 uses.
 *
 * Returns the encoding used so callers can log or record the fallback.
 */

export type CsvEncoding = "utf-8" | "utf-16le" | "utf-16be" | "windows-1252";

export function decodeCsvBuffer(bytes: Buffer): { text: string; encoding: CsvEncoding } {
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    return { text: decode(bytes, "utf-16le"), encoding: "utf-16le" };
  }
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    return { text: decode(bytes, "utf-16be"), encoding: "utf-16be" };
  }
  try {
    return {
      text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes),
      encoding: "utf-8",
    };
  } catch {
    return { text: decode(bytes, "windows-1252"), encoding: "windows-1252" };
  }
}

function decode(bytes: Buffer, encoding: string): string {
  // ignoreBOM keeps a leading BOM in the output for UTF-16 too; the worker's
  // utf-8-sig read strips only a UTF-8 BOM, so drop the decoded one here.
  return new TextDecoder(encoding, { fatal: false, ignoreBOM: false }).decode(bytes);
}
