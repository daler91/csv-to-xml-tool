"""The web and the command line must decode an upload to the same text.

There are two decoders: the web reads the upload with decodeCsvBuffer
(apps/web/src/lib/csv-decode.ts) and sends the worker text, and the command
line reads the file with decode_csv_bytes. Where they disagree, the same file
is filed differently depending on where it was converted -- as happened with a
UTF-16 file one byte too long: the converters learned to leave the stray byte
out, the web did not, and it reached the filing as a '�' in the last cell.

Both suites check one table, tests/fixtures/csv_decoding_cases.json: the bytes
of each case below and the text decode_csv_bytes reads from them. This test
keeps the table in step with the cases and the Python decoder;
csv-decode.test.ts holds the web decoder to the same texts. After changing a
case or the decoder on purpose, regenerate the table:

    python tests/test_csv_decoding_parity.py
"""

import codecs
import json
import os
import sys
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:  # run directly to regenerate the table
    sys.path.insert(0, _REPO_ROOT)

from src.data_cleaning import decode_csv_bytes  # noqa: E402


# TestCase assertions rather than bare asserts, which the code scanners report
# (Bandit B101); one instance serves every test.
check = unittest.TestCase()

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "csv_decoding_cases.json")

_BODY = "Contact ID,Name,City\nC-1,José Muñoz–Peña,Montréal\nC-2,“Zoë” O’Brien,Kraków\n"
_CP1252_BODY = _BODY.replace("ó", "o")  # every other character is in Windows-1252


def _utf16le(text):
    return codecs.BOM_UTF16_LE + text.encode("utf-16-le")


CASES = {
    "utf-8": _BODY.encode("utf-8"),
    "utf-8 with a BOM (Excel's CSV UTF-8)": codecs.BOM_UTF8 + _BODY.encode("utf-8"),
    "utf-8 with CRLF line ends": _BODY.replace("\n", "\r\n").encode("utf-8"),
    "utf-8 with bare CR line ends": _BODY.replace("\n", "\r").encode("utf-8"),
    "windows-1252 (Excel's CSV Comma delimited)": _CP1252_BODY.encode("cp1252"),
    "windows-1252 bytes it leaves undefined": b"A,B\n\x81\x8d\x8f\x90\x9d,\x80\x96\x93\x94\n",
    "latin-1 high bytes": bytes(range(0xA0, 0x100)) + b"\n",
    "utf-16 le (Excel's Unicode Text)": _utf16le(_BODY),
    "utf-16 be": codecs.BOM_UTF16_BE + _BODY.encode("utf-16-be"),
    "utf-16 le with CRLF line ends": _utf16le(_BODY.replace("\n", "\r\n")),
    "utf-16 le, a stray byte after the last newline": _utf16le(_BODY) + b"\n",
    "utf-16 le, a stray byte and no final newline": _utf16le(_BODY.rstrip("\n")) + b"\n",
    "utf-16 le, half an emoji": (
        _utf16le("A,B\n1,") + "\U0001F600".encode("utf-16-le")[:2] + "x\n".encode("utf-16-le")
    ),
    "empty": b"",
    "only a utf-8 BOM": codecs.BOM_UTF8,
}


def _table_from_cases():
    rows = []
    for name, data in CASES.items():
        text, encoding = decode_csv_bytes(data)
        rows.append({"name": name, "hex": data.hex(), "text": text, "encoding": encoding})
    return rows


def _load_table():
    with open(TABLE, encoding="utf-8") as f:
        return json.load(f)


def test_the_shared_table_holds_exactly_these_cases():
    check.assertEqual([(row["name"], row["hex"]) for row in _load_table()], [
        (name, data.hex()) for name, data in CASES.items()
    ])


def test_decode_csv_bytes_reads_each_case_as_the_table_says():
    for row in _load_table():
        check.assertEqual(decode_csv_bytes(bytes.fromhex(row["hex"])), (row["text"], row["encoding"]), row["name"])


def test_a_stray_utf16_byte_never_becomes_a_character():
    for row in _load_table():
        if "stray byte" in row["name"]:
            check.assertNotIn("\ufffd", row["text"], row["name"])
            check.assertTrue(row["text"].rstrip("\n").endswith("Kraków"), row["name"])


if __name__ == "__main__":
    os.makedirs(os.path.dirname(TABLE), exist_ok=True)
    with open(TABLE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(_table_from_cases(), f, ensure_ascii=True, indent=1)
        f.write("\n")
    print(f"wrote {len(CASES)} cases to {os.path.relpath(TABLE, _REPO_ROOT)}")
