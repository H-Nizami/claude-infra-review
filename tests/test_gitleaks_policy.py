"""Exercise the allowlist with synthetic markers; no credentials are used."""

from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
GITLEAKS = ROOT / ".bin/gitleaks"


@pytest.mark.skipif(not GITLEAKS.exists(), reason="run make tools for gitleaks")
@pytest.mark.parametrize("relative,value,expected", [
    ("scenarios/S08-hardcoded-secret/patch.diff", "Example-Only-Not-A-Secret-0000", 0),
    ("scenarios/S08-hardcoded-secret/answer.yaml", "Example-Only-Not-A-Secret-0000", 0),
    ("scenarios/S08-hardcoded-secret/patch.diff", "Example-Only-Not-A-Secret-1111", 1),
    ("scenarios/S09-region-residency/patch.diff", "Example-Only-Not-A-Secret-0000", 1),
    ("scenarios/S08-hardcoded-secret/extra.txt", "Example-Only-Not-A-Secret-0000", 1),
])
def test_allowlist_requires_both_exact_path_and_value(tmp_path, relative, value, expected):
    config = tmp_path / "gitleaks-test.toml"
    # This test-only rule guarantees detection of the non-credential-shaped fixture.
    # Reuse the real allowlist verbatim, rather than duplicating its conditions.
    config.write_text((ROOT / ".gitleaks.toml").read_text().replace("useDefault = true", "useDefault = false") + '\n[[rules]]\nid = "generic-api-key"\nregex = \'\'\'(Example-Only-Not-A-Secret-[0-9]{4})\'\'\'\nsecretGroup = 1\n')
    target = tmp_path / "target"
    path = target / relative
    path.parent.mkdir(parents=True)
    path.write_text(value + "\n")
    result = subprocess.run([str(GITLEAKS), "dir", "--config", str(config), "--redact", "--no-banner", "."], cwd=target, capture_output=True, text=True)
    assert result.returncode == expected, result.stderr


@pytest.mark.skipif(not GITLEAKS.exists(), reason="run make tools for gitleaks")
@pytest.mark.parametrize("relative", ["scenarios/S08-hardcoded-secret/patch.diff", "outside.txt"])
def test_default_rules_still_detect_a_different_synthetic_value(tmp_path, relative):
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic test marker with sufficient entropy for generic-api-key.
    # It is manufactured locally and has no issuing service or authentication use.
    marker = "0123456789abcdef" * 3
    target.write_text(f'api_key = "{marker}"\n')
    result = subprocess.run([str(GITLEAKS), "dir", "--config", str(ROOT / ".gitleaks.toml"), "--redact", "--no-banner", "."], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
