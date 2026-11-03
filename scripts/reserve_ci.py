#!/usr/bin/env python3
"""Owner utility: precharge one exact CI attempt; never invokes Claude or GitHub."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.ledger import Ledger, entry_cost


def amount(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("invalid ledger amount")
    return result


def cost(entry):
    return entry_cost(entry)


def identity(run_id, run_attempt, head_sha):
    if not str(run_id).isdigit() or not str(run_attempt).isdigit() or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise ValueError("invalid CI reservation identity")
    return {"run_id": str(run_id), "run_attempt": str(run_attempt), "head_sha": head_sha}


def check_caps(ledger):
    entries = ledger["entries"]
    total = sum((cost(e) for e in entries), Decimal(0))
    ci = sum((cost(e) for e in entries if e.get("source") == "ci"), Decimal(0))
    if total > min(amount(ledger["budget_usd"]), Decimal("2.00")):
        raise ValueError("total estimate budget exhausted")
    if ci > min(amount(ledger["split"]["ci"]), Decimal("0.50")):
        raise ValueError("CI estimate budget exhausted")


def authorized(ledger, reservation, usd):
    check_caps(ledger)
    matches = [e for e in ledger["entries"] if e.get("source") == "ci" and e.get("ci_reservation") == reservation]
    return len(matches) == 1 and cost(matches[0]) >= amount(usd) > 0


def reserve(ledger, reservation, usd):
    usd = amount(usd)
    if not 0 < usd <= Decimal("0.20"):
        raise ValueError("reservation must be >0 and <=0.20 USD estimated")
    if any(e.get("ci_reservation") == reservation for e in ledger["entries"]):
        raise ValueError("CI attempt already reserved")
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "source": "ci", "scenario": "ci-reservation",
             "model": None, "tokens": {}, "est_usd": float(usd), "reported_usd": None,
             "ci_reservation": reservation}
    # Validate the proposed ledger before changing the caller's in-memory state.
    candidate = dict(ledger, entries=ledger["entries"] + [entry])
    check_caps(candidate)
    ledger["entries"].append(entry)
    return ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=Path("eval/spend-ledger.json"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--usd", default="0.20")
    parser.add_argument("--check", action="store_true", help="Read-only authorization check used by CI")
    args = parser.parse_args()
    try:
        key = identity(args.run_id, args.run_attempt, args.head_sha)
        shared = Ledger(args.ledger)
        with shared.locked() as ledger:
            if args.check:
                if not authorized(ledger, key, args.usd):
                    print("CI review unavailable: exact precharged attempt reservation missing")
                    return 2
                return 0
            reserve(ledger, key, args.usd)
            shared.write(ledger)
        print("Reserved CI estimate; commit this ledger on the default branch before rerunning the exact attempt.")
    except (ValueError, KeyError, OSError, InvalidOperation):
        print("CI reservation refused: invalid identity, ledger, or estimate budget")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
