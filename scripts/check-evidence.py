#!/usr/bin/env python3
"""Allow a measured headline only when it matches a complete live eval report."""
import json
import math
import hashlib
from collections import Counter
from pathlib import Path
import sys


def check(root):
    candidates = sorted((root / "eval/results").glob("*-claude-*.json"))
    report = json.loads(candidates[-1].read_text())
    assert report["status"] == "complete" and report["config"]["with_claude"]
    expected = {p.name.split("-", 1)[0] for p in (root / "scenarios").iterdir() if p.is_dir()}
    assert set(report["config"]["scenarios"]) == expected
    rows = report["scenarios"]
    assert len(rows) == len(expected) * report["config"]["runs"]
    assert Counter(row["id"] for row in rows) == Counter({key: report["config"]["runs"] for key in expected})
    assert all(row.get("claude") is not None and row.get("call") for row in rows)
    for source in report.get("source_reports", []):
        path = (root / source["path"]).resolve()
        path.relative_to(root.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
    positives = [row for row in rows if row["kind"] == "positive"]
    scanner_hits = sum(row["scanners"]["detected"] for row in positives)
    model_hits = sum(row["claude"]["detected"] for row in positives)
    false_positives = sum(row["claude"]["fp"] for row in rows)
    costs = [row["call"]["est_usd"] for row in rows]
    assert all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in costs)
    headline = (f"Scanners alone caught {scanner_hits}/{len(positives)} seeded misconfigs; "
                f"with Claude {model_hits}/{len(positives)}, with {false_positives} false positives, "
                f"at ${sum(costs) / len(costs):.6f} per PR (estimated: tokens × list price).")
    assert (root / "eval/results/headline.txt").read_text().strip() == headline
    line = next(line for line in (root / "README.md").read_text().splitlines()
                if line.startswith("> **Result:**"))
    assert line == "> **Result:** " + headline


if __name__ == "__main__":
    try:
        check(Path(__file__).resolve().parents[1])
    except (AssertionError, IndexError, KeyError, OSError, ValueError, StopIteration):
        print("check-evidence: measured headline needs a matching complete live eval", file=sys.stderr)
        raise SystemExit(1)
    print("check-evidence: measured headline matches complete live eval")
