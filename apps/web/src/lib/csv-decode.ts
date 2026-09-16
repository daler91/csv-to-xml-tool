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
    return { text: decodeWindows1252(bytes), encoding: "windows-1252" };
  }
}

function decode(bytes: Buffer, encoding: string): string {
  // ignoreBOM keeps a leading BOM in the output for UTF-16 too; the worker's
  // utf-8-sig read strips only a UTF-8 BOM, so drop the decoded one here.
  return new TextDecoder(encoding, { fatal: false, ignoreBOM: false }).decode(bytes);
}

// Code points for bytes 0x80-0x9F, where windows-1252 differs from ISO-8859-1.
// Five positions (0x81, 0x8D, 0x8F, 0x90, 0x9D) are undefined in cp1252;
// they map to the C1 control of the same value, as the WHATWG decoder does.
const CP1252_HIGH: readonly number[] = [
  0x20ac, 0x0081, 0x201a, 0x0192, 0x201e, 0x2026, 0x2020, 0x2021,
  0x02c6, 0x2030, 0x0160, 0x2039, 0x0152, 0x008d, 0x017d, 0x008f,
  0x0090, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014,
  0x02dc, 0x2122, 0x0161, 0x203a, 0x0153, 0x009d, 0x017e, 0x0178,
];

/**
 * Hand-rolled rather than `new TextDecoder("windows-1252")`: a Node built
 * with small-icu (the GitHub Actions runner, for one) accepts that label but
 * decodes it as ISO-8859-1, so an en dash (0x96) came out as the C1 control
 * U+0096. Every byte below 0x80 or above 0x9F is its own code point in both
 * encodings; only the 32 in between need the table.
 */
export function decodeWindows1252(bytes: Uint8Array): string {
  let out = "";
  for (const byte of bytes) {
    out += String.fromCharCode(
      byte >= 0x80 && byte <= 0x9f ? CP1252_HIGH[byte - 0x80] : byte
    );
  }
  return out;
}
