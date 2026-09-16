import { describe, it, expect } from "vitest";

import { decodeCsvBuffer, decodeWindows1252 } from "@/lib/csv-decode";

describe("decodeCsvBuffer", () => {
  it("decodes valid UTF-8 as UTF-8 and keeps the BOM for the worker's utf-8-sig read", () => {
    const bytes = Buffer.concat([
      Buffer.from([0xef, 0xbb, 0xbf]),
      Buffer.from("Last Name\nMuñoz\n", "utf-8"),
    ]);
    const { text, encoding } = decodeCsvBuffer(bytes);
    expect(encoding).toBe("utf-8");
    expect(text).toBe("﻿Last Name\nMuñoz\n");
  });

  it("falls back to windows-1252 for an Excel 'CSV (Comma delimited)' export", () => {
    // "Muñoz" and an en dash as cp1252 writes them: ñ = 0xF1, – = 0x96.
    const bytes = Buffer.concat([
      Buffer.from("Last Name,Street\nMu", "latin1"),
      Buffer.from([0xf1]),
      Buffer.from("oz,12 Main ", "latin1"),
      Buffer.from([0x96]),
      Buffer.from(" Suite 4\n", "latin1"),
    ]);
    const { text, encoding } = decodeCsvBuffer(bytes);
    expect(encoding).toBe("windows-1252");
    expect(text).toBe("Last Name,Street\nMuñoz,12 Main – Suite 4\n");
    expect(text).not.toContain("�");
  });

  it("decodes a UTF-16 LE export by its BOM", () => {
    const bytes = Buffer.concat([
      Buffer.from([0xff, 0xfe]),
      Buffer.from("Last Name\nJosé\n", "utf16le"),
    ]);
    const { text, encoding } = decodeCsvBuffer(bytes);
    expect(encoding).toBe("utf-16le");
    expect(text).toBe("Last Name\nJosé\n");
  });

  it("leaves plain ASCII untouched", () => {
    const { text, encoding } = decodeCsvBuffer(Buffer.from("a,b\n1,2\n"));
    expect(encoding).toBe("utf-8");
    expect(text).toBe("a,b\n1,2\n");
  });
});

describe("decodeWindows1252", () => {
  it("maps the 0x80-0x9F range to the cp1252 characters, not C1 controls", () => {
    // € ‚ ƒ „ … † ‡ ˆ ‰ Š ‹ Œ Ž ‘ ’ “ ” • – — ˜ ™ š › œ ž Ÿ
    const bytes = new Uint8Array([
      0x80, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x8b, 0x8c, 0x8e,
      0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0x9b, 0x9c, 0x9e, 0x9f,
    ]);
    expect(decodeWindows1252(bytes)).toBe("€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ");
  });

  it("passes ASCII and Latin-1 bytes through unchanged", () => {
    expect(decodeWindows1252(new Uint8Array([0x41, 0x7e, 0xa9, 0xf1, 0xff]))).toBe("A~©ñÿ");
  });
});
