"""Strip obvious personal identifiers from a CSV before it is used for labeling.

Catches only fixed-format identifiers (phone, e-mail, URL, LINE id, 13-digit
national id, long digit runs such as bank accounts and order numbers). It does
NOT find names or addresses: read the output yourself before sharing it.

    python3 -m phase8.tools.anonymize in.csv out.csv --column text --column staff_reply
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter

# Order matters: the more specific patterns run first.
PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("URL", re.compile(r"(?:https?://|www\.)\S+", re.I)),
    ("LINEID", re.compile(r"(?<![\w.])@[A-Za-z0-9._-]{3,}")),
    ("NATIONAL_ID", re.compile(r"\b\d[- ]?\d{4}[- ]?\d{5}[- ]?\d{2}[- ]?\d\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+66|0)[- ]?\d{1,2}[- ]?\d{3}[- ]?\d{3,4}(?!\d)")),
    ("NUMBER", re.compile(r"(?<!\d)\d[\d\- ]{6,}\d(?!\d)")),
]


def scrub(text: str, counts: Counter | None = None) -> str:
    for tag, pattern in PATTERNS:
        def _sub(match, tag=tag):
            if counts is not None:
                counts[tag] += 1
            return "[%s]" % tag
        text = pattern.sub(_sub, text)
    return text


def anonymize_file(src: str, dst: str, columns: list[str]) -> Counter:
    counts: Counter = Counter()
    with open(src, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit("column not found: %s (have: %s)" % (", ".join(missing), reader.fieldnames))
        rows = list(reader)
        fieldnames = reader.fieldnames
    for row in rows:
        for col in columns:
            row[col] = scrub(row.get(col) or "", counts)
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--column", action="append", required=True, help="column to scrub (repeatable)")
    args = ap.parse_args(argv)
    counts = anonymize_file(args.src, args.dst, args.column)
    print("replaced:", dict(counts) or "nothing found")
    print("NOTE: names and addresses are NOT detected. Read %s before sharing it." % args.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
