"""Trust-boundary regression checks; no API calls or live model invocations."""
import json
import copy
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_review


def test_moving_default_branch_does_not_invalidate_pr_base():
    data = {"number": 1, "state": "open", "labels": [{"name": "claude-review"}],
            "head": {"sha": "c" * 40, "repo": {"full_name": "owner/repo"}},
            "base": {"sha": "b" * 40, "ref": "main", "repo": {"full_name": "owner/repo"}}}
    resolved = prepare_review.resolve_metadata(data, "a" * 40, "owner/repo", "main")
    assert resolved["trusted_sha"] == "a" * 40
    assert resolved["base_sha"] == "b" * 40
    assert resolved["is_cross_repo"] == "false"
    for field, value in (("ref", "other"), ("repo", {"full_name": "attacker/repo"})):
        invalid = copy.deepcopy(data)
        invalid["base"][field] = value
        with pytest.raises(ValueError):
            prepare_review.resolve_metadata(invalid, "a" * 40, "owner/repo", "main")


def test_secret_and_write_jobs_execute_only_trusted_checkout():
    workflow = yaml.safe_load((ROOT / ".github/workflows/review.yml").read_text())
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    assert jobs["claude"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert jobs["post"]["permissions"] == {"contents": "read", "pull-requests": "write"}
    for name in ("claude", "post"):
        checkouts = [step for step in jobs[name]["steps"] if step.get("uses", "").startswith("actions/checkout@")]
        assert len(checkouts) == 1
        assert checkouts[0]["with"]["ref"] == "${{ needs.scan.outputs.trusted_sha }}"
        assert checkouts[0]["with"]["persist-credentials"] is False
    for name, job in jobs.items():
        if name != "claude":
            assert "CLAUDE_CODE_OAUTH_TOKEN" not in json.dumps(job)
    action = next(s for s in jobs["claude"]["steps"] if s.get("uses", "").startswith("anthropics/"))
    assert action["with"]["show_full_output"] == "false"
    assert action["with"]["use_sticky_comment"] == "false"
    assert action["if"] == "steps.budget.outputs.allowed == 'true'"


def test_snapshot_rejects_links_without_reading_contents(monkeypatch, tmp_path):
    def git(*args):
        if "diff" in args:
            return b""
        if "ls-tree" in args:
            return b"120000 blob " + b"a" * 40 + b"\tfixtures/terraform/main.tf\0"
        pytest.fail("symlink target must never be opened")
    monkeypatch.setattr(prepare_review, "git", git)
    with pytest.raises(ValueError, match="links"):
        prepare_review.snapshot("a" * 40, "b" * 40, tmp_path / "cir-input")


def test_snapshot_overwrites_pr_linter_config_with_trusted_policy(monkeypatch, tmp_path):
    def git(*args):
        if "diff" in args:
            return b"bounded data"
        if "ls-tree" in args:
            return b"100644 blob " + b"a" * 40 + b"\tfixtures/terraform/.tflint.hcl\0"
        return b"malicious plugin config"
    monkeypatch.setattr(prepare_review, "git", git)
    monkeypatch.chdir(ROOT)
    prepare_review.snapshot("a" * 40, "b" * 40, tmp_path / "cir-input")
    assert (tmp_path / "cir-input/files/fixtures/terraform/.tflint.hcl").read_bytes() == (ROOT / "fixtures/terraform/.tflint.hcl").read_bytes()


@pytest.mark.parametrize("variable,value", [("REVIEW_MODEL", "x --tools Bash"), ("REVIEW_TURNS", "7"),
                                            ("REVIEW_TURNS", "6;evil"), ("REVIEW_BUDGET", ".21")])
def test_prompt_options_fail_closed(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        prepare_review.outputs("3", "a" * 40, "b" * 40)


def test_settings_guard_matches_every_tool_and_fails_on_crash():
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    matcher = settings["hooks"]["PreToolUse"][0]
    assert matcher["matcher"] == "*"
    assert matcher["hooks"][0]["onFailure"] == "block"
    assert matcher["hooks"][0]["command"].endswith("|| exit 2")
