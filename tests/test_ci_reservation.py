import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reserve_ci import authorized, identity, reserve


def ledger():
    return {"budget_usd": 2, "split": {"eval": 1.5, "ci": 0.5}, "entries": []}


def test_exact_attempt_is_precharged_and_no_replays():
    state = ledger()
    key = identity("123", "2", "a" * 40)
    reserve(state, key, ".20")
    assert authorized(state, key, ".20")
    assert not authorized(state, identity("123", "3", "a" * 40), ".20")
    assert not authorized(state, identity("123", "2", "b" * 40), ".20")
    assert not authorized(state, identity("124", "2", "a" * 40), ".20")
    with pytest.raises(ValueError):
        reserve(state, key, ".20")


def test_shared_total_and_ci_caps():
    state = ledger()
    for run in (1, 2):
        reserve(state, identity(str(run), "1", "a" * 40), ".20")
    with pytest.raises(ValueError):
        reserve(state, identity("3", "1", "a" * 40), ".20")
    assert len(state["entries"]) == 2
    state = ledger()
    state["entries"] = [{"source": "eval", "est_usd": 1.9}]
    with pytest.raises(ValueError):
        reserve(state, identity("3", "1", "a" * 40), ".20")


@pytest.mark.parametrize("usd", ["-1", "0", "NaN", "Infinity", ".21"])
def test_invalid_reservations(usd):
    with pytest.raises(ValueError):
        reserve(ledger(), identity("1", "1", "a" * 40), usd)
