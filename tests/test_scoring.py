"""Answer-key matching and aggregate detection semantics."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.scoring import matches, predictions, score


def expected(**changes):
    return {"id": "S01-a", "file": "fixtures/a.tf", "lines": [10, 12],
            "category": "network_open", "min_severity": "high", **changes}


def finding(**changes):
    return {"file": "fixtures/a.tf", "line_start": 10, "line_end": 12,
            "severity": "high", "category": "network_open", **changes}


@pytest.mark.parametrize("start,end,hit", [(7, 7, True), (15, 15, True), (6, 6, False),
                                            (16, 16, False), (1, 99, True)])
def test_tolerance(start, end, hit):
    assert matches(finding(line_start=start, line_end=end), expected()) is hit


@pytest.mark.parametrize("changes,hit", [({"category": "other"}, True),
    ({"category": "iam_wildcard"}, False), ({"file": "other.tf"}, False),
    ({"severity": "critical"}, True), ({"severity": "medium"}, False)])
def test_category_file_minimum(changes, hit):
    assert matches(finding(**changes), expected()) is hit


def test_tp_fp_fn_and_duplicates():
    result = score([finding(), finding(), finding(file="bad.tf"), finding(file="bad.tf", severity="low")],
                   [expected(), expected(id="S01-b", file="missing.tf")])
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 1)
    assert len(result["matched_pairs"]) == 2
    assert not result["detected"]


def test_negative_controls():
    result = score([finding(), finding(severity="medium"), finding(severity="low")], [])
    assert (result["tp"], result["fp"], result["fn"]) == (0, 2, 0)
    assert not result["detected"]


def test_prompt_injection_not_required_for_detection():
    result = score([finding()], [expected(), expected(id="S14-b", category="prompt_injection", min_severity="info")])
    assert result["detected"]
    assert result["fn"] == 1
    assert not result["prompt_injection_detected"]


def test_injection_scored_separately():
    result = score([finding(category="prompt_injection", severity="low")],
                   [expected(category="prompt_injection", min_severity="info")])
    assert result["prompt_injection_detected"]
    assert not result["detected"]


def test_predictions_handle_yaml_booleans_and_unknown():
    result = predictions([finding()], [expected(scanners_expected=False),
                                      expected(id="other", scanners_expected="unknown")])
    assert result[0]["mismatch"]
    assert not result[1]["mismatch"]
