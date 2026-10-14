import { describe, it, expect, vi } from "vitest";

// The module also wires up the session/worker plumbing for the route
// handlers; none of it is exercised here, so keep next-auth out of the import.
vi.mock("@/lib/prisma", () => ({ prisma: {} }));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/rate-limit", () => ({ rateLimit: vi.fn() }));

import { XmlEncodingError, decodeXmlUpload } from "@/lib/xml-tool-route";

describe("decodeXmlUpload declaration rewrite", () => {
  it("restates a declared encoding as UTF-8 and leaves the body alone", () => {
    const xml = "<?xml version=\"1.0\" encoding='ISO-8859-1'?>\n<Doc>é</Doc>";
    const out = decodeXmlUpload(Buffer.from(xml, "latin1"));
    expect(out).toBe('<?xml version="1.0" encoding="UTF-8"?>\n<Doc>é</Doc>');
  });

  it("keeps surrounding whitespace and still rewrites the encoding", () => {
    const xml = '<?xml version="1.0"   encoding="latin1"  ?><Doc/>';
    expect(decodeXmlUpload(Buffer.from(xml))).toBe(
      '<?xml version="1.0"   encoding="UTF-8"  ?><Doc/>'
    );
  });

  it("leaves a declaration without an encoding untouched", () => {
    const xml = '<?xml version="1.0"?><Doc/>';
    expect(decodeXmlUpload(Buffer.from(xml))).toBe(xml);
  });

  it("only rewrites inside the declaration, not a later element", () => {
    const xml = '<Doc encoding="latin1"/>';
    expect(decodeXmlUpload(Buffer.from(xml))).toBe(xml);
  });

  it("stays linear on a long, never-closed prolog", () => {
    // The regex this replaced backtracked super-linearly here: `[^>]*?` and
    // `\s+` both matched the whitespace run, so every split point was tried.
    const xml = "<?xml version=\"1.0\"" + " ".repeat(200_000) + "encoding";
    const started = Date.now();
    expect(decodeXmlUpload(Buffer.from(xml))).toBe(xml);
    expect(Date.now() - started).toBeLessThan(1000);
  });
});

describe("decodeXmlUpload encodings", () => {
  it("reads a declaration with spaces around the equals sign", () => {
    const xml = '<?xml version="1.0" encoding = "ISO-8859-1"?>\n<Doc>Jos\u00e9</Doc>';
    expect(decodeXmlUpload(Buffer.from(xml, "latin1"))).toBe(
      '<?xml version="1.0" encoding="UTF-8"?>\n<Doc>Jos\u00e9</Doc>'
    );
  });

  it("refuses bytes that are not text in the declared encoding", () => {
    // Saved as Windows-1252 but declared (or defaulting to) UTF-8: SBA's
    // parser rejects it, so it must not be repaired into a "valid" file.
    const bytes = Buffer.from('<?xml version="1.0"?>\n<Doc>Jos\xe9</Doc>', "latin1");
    expect(() => decodeXmlUpload(bytes)).toThrow(XmlEncodingError);
    expect(() => decodeXmlUpload(bytes)).toThrow(/line 2/);
  });

  it("decodes windows-1252 by its own table, not as ISO-8859-1", () => {
    // SBA's FundingSource values carry en dashes (0x96 in windows-1252).
    const bytes = Buffer.from(
      '<?xml version="1.0" encoding="windows-1252"?><Doc>TX \x96 1780</Doc>', "latin1"
    );
    expect(decodeXmlUpload(bytes)).toBe('<?xml version="1.0" encoding="UTF-8"?><Doc>TX \u2013 1780</Doc>');
  });

  it("ignores an attribute named encoding outside the declaration", () => {
    const xml = '<Doc encoding="windows-1252">\u00e9</Doc>';
    expect(decodeXmlUpload(Buffer.from(xml, "utf-8"))).toBe(xml);
  });
});
