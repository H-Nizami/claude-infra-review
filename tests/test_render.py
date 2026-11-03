import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from render_comment import changed_lines, render, scanner_document

DIFF = "diff --git a/fixtures/terraform/main.tf b/fixtures/terraform/main.tf\n--- a/fixtures/terraform/main.tf\n+++ b/fixtures/terraform/main.tf\n@@ -1,3 +1,3 @@\n same\n-old\n+new\n tail\n"


def valid():
    return json.loads((ROOT / "tests/data/findings.valid.json").read_text())


def test_escapes_model_html_mentions_markdown():
    data = valid()
    data["summary"] = '<script>alert(1)</script> @user <b>x</b> [click](https://evil.example) ![x](evil) | table'
    for field in ("title", "why_it_matters", "suggested_fix", "rule_id"):
        data["findings"][0][field] = '<img src=x onerror=alert(1)> @team [x](evil)'
    body, inline = render(data, DIFF, head_sha="a" * 40)
    assert "<script>" not in body and "<img" not in body and "<b>" not in body
    assert "@user" not in body and "@\u200buser" in body
    assert "[click](" not in body and r"\[click\]\(" in body
    assert "https://evil" not in body
    assert len(inline) == 1 and "<img" not in inline[0]["body"]


def test_inline_right_side_hunk_only_and_max_ten():
    data = valid()
    data["findings"] *= 15
    _, inline = render(data, DIFF, head_sha="a" * 40)
    assert len(inline) == 10
    data["findings"][0]["line_end"] = 4
    _, inline = render(data, DIFF, head_sha="a" * 40)
    assert not inline
    assert changed_lines(DIFF) == {"fixtures/terraform/main.tf": {1, 2, 3}}


def test_metadata_does_not_render_arbitrary_values():
    body, _ = render(valid(), meta={"num_turns": "<script>", "total_cost_usd": "@user", "model": "@team"})
    assert "<script>" not in body and "@user" not in body and "unavailable" in body
    assert "estimate" in body and "subscription" in body


def test_scanner_fallback():
    f = valid()["findings"][0]
    item = {k: f[k] for k in ("file", "line_start", "line_end", "severity", "category", "rule_id")}
    item.update(tool="checkov", message="A risk")
    doc = scanner_document([item])
    assert doc["findings"][0]["source"] == "scanner"
    body, _ = render(doc, reason="gate off")
    assert "gate off" in body and "scanners" in body
    assert scanner_document([])["risk_level"] == "none"


def test_scanners_show_highest_severity_before_truncation():
    f = valid()["findings"][0]
    item = {k: f[k] for k in ("file", "line_start", "line_end", "severity", "category", "rule_id")}
    items = [dict(item, severity="medium", rule_id=str(i)) for i in range(30)]
    items.append(dict(item, severity="critical", rule_id="critical-at-end"))
    doc = scanner_document(items)
    assert doc["risk_level"] == "critical" and doc["findings"][0]["rule_id"] == "critical-at-end"
    assert "1 additional" in doc["summary"]


def test_maximum_schema_sized_output_stays_within_github_limit():
    data = valid()
    finding = data["findings"][0]
    for name, limit in (("file", 300), ("rule_id", 300), ("title", 120), ("why_it_matters", 600), ("suggested_fix", 800)):
        finding[name] = "&" * limit
    data["findings"] *= 30
    data["summary"] = "&" * 1200
    data["dropped_scanner_findings"] = [{"tool": "&" * 300, "rule_id": "&" * 300, "file": "&" * 300, "reason": "&" * 300}] * 100
    body, _ = render(data)
    assert len(body) < 60_000
    assert "artifact" in body
