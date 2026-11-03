"""Contain target-controlled scanner suppressions and unsafe fixture paths."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_scanner_policy.py"
SPEC = importlib.util.spec_from_file_location("scanner_policy", SCRIPT)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


@pytest.mark.parametrize("directive", [
    "#checkov:skip=CKV_AWS_24: text", "# checkov:skip=CKV_AWS_24", "# CHECKOV:SKIP=CKV_AWS_24",
    'checkov.io/skip1: "CKV_K8S_16=ignored"', '"checkov.io/skip2": "CKV_K8S_20"',
    "#trivy:ignore:AWS-0107", "# trivy:ignore:AVD-AWS-0107", "# TRIVY:IGNORE:AWS-0107",
    "#tfsec:ignore:aws-vpc-no-public-ingress-sgr", "# tfsec:ignore:AWS006", "# TFSEC:IGNORE:AWS006",
])
@pytest.mark.parametrize("suffix", [".tf", ".yaml", ".yml"])
def test_rejects_suppressions(tmp_path, directive, suffix):
    path = tmp_path / "fixtures/k8s" / ("example" + suffix)
    path.parent.mkdir(parents=True)
    path.write_text(directive)
    assert policy.violations(tmp_path) == [path.relative_to(tmp_path).as_posix()]


def test_current_fixture_and_scanner_cache_pass():
    assert policy.violations(ROOT) == []


def test_ignores_unrelated_documentation(tmp_path):
    path = tmp_path / "fixtures/POLICY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# checkov:skip=CKV_AWS_24")
    assert policy.violations(tmp_path) == []


def test_rejects_symlink_without_reading_target(tmp_path):
    outside = tmp_path / "outside.yaml"
    outside.write_text("safe placeholder")
    fixture = tmp_path / "fixtures/k8s/symlink.yaml"
    fixture.parent.mkdir(parents=True)
    fixture.symlink_to(outside)
    assert policy.violations(tmp_path) == ["fixtures/k8s/symlink.yaml"]


def test_allows_generated_provider_cache_directory_link(tmp_path):
    cache = tmp_path / "provider-cache"
    cache.mkdir()
    link = tmp_path / "fixtures/terraform/.terraform/providers/provider-package"
    link.parent.mkdir(parents=True)
    link.symlink_to(cache, target_is_directory=True)
    assert policy.violations(tmp_path) == []


def test_cli_diagnostic_quotes_filename_and_never_prints_content(tmp_path):
    path = tmp_path / "fixtures/terraform/line\nbreak.tf"
    path.parent.mkdir(parents=True)
    marker = "SYNTHETIC-CONTENT-MUST-NOT-APPEAR"
    path.write_text("# checkov:skip=CKV_AWS_24 " + marker)
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert marker not in result.stderr and "CKV_AWS_24" not in result.stderr
    assert "line\\nbreak.tf" in result.stderr
    assert len(result.stderr.splitlines()) == 1


def test_scan_rejects_suppression_before_starting_any_tool(tmp_path):
    (tmp_path / "fixtures/k8s").mkdir(parents=True)
    tf = tmp_path / "fixtures/terraform"
    tf.mkdir()
    (tf / "main.tf").write_text("#checkov:skip=CKV_AWS_24")
    result = subprocess.run([str(ROOT / "scripts/scan.sh"), str(tmp_path), str(tmp_path / "out")], capture_output=True, text=True)
    assert result.returncode == 1
    assert "scanner policy rejected fixture" in result.stderr
    assert not (tf / ".terraform").exists()
    assert not (tmp_path / "out/tf-validate.json").exists()
