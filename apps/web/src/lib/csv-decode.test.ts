import { describe, it, expect } from "vitest";

import { decodeCsvBuffer } from "@/lib/csv-decode";

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
