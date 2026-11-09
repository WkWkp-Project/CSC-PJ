"""Export collected question types to CSV (and/or print counts by category).

    python3 -m phase8.tools.export_collected --db data/assist.db --out data/collected.csv
    python3 -m phase8.tools.export_collected --db data/assist.db --summary
    python3 -m phase8.tools.export_collected --db data/assist.db --cases --summary --out data/cases.csv

--cases reads the case table that is always kept (category, route, time; no text,
no customer identity), so it works even with ASSIST_STORE_TEXT off.

The CSV has an empty true_intent column: fill it in, then run
phase8.tools.evaluate on the file to measure the classifier.
"""

from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import sys
from collections import Counter


class ExportError(Exception):
    pass


def fetch(db_path: str) -> list[tuple]:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        return conn.execute(
            "SELECT collected_at,channel,text,predicted_intent,route FROM collected_text ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError:
        raise ExportError("no collected_text table: was the server run with ASSIST_STORE_TEXT=1?")
    finally:
        conn.close()


def fetch_cases(db_path: str) -> list[tuple]:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        return conn.execute(
            "SELECT opened_at,primary_intent,route,status FROM assist_case ORDER BY opened_at"
        ).fetchall()
    except sqlite3.OperationalError:
        raise ExportError("no assist_case table: has the server received any messages yet?")
    finally:
        conn.close()


def cases_csv_text(rows: list[tuple]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["opened_at", "category", "route", "status"])
    for at, intent, route, status in rows:
        w.writerow([at, intent or "", route or "", status])
    return buf.getvalue()


def write_cases_csv(rows: list[tuple], out: str) -> None:
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads Thai
        fh.write(cases_csv_text(rows))


def cases_summary(rows: list[tuple]) -> str:
    by_intent = Counter(r[1] or "(none)" for r in rows)
    by_day = Counter(r[0][:10] for r in rows)
    lines = ["cases: %d" % len(rows), "", "by category:"]
    lines += ["  %-8s %d" % (k, v) for k, v in by_intent.most_common()]
    lines += ["", "by day:"] + ["  %s %d" % (k, v) for k, v in sorted(by_day.items())]
    return "\n".join(lines)


def collected_csv_text(rows: list[tuple]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["text", "true_intent", "predicted_intent", "route", "channel", "collected_at"])
    for at, channel, text, pred, route in rows:
        w.writerow([text, "", pred or "", route or "", channel, at])
    return buf.getvalue()


def write_csv(rows: list[tuple], out: str) -> None:
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads Thai
        fh.write(collected_csv_text(rows))


def summary(rows: list[tuple]) -> str:
    by_intent = Counter(r[3] or "(none)" for r in rows)
    by_day = Counter(r[0][:10] for r in rows)
    lines = ["total: %d" % len(rows), "", "by predicted category:"]
    lines += ["  %-8s %d" % (k, v) for k, v in by_intent.most_common()]
    lines += ["", "by day:"] + ["  %s %d" % (k, v) for k, v in sorted(by_day.items())]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--cases", action="store_true", help="use the case table (no text) instead of collected text")
    args = ap.parse_args(argv)
    if not (args.out or args.summary):
        ap.error("give --out and/or --summary")
    try:
        return _run(args)
    except ExportError as exc:
        raise SystemExit(str(exc))


def _run(args) -> int:
    if args.cases:
        crows = fetch_cases(args.db)
        if args.summary:
            print(cases_summary(crows))
        if args.out:
            write_cases_csv(crows, args.out)
            print("wrote %d rows to %s" % (len(crows), args.out))
        return 0
    rows = fetch(args.db)
    if args.summary:
        print(summary(rows))
    if args.out:
        write_csv(rows, args.out)
        print("wrote %d rows to %s (names and addresses are NOT scrubbed: read it before sharing)" % (len(rows), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
