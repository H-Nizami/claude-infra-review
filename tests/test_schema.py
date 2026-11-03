import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_findings import validate


@pytest.fixture
def findings():
    return json.loads((ROOT / "tests/data/findings.valid.json").read_text())


def test_valid(findings):
    assert validate(findings) == findings


@pytest.mark.parametrize("field,value", [("file", "../../proc/environ"), ("file", "/etc/passwd"),
                                           ("file", "fixtures\\x"), ("severity", "urgent"),
                                           ("confidence", 2), ("line_start", 0), ("line_end", 1),
                                           ("category", "invented"), ("title", "x" * 121)])
def test_invalid_fields(findings, field, value):
    findings["findings"][0][field] = value
    with pytest.raises(ValueError):
        validate(findings)


def test_no_extra_properties(findings):
    for target in (findings, findings["findings"][0]):
        data = copy.deepcopy(findings)
        if target is findings:
            data["shell_command"] = "danger"
        else:
            data["findings"][0]["shell_command"] = "danger"
        with pytest.raises(ValueError):
            validate(data)


def test_invalid_fixture():
    with pytest.raises(ValueError):
        validate(json.loads((ROOT / "tests/data/findings.invalid.json").read_text()))
