"""Measure how often the classifier agrees with a person's labels.

Input CSV columns: text, true_intent (I01..I18 or I99 for chit-chat/unclear).
Extra columns (staff_reply, needs_human) are ignored here.

    python3 -m phase8.tools.evaluate data/labeled.csv --misses data/misses.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict

from phase5.classifier_v2 import classify_v2

SENSITIVE = {"I03", "I07", "I14"}
VALID = {"I%02d" % i for i in range(1, 19)} | {"I99"}


def load(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for col in ("text", "true_intent"):
            if col not in (reader.fieldnames or []):
                raise SystemExit("missing column %r (have: %s)" % (col, reader.fieldnames))
        return [r for r in reader if (r.get("text") or "").strip()]


def evaluate(rows: list[dict]) -> dict:
    results, bad_labels = [], []
    for i, r in enumerate(rows, start=2):  # +2: header is line 1
        truth = (r.get("true_intent") or "").strip().upper()
        if truth not in VALID:
            bad_labels.append((i, truth))
            continue
        pred = classify_v2(r["text"], "").get("primary_intent", "I99")
        results.append({"line": i, "text": r["text"], "truth": truth, "pred": pred})

    n = len(results)
    correct = sum(1 for x in results if x["truth"] == x["pred"])
    support, tp, predicted = Counter(), Counter(), Counter()
    confusions = Counter()
    for x in results:
        support[x["truth"]] += 1
        predicted[x["pred"]] += 1
        if x["truth"] == x["pred"]:
            tp[x["truth"]] += 1
        else:
            confusions[(x["truth"], x["pred"])] += 1
    per_intent = {}
    for k in sorted(set(support) | set(predicted)):
        per_intent[k] = {
            "support": support[k],
            "recall": (tp[k] / support[k]) if support[k] else None,
            "precision": (tp[k] / predicted[k]) if predicted[k] else None,
        }
    sensitive_total = sum(1 for x in results if x["truth"] in SENSITIVE)
    sensitive_missed = [x for x in results if x["truth"] in SENSITIVE and x["pred"] not in SENSITIVE]
    return {
        "n": n, "accuracy": (correct / n) if n else None,
        "unsure_rate": (predicted["I99"] / n) if n else None,
        "per_intent": per_intent, "confusions": confusions.most_common(10),
        "sensitive_total": sensitive_total, "sensitive_missed": sensitive_missed,
        "misses": [x for x in results if x["truth"] != x["pred"]], "bad_labels": bad_labels,
    }


def fmt(v) -> str:
    return "-" if v is None else "%.0f%%" % (v * 100)


def report(res: dict) -> str:
    out = ["rows scored: %d" % res["n"]]
    if not res["n"]:
        return "\n".join(out + ["nothing to score: check the true_intent column"])
    out.append("accuracy (exact intent): %s   |   fell to 'unsure' (I99): %s" % (fmt(res["accuracy"]), fmt(res["unsure_rate"])))
    out.append("")
    out.append("%-6s %8s %8s %10s" % ("intent", "support", "recall", "precision"))
    for k, v in res["per_intent"].items():
        out.append("%-6s %8d %8s %10s" % (k, v["support"], fmt(v["recall"]), fmt(v["precision"])))
    out.append("")
    out.append("most common mistakes (truth -> predicted):")
    for (t, p), c in res["confusions"]:
        out.append("  %s -> %s : %d" % (t, p, c))
    out.append("")
    out.append("sensitive cases (I03/I07/I14) not recognised as sensitive: %d of %d"
               % (len(res["sensitive_missed"]), res["sensitive_total"]))
    for x in res["sensitive_missed"][:10]:
        out.append("  line %d: %s -> %s  %s" % (x["line"], x["truth"], x["pred"], x["text"][:60]))
    if res["bad_labels"]:
        out.append("")
        out.append("rows skipped, unknown label: %s" % res["bad_labels"][:10])
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--misses", help="write every wrong row to this CSV")
    args = ap.parse_args(argv)
    res = evaluate(load(args.csv))
    print(report(res))
    if args.misses:
        with open(args.misses, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["line", "text", "true_intent", "predicted"])
            for x in res["misses"]:
                w.writerow([x["line"], x["text"], x["truth"], x["pred"]])
        print("\nwrote %d misses to %s" % (len(res["misses"]), args.misses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
