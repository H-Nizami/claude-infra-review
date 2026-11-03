"""Real subprocess tests use a fake executable; no model call can occur."""
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval import run
from eval.claude_runner import ClaudeFailure, TOKEN_KEYS, command, estimate_cost, parse_response

EMPTY = {"summary": "No findings", "risk_level": "none", "findings": [], "dropped_scanner_findings": []}


@pytest.fixture
def rehearsal(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("eval", "schema", "prompts", "fixtures", "scenarios", "bin"):
        (root / name).mkdir()
    shutil.copy2(ROOT / "eval/pricing.yaml", root / "eval/pricing.yaml")
    shutil.copy2(ROOT / "schema/findings.schema.json", root / "schema/findings.schema.json")
    (root / "prompts/review.md").write_text("Review {{PR_NUMBER}} {{BASE_SHA}} {{HEAD_SHA}}")
    (root / "fixtures/file.txt").write_text("before\n")
    (root / "eval/spend-ledger.json").write_text(json.dumps({"budget_usd": 1, "split": {"eval": 1, "ci": 0}, "entries": []}))
    for number in range(1, 5):
        directory = root / "scenarios" / f"S{number:02d}-example"
        directory.mkdir()
        (directory / "patch.diff").write_text("diff --git a/fixtures/file.txt b/fixtures/file.txt\n--- a/fixtures/file.txt\n+++ b/fixtures/file.txt\n@@ -1 +1 @@\n-before\n+after\n")
        (directory / "answer.yaml").write_text(f"id: S{number:02d}\ntitle: Test scenario\nkind: positive\nexpected: []\n")
    calls = tmp_path / "calls.jsonl"
    fake = root / "bin/claude"
    fake.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
with open(os.environ["FAKE_CALLS"], "a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "unknown":
    print("unknown option --max-turns do-not-leak", file=sys.stderr)
    sys.exit(1)
if mode == "malformed":
    print("not json")
    sys.exit(0)
payload = {"structured_output": {"summary": "No findings", "risk_level": "none", "findings": [], "dropped_scanner_findings": []},
           "total_cost_usd": 0.4, "num_turns": 2, "is_error": False,
           "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
if mode == "invalid":
    payload["structured_output"] = {"findings": []}
if mode == "missing":
    payload.pop("total_cost_usd")
    payload.pop("usage")
if mode == "result":
    payload["result"] = json.dumps(payload.pop("structured_output"))
if mode == "malformed-cache":
    payload["usage"]["cache_creation"] = "malformed"
print(json.dumps(payload))
''')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CALLS", str(calls))
    monkeypatch.delenv("CIR_ALLOW_CLAUDE", raising=False)
    monkeypatch.delenv("CIR_ALLOW_DOCS_WRITES", raising=False)
    def scanner(trusted_root, target, output):
        assert trusted_root == root
        output.mkdir(parents=True)
        return [], {"fake-scanner": "test-only"}
    monkeypatch.setattr(run, "scan", scanner)
    return root, calls


def test_default_is_offline_and_identical(rehearsal):
    root, calls = rehearsal
    reports = []
    for _ in range(2):
        assert run.main([], root=root) == 0
        path = max((root / "eval/results").glob("*-scanners.json"), key=lambda p: p.stat().st_mtime_ns)
        report = json.loads(path.read_text())
        report.pop("generated_at")
        reports.append(report)
    assert reports[0] == reports[1]
    assert not calls.exists()
    markdown = (root / "eval/results/latest.md").read_text()
    assert "Claude: not run" in markdown
    assert markdown.count("| S0") == 4


def test_gate_refuses_without_even_invoking_fake(rehearsal):
    root, calls = rehearsal
    assert run.main(["--with-claude"], root=root) == 2
    assert not calls.exists()
    assert not (root / "eval/results").exists()


def test_eval_never_copies_live_git_metadata(rehearsal, monkeypatch):
    root, calls = rehearsal
    copytree = shutil.copytree

    def source_only(source, *args, **kwargs):
        assert not (Path(source) / ".git").exists()
        return copytree(source, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", source_only)
    assert run.main([], root=root) == 0
    assert not calls.exists()


@pytest.mark.parametrize("failure,code,status", [
    (RuntimeError("scanner crashed"), 1, "failed"),
    (KeyboardInterrupt(), 130, "interrupted"),
])
def test_partial_scan_never_reports_complete(rehearsal, monkeypatch, failure, code, status):
    root, calls = rehearsal
    scanner = run.scan
    count = 0

    def interrupted_scan(*args):
        nonlocal count
        count += 1
        if count == 3:  # Baseline and S01 succeed; S02 fails.
            raise failure
        return scanner(*args)

    monkeypatch.setattr(run, "scan", interrupted_scan)
    assert run.main([], root=root) == code
    report = json.loads(next((root / "eval/results").glob("*-scanners.json")).read_text())
    assert report["status"] == status
    assert len(report["scenarios"]) == 1
    assert not calls.exists()


def test_budget_stops_before_third_fake_call(rehearsal, monkeypatch, capsys):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    assert run.main(["--with-claude"], root=root) == 3
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(invocations) == 2
    assert all(args[args.index("--tools") + 1] == "Read,Grep,Glob" for args in invocations)
    assert invocations[0][invocations[0].index("--max-budget-usd") + 1] == "0.12"
    assert invocations[1][invocations[1].index("--max-budget-usd") + 1] == "0.12"
    ledger = json.loads((root / "eval/spend-ledger.json").read_text())
    assert sum(entry["reported_usd"] for entry in ledger["entries"]) == .8
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert all("estimate" in line and "cumulative=" in line for line in lines)
    report = json.loads(next((root / "eval/results").glob("*-claude-*.json")).read_text())
    assert report["status"] == "budget_stop"
    assert len(report["scenarios"]) == 3
    assert report["totals"]["claude"]["evaluated_scenarios"] == 2


@pytest.mark.parametrize("mode,code", [("unknown", 2), ("malformed", 1), ("invalid", 1)])
def test_errors_stop_and_charge_without_retry(rehearsal, monkeypatch, capsys, mode, code):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    monkeypatch.setenv("FAKE_MODE", mode)
    assert run.main(["--with-claude"], root=root) == code
    assert len(calls.read_text().splitlines()) == 1
    ledger = json.loads((root / "eval/spend-ledger.json").read_text())
    assert len(ledger["entries"]) == 1
    assert ledger["entries"][0]["status"] == "failed"
    if mode == "invalid":
        assert ledger["entries"][0]["reported_usd"] == .4
    captured = capsys.readouterr()
    assert "do-not-leak" not in captured.out + captured.err


def test_missing_cost_charged_conservatively(rehearsal, monkeypatch):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    monkeypatch.setenv("FAKE_MODE", "missing")
    assert run.main(["--with-claude", "--scenarios", "S01"], root=root) == 0
    entry = json.loads((root / "eval/spend-ledger.json").read_text())["entries"][0]
    assert entry["est_usd"] is None and entry["reported_usd"] is None
    assert entry["per_run_usd"] == .12
    report = json.loads(next((root / "eval/results").glob("*-claude-*.json")).read_text())
    assert report["scenarios"][0]["call"]["price"] == "unverified"


def test_result_fallback(rehearsal, monkeypatch):
    root, _ = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    monkeypatch.setenv("FAKE_MODE", "result")
    assert run.main(["--with-claude", "--scenarios", "S01"], root=root) == 0


def test_malformed_cache_details_use_conservative_estimate(rehearsal, monkeypatch):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    monkeypatch.setenv("FAKE_MODE", "malformed-cache")
    assert run.main(["--with-claude", "--scenarios", "S01"], root=root) == 0
    assert len(calls.read_text().splitlines()) == 1
    report = json.loads(next((root / "eval/results").glob("*-claude-*.json")).read_text())
    assert report["status"] == "complete"
    assert any("cache_creation" in warning for warning in report["scenarios"][0]["call"]["warnings"])


def test_cli_budget_cannot_raise_cap(rehearsal, monkeypatch):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    assert run.main(["--with-claude", "--budget-usd", "5"], root=root) == 3
    assert len(calls.read_text().splitlines()) == 2


def test_cli_budget_can_lower_cap(rehearsal, monkeypatch):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    assert run.main(["--with-claude", "--budget-usd", ".1"], root=root) == 3
    assert not calls.exists()


def test_no_docs_write_override(rehearsal, monkeypatch):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    monkeypatch.setenv("CIR_ALLOW_DOCS_WRITES", "1")
    assert run.main(["--with-claude"], root=root) == 2
    assert not calls.exists()


def test_haiku_requires_affordable_comparison(rehearsal, monkeypatch, capsys):
    root, calls = rehearsal
    monkeypatch.setenv("CIR_ALLOW_CLAUDE", "1")
    assert run.main(["--with-claude", "--model", "claude-haiku-5-5"], root=root) == 3
    assert not calls.exists()
    assert "skipped: insufficient budget" in capsys.readouterr().err


def test_baseline_drift_subtracted():
    baseline = {"tool": "scanner", "rule_id": "old", "file": "f", "line_start": 1}
    added = {**baseline, "rule_id": "new"}
    assert run.delta_findings([added, baseline], [baseline]) == [added]


def test_command_is_argv_with_strict_isolation():
    args = command("claude-sonnet-5-5", 6, .12, {}, "hello")
    assert "--bare" not in args
    assert args[args.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in args and "--no-session-persistence" in args
    assert args[args.index("--settings") + 1] == ".claude/settings.json"
    assert args[-2:] == ["--", "hello"]


def test_unverified_pricing_never_guessed():
    tokens = dict.fromkeys(TOKEN_KEYS, 100)
    assert estimate_cost(tokens, None) is None
    assert estimate_cost(tokens, {"input_per_mtok": None}) is None


def test_verified_pricing_accounts_for_all_tokens():
    pricing = {"input_per_mtok": 2, "output_per_mtok": 10,
               "cache_write_per_mtok": 2.5, "cache_write_1h_per_mtok": 4,
               "cache_read_per_mtok": .1}
    assert estimate_cost(dict.fromkeys(TOKEN_KEYS, 100), pricing) == .00161
    assert estimate_cost(dict.fromkeys(TOKEN_KEYS, 100), pricing,
                         {"cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 0}}) == .00146


def test_defensive_parse_missing_and_invalid():
    response = parse_response(json.dumps({"result": json.dumps(EMPTY), "usage": {"input_tokens": True}, "total_cost_usd": -1}), None)
    assert all(value is None for value in response["tokens"].values())
    assert response["reported_usd"] is None
    assert response["num_turns"] is None
    assert response["warnings"]
    with pytest.raises(ClaudeFailure):
        parse_response("[]", None)
