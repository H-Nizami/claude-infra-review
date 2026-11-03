"""Reservations, crash accounting, conservative costs and split caps."""
import json
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.ledger import BudgetStop, Ledger, entry_cost, money


@pytest.fixture
def path(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"budget_usd": 2, "split": {"eval": 1, "ci": .5}, "entries": []}))
    return path


@pytest.mark.parametrize("value", [-1, "NaN", "Infinity", True, "bad"])
def test_invalid_money(value):
    with pytest.raises(ValueError):
        money(value)


@pytest.mark.parametrize("entry,cost", [({"est_usd": .2, "reported_usd": .4}, .4),
    ({"est_usd": .4, "reported_usd": .2}, .4), ({"est_usd": None, "reported_usd": .3}, .3),
    ({"est_usd": None, "reported_usd": None, "per_run_usd": .12}, .12),
    ({"est_usd": 0, "reported_usd": None}, 0)])
def test_cost_uses_max_and_fallback(entry, cost):
    assert float(entry_cost(entry)) == cost


def test_cannot_raise_or_lower_beyond_requested(path):
    assert Ledger(path, 5).snapshot()["eval_cap"] == 1
    assert Ledger(path, .3).snapshot()["eval_cap"] == .3
    ledger = Ledger(path, .3)
    ledger.reserve("S01", "test", .2)
    with pytest.raises(BudgetStop):
        ledger.reserve("S02", "test", .2)


def test_reservation_survives_restart(path):
    Ledger(path).reserve("S01", "test", .6)
    assert Ledger(path).snapshot()["spent"] == .6
    with pytest.raises(BudgetStop):
        Ledger(path).reserve("S02", "test", .6)


def test_fake_overrun_learns_safe_next_reservation(path):
    ledger = Ledger(path)
    for scenario in ("S01", "S02"):
        reservation, cap = ledger.reserve(scenario, "test", .12)
        ledger.settle(reservation, {}, None, .4)
    assert ledger.snapshot()["spent"] == .8
    with pytest.raises(BudgetStop):
        ledger.reserve("S03", "test", .12)


def test_unknown_cost_charges_full_reservation(path):
    ledger = Ledger(path)
    reservation, cap = ledger.reserve("S01", "test", .12)
    assert ledger.settle(reservation, {}, None, None, "failed") == .12
    assert ledger.snapshot()["entries"][0]["status"] == "failed"
    with pytest.raises(ValueError):
        ledger.settle(reservation, {}, None, .1)


def test_total_and_ci_caps(path):
    data = json.loads(path.read_text())
    data["budget_usd"] = 1
    path.write_text(json.dumps(data))
    ledger = Ledger(path)
    ledger.add(.4, "CI demo (estimate)")
    with pytest.raises(BudgetStop):
        ledger.add(.2, "too much CI")
    ledger.reserve("S01", "test", .6)
    with pytest.raises(BudgetStop):
        ledger.reserve("S02", "test", .1)


def test_concurrent_calls_cannot_double_reserve(path):
    def attempt(index):
        try:
            Ledger(path).reserve(str(index), "model", .6)
            return True
        except BudgetStop:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(attempt, range(2))) == 1
    assert Ledger(path).snapshot()["spent"] == .6


def test_ci_reservation_metadata_is_preserved(path):
    data = json.loads(path.read_text())
    data["entries"].append({"source": "ci", "scenario": "ci-reservation", "est_usd": .2,
                            "reported_usd": None, "ci_reservation": {"run_id": "1", "run_attempt": "1", "head_sha": "a" * 40}})
    path.write_text(json.dumps(data))
    ledger = Ledger(path)
    ledger.reserve("S01", "test", .1)
    assert ledger.snapshot()["entries"][0]["ci_reservation"]["run_id"] == "1"
