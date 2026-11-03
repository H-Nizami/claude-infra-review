"""Unit tests for scripts/normalize.py (no scanners needed: raw outputs are synthetic)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("normalize", ROOT / "scripts" / "normalize.py")
normalize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(normalize)

KEYS = {"tool", "rule_id", "file", "line_start", "line_end", "severity", "message", "category"}


@pytest.mark.parametrize(
    "tool,raw,expected",
    [
        ("trivy", "CRITICAL", "critical"),
        ("trivy", "HIGH", "high"),
        ("trivy", "MEDIUM", "medium"),
        ("trivy", "LOW", "low"),
        ("trivy", "UNKNOWN", "info"),
        ("checkov", "HIGH", "high"),
        ("checkov", None, "medium"),
        ("checkov", "WEIRD", "medium"),
        ("tflint", "error", "high"),
        ("tflint", "warning", "medium"),
        ("tflint", "notice", "low"),
        ("terraform", "error", "high"),
        ("terraform", "warning", "low"),
        ("tofu", "error", "high"),
        ("kubeconform", "invalid", "high"),
        ("kubeconform", "error", "high"),
        ("terraform-fmt", "diff", "low"),
        ("unknown-tool", "HIGH", "info"),
    ],
)
def test_severity_map(tool, raw, expected):
    assert normalize.map_severity(tool, raw) == expected


def test_all_mapped_severities_are_valid():
    for table in normalize.SEVERITY_MAP.values():
        assert set(table.values()) <= set(normalize.SEVERITIES)


def test_repo_rule_map_uses_only_known_categories():
    rule_map = normalize.load_rule_map(ROOT / "scanners" / "rule_map.yaml")
    assert set(rule_map.values()) <= normalize.CATEGORIES
    assert all(":" in k for k in rule_map)


def test_rule_map_rejects_unknown_category(tmp_path):
    p = tmp_path / "rm.yaml"
    p.write_text('"trivy:X-1": not_a_category\n')
    with pytest.raises(ValueError):
        normalize.load_rule_map(p)


def test_parse_fmt():
    text = "main.tf\n--- old/main.tf\n+++ new/main.tf\n@@ -1 +1 @@\n-a=1\n+a = 1\n"
    [f] = normalize.parse_fmt(text)
    assert f["file"] == "fixtures/terraform/main.tf"
    assert (f["tool"], f["rule_id"], f["severity"]) == ("terraform-fmt", "fmt", "low")


def test_parse_validate():
    data = {
        "valid": False,
        "diagnostics": [
            {
                "severity": "error",
                "summary": "Unsupported argument",
                "detail": "An argument named \"x\" is not expected here.",
                "range": {"filename": "main.tf", "start": {"line": 7}, "end": {"line": 7}},
            }
        ],
    }
    [f] = normalize.parse_validate("tofu", data)
    assert f["file"] == "fixtures/terraform/main.tf"
    assert (f["line_start"], f["line_end"], f["severity"]) == (7, 7, "high")
    assert f["message"].startswith("Unsupported argument: ")


def test_parse_tflint():
    data = {
        "issues": [
            {
                "rule": {"name": "aws_db_instance_invalid_type", "severity": "error"},
                "message": "\"db.x\" is an invalid value",
                "range": {"filename": "main.tf", "start": {"line": 162}, "end": {"line": 162}},
            }
        ],
        "errors": [],
    }
    [f] = normalize.parse_tflint(data)
    assert (f["rule_id"], f["file"], f["severity"]) == ("aws_db_instance_invalid_type", "fixtures/terraform/main.tf", "high")


def test_parse_trivy_prefixes_scan_root_and_skips_passes():
    data = {
        "Results": [
            {
                "Target": "terraform/main.tf",
                "Misconfigurations": [
                    {"ID": "AWS-0107", "Severity": "CRITICAL", "Title": "Open ingress", "Message": "0.0.0.0/0",
                     "Status": "FAIL", "CauseMetadata": {"StartLine": 113, "EndLine": 113}},
                    {"ID": "AWS-0104", "Severity": "HIGH", "Title": "ok", "Status": "PASS", "CauseMetadata": {}},
                ],
            },
            {"Target": "k8s/deployment.yaml", "Misconfigurations": None},
        ]
    }
    [f] = normalize.parse_trivy(data)
    assert (f["tool"], f["rule_id"], f["file"], f["line_start"], f["severity"]) == (
        "trivy", "AWS-0107", "fixtures/terraform/main.tf", 113, "critical")


def test_parse_checkov_list_and_dict_forms():
    check = {"check_id": "CKV_AWS_24", "check_name": "No SSH from 0.0.0.0/0", "file_path": "/terraform/main.tf",
             "file_line_range": [94, 124], "resource": "aws_security_group.app", "severity": None}
    one = normalize.parse_checkov({"check_type": "terraform", "results": {"failed_checks": [check]}})
    many = normalize.parse_checkov([{"check_type": "terraform", "results": {"failed_checks": [check]}},
                                    {"check_type": "kubernetes", "results": {"failed_checks": []}}])
    assert one == many
    [f] = one
    assert (f["file"], f["line_start"], f["line_end"], f["severity"]) == ("fixtures/terraform/main.tf", 94, 124, "medium")
    assert "aws_security_group.app" in f["message"]


def test_parse_checkov_empty():
    assert normalize.parse_checkov(None) == []
    assert normalize.parse_checkov({"passed": 0, "failed": 0}) == []


def test_kubeconform_maps_rendered_resource_to_source_file(tmp_path):
    k8s = tmp_path / "fixtures" / "k8s"
    k8s.mkdir(parents=True)
    (k8s / "netpol.yaml").write_text(
        "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: a\n---\n"
        "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: b\nspec: {}\n"
    )
    index = normalize.k8s_source_index(k8s, tmp_path)
    assert index[("NetworkPolicy", "a")] == ("fixtures/k8s/netpol.yaml", 1, 4)
    assert index[("NetworkPolicy", "b")] == ("fixtures/k8s/netpol.yaml", 6, 10)
    data = {"resources": [
        {"filename": "k8s.rendered.yaml", "kind": "NetworkPolicy", "name": "b", "status": "statusInvalid", "msg": "bad"},
        {"filename": "k8s.rendered.yaml", "kind": "Service", "name": "x", "status": "statusValid", "msg": ""},
    ]}
    [f] = normalize.parse_kubeconform(data, index)
    assert (f["file"], f["line_start"], f["line_end"], f["rule_id"], f["severity"]) == (
        "fixtures/k8s/netpol.yaml", 6, 10, "invalid", "high")


def test_finalize_sorts_dedupes_and_categorises():
    a = normalize._finding("trivy", "AWS-0107", "fixtures/terraform/main.tf", 113, 113, "critical", "x")
    b = normalize._finding("checkov", "CKV_AWS_24", "fixtures/terraform/main.tf", 94, 124, "medium", "y")
    c = normalize._finding("trivy", "KSV-0017", "fixtures/k8s/deployment.yaml", 43, 43, "high", "z")
    out = normalize.finalize([a, b, a, c], {"trivy:AWS-0107": "network_open"})
    assert [(f["file"], f["line_start"]) for f in out] == [
        ("fixtures/k8s/deployment.yaml", 43), ("fixtures/terraform/main.tf", 94), ("fixtures/terraform/main.tf", 113)]
    assert out[2]["category"] == "network_open"
    assert out[0]["category"] == "other"
    assert all(set(f) == KEYS for f in out)


def test_finding_clamps_bad_lines_and_truncates_message():
    f = normalize._finding("trivy", "X", "fixtures/a", 0, None, "low", "m " * 500)
    assert (f["line_start"], f["line_end"]) == (1, 1)
    assert len(f["message"]) <= normalize.MAX_MESSAGE


def test_normalize_end_to_end(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "fixtures" / "k8s").mkdir(parents=True)
    (out / "fmt.txt").write_text("")
    (out / "tf-validate.json").write_text(json.dumps({"valid": True, "diagnostics": []}))
    (out / "trivy.json").write_text(json.dumps({"Results": [{"Target": "k8s/deployment.yaml", "Misconfigurations": [
        {"ID": "KSV-0017", "Severity": "HIGH", "Title": "Privileged", "Message": "m", "Status": "FAIL",
         "CauseMetadata": {"StartLine": 43, "EndLine": 43}}]}]}))
    (out / "checkov.json").write_text(json.dumps({"passed": 0, "failed": 0}))
    rm = tmp_path / "rm.yaml"
    rm.write_text('"trivy:KSV-0017": privileged_container\n')
    assert normalize.main([str(out), "--target-root", str(tmp_path), "--rule-map", str(rm)]) == 0
    [f] = json.loads((out / "normalized.json").read_text())
    assert f == {"tool": "trivy", "rule_id": "KSV-0017", "file": "fixtures/k8s/deployment.yaml", "line_start": 43,
                 "line_end": 43, "severity": "high", "message": "Privileged: m", "category": "privileged_container"}


@pytest.mark.parametrize("bad_output", [None, "", "null", "{not-json"])
@pytest.mark.parametrize("name", ["tf-validate.json", "tofu-validate.json", "tflint.json", "kubeconform.json", "trivy.json", "checkov.json"])
def test_complete_scan_rejects_missing_or_bad_scanner_output(tmp_path, name, bad_output):
    for filename in ["tf-validate.json", "tofu-validate.json", "tflint.json", "kubeconform.json", "trivy.json", "checkov.json"]:
        (tmp_path / filename).write_text("{}")
    if bad_output is None:
        (tmp_path / name).unlink()
    else:
        (tmp_path / name).write_text(bad_output)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        normalize.normalize(tmp_path, ROOT, ROOT / "scanners/rule_map.yaml", require_complete=True)
