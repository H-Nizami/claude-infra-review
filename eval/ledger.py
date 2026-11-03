"""Atomic, locked budget reservations. Interrupted calls retain their reservation."""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid


class BudgetStop(Exception):
    """No call may be started under the remaining budget."""


def money(value):
    try:
        if isinstance(value, bool):
            raise ValueError("boolean cost")
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError("cost must be finite and nonnegative")
        return result
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("invalid dollar amount") from exc


def entry_cost(entry):
    values = [money(entry[key]) for key in ("est_usd", "reported_usd")
              if entry.get(key) is not None]
    return max(values) if values else money(entry.get("per_run_usd", "0.12"))


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    def __init__(self, path, budget=None):
        self.path = Path(path).resolve()
        self.budget = None if budget is None else money(budget)

    @contextmanager
    def locked(self):
        digest = hashlib.sha256(str(self.path).encode()).hexdigest()
        with open(Path(tempfile.gettempdir()) / f"cir-ledger-{digest}.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(self.path.read_text())
            money(data["budget_usd"])
            for source in ("eval", "ci"):
                money(data["split"][source])
            for entry in data["entries"]:
                entry_cost(entry)
                if entry.get("source") not in ("eval", "ci", "manual"):
                    raise ValueError("unknown ledger source")
            yield data

    def write(self, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent,
                                             prefix=".ledger-", delete=False) as output:
                temporary = output.name
                json.dump(data, output, indent=2, allow_nan=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def caps(self, data, source="eval"):
        total = money(data["budget_usd"])
        cap = min(total, money(data["split"][source]))
        if self.budget is not None:
            cap = min(cap, self.budget)  # CLI overrides can only lower the ledger cap.
        return total, cap

    def snapshot(self):
        with self.locked() as data:
            total, cap = self.caps(data)
            spent = sum((entry_cost(e) for e in data["entries"]), Decimal(0))
            eval_spent = sum((entry_cost(e) for e in data["entries"]
                              if e["source"] in ("eval", "manual")), Decimal(0))
            return {"total_cap": float(total), "eval_cap": float(cap),
                    "spent": float(spent), "eval_spent": float(eval_spent),
                    "remaining": float(max(Decimal(0), min(total - spent, cap - eval_spent))),
                    "entries": data["entries"]}

    def reserve(self, scenario, model, per_run):
        requested = money(per_run)
        if not requested:
            raise ValueError("per-run reservation must be positive")
        with self.locked() as data:
            total, cap = self.caps(data)
            spent = sum((entry_cost(e) for e in data["entries"]), Decimal(0))
            eval_spent = sum((entry_cost(e) for e in data["entries"]
                              if e["source"] in ("eval", "manual")), Decimal(0))
            # Never repeat an observed per-call overrun with a smaller reservation.
            reserve = max([requested] + [entry_cost(e) for e in data["entries"]
                                         if e.get("model") == model])
            if spent + reserve > total or eval_spent + reserve > cap:
                raise BudgetStop("insufficient budget for the next reserved call")
            reservation = uuid.uuid4().hex
            data["entries"].append({"ts": now(), "source": "eval", "scenario": scenario,
                                    "model": model, "tokens": {}, "est_usd": None,
                                    "reported_usd": None, "per_run_usd": float(reserve),
                                    "reservation_id": reservation, "status": "reserved"})
            self.write(data)
            return reservation, float(reserve)

    def settle(self, reservation, tokens, estimate, reported, status="complete"):
        with self.locked() as data:
            entry = next(e for e in data["entries"] if e.get("reservation_id") == reservation)
            if entry["status"] != "reserved":
                raise ValueError("reservation already settled")
            for amount in (estimate, reported):
                if amount is not None:
                    money(amount)
            entry.update(tokens=tokens, est_usd=estimate, reported_usd=reported, status=status)
            entry["over_reservation"] = entry_cost(entry) > money(entry["per_run_usd"])
            self.write(data)
            return float(entry_cost(entry))

    def add(self, amount, note):
        amount = money(amount)
        with self.locked() as data:
            total, cap = self.caps(data, "ci")
            spent = sum((entry_cost(e) for e in data["entries"]), Decimal(0))
            ci_spent = sum((entry_cost(e) for e in data["entries"] if e["source"] == "ci"), Decimal(0))
            if spent + amount > total or ci_spent + amount > cap:
                raise BudgetStop("CI entry would exceed its ledger cap")
            data["entries"].append({"ts": now(), "source": "ci", "scenario": None,
                                    "model": None, "tokens": {}, "est_usd": float(amount),
                                    "reported_usd": None, "note": note})
            self.write(data)
