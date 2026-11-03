"""Validate answer keys against real post-patch files without invoking scanners."""

from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = sorted((ROOT / "scenarios").iterdir())
CATEGORIES = set("public_exposure network_open iam_wildcard iam_widening privileged_container host_access missing_limits destroy_protection stateful_replace hardcoded_secret data_residency cost_jump encryption prompt_injection other".split())
SEVERITIES = {"critical", "high", "medium", "low", "info"}


def test_scenario_count():
    assert len(SCENARIOS) == 16


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda p: p.name)
def test_patch_and_answer_key(scenario, tmp_path):
    answer = yaml.safe_load((scenario / "answer.yaml").read_text())
    assert answer["id"] == scenario.name.split("-", 1)[0]
    assert answer["kind"] in {"positive", "negative"}
    assert answer["patch"] == "patch.diff"
    shutil.copytree(ROOT / "fixtures", tmp_path / "fixtures", ignore=shutil.ignore_patterns(".terraform"))
    patch = scenario / "patch.diff"
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patch)], cwd=tmp_path, check=True, capture_output=True)
    if answer["kind"] == "negative":
        assert answer["expected"] == []
    else:
        assert answer["expected"]
    for item in answer["expected"]:
        assert item["category"] in CATEGORIES
        assert item["severity"] in SEVERITIES
        assert item["min_severity"] in SEVERITIES
        assert item["scanners_expected"] in {"yes", "no", "unknown"}
        assert isinstance(item["semantic_only"], bool)
        assert item["file"] in answer["files"]
        assert not Path(item["file"]).is_absolute()
        path = (tmp_path / item["file"]).resolve()
        assert path.is_relative_to(tmp_path.resolve())
        start, end = item["lines"]
        assert 1 <= start <= end <= len(path.read_text().splitlines())
        assert item["scanner_rule_ids_source"] == "none-observed" or item["scanner_rule_ids_source"].startswith("observed-")
        assert isinstance(item["scanner_rule_ids"], list)


def test_skip_lists_are_small_justified_and_do_not_hide_seeded_rules():
    checkov_path = ROOT / "scanners/.checkov.yaml"
    checkov = yaml.safe_load(checkov_path.read_text())["skip-check"]
    trivy_path = ROOT / "scanners/.trivyignore"
    trivy = [line.strip() for line in trivy_path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert len(checkov) <= 15 and len(trivy) <= 15
    for path, skips in [(checkov_path, checkov), (trivy_path, trivy)]:
        lines = path.read_text().splitlines()
        for rule in skips:
            matching = [i for i, line in enumerate(lines) if line.strip().lstrip("- ") == rule]
            assert len(matching) == 1
            assert lines[matching[0] - 1].strip().startswith("#")
    for scenario in SCENARIOS:
        answer = yaml.safe_load((scenario / "answer.yaml").read_text())
        for item in answer["expected"]:
            assert not set(item["scanner_rule_ids"]) & set(checkov + trivy)
    for path in (ROOT / "fixtures").rglob("*"):
        if path.is_file() and ".terraform" not in path.parts:
            text = path.read_text()
            assert "checkov:skip" not in text and "trivy:ignore" not in text
