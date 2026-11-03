#!/usr/bin/env python3
"""Normalize raw scanner output in <out-dir> into <out-dir>/normalized.json.

Each finding: {tool, rule_id, file, line_start, line_end, severity, message, category}.
`file` is repo-relative (fixtures/...), severity is one of critical|high|medium|low|info,
category comes from scanners/rule_map.yaml ("<tool>:<rule_id>": <category>), else "other".
Output is sorted by (file, line_start, tool, rule_id) and de-duplicated.

Usage: normalize.py <out-dir> [--target-root DIR] [--rule-map FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

TF_DIR = "fixtures/terraform"
K8S_DIR = "fixtures/k8s"
SCAN_ROOT = "fixtures"  # trivy and checkov are run with this directory as their target

SEVERITIES = ("critical", "high", "medium", "low", "info")

CATEGORIES = frozenset(
    {
        "public_exposure", "network_open", "iam_wildcard", "iam_widening",
        "privileged_container", "host_access", "missing_limits", "destroy_protection",
        "stateful_replace", "hardcoded_secret", "data_residency", "cost_jump",
        "encryption", "prompt_injection", "other",
    }
)

# Tool severity vocabulary -> normalized severity. Unknown or missing values -> DEFAULT.
SEVERITY_MAP: dict[str, dict[str, str]] = {
    "trivy": {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "UNKNOWN": "info"},
    # checkov run offline (--skip-download) reports severity null; then DEFAULT applies.
    "checkov": {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "INFO": "info"},
    "tflint": {"error": "high", "warning": "medium", "notice": "low"},
    "terraform": {"error": "high", "warning": "low"},
    "tofu": {"error": "high", "warning": "low"},
    "kubeconform": {"invalid": "high", "error": "high"},
    "terraform-fmt": {"diff": "low"},
}
DEFAULT_SEVERITY = {"checkov": "medium"}
FALLBACK_SEVERITY = "info"

MAX_MESSAGE = 300


def map_severity(tool: str, raw: Any) -> str:
    table = SEVERITY_MAP.get(tool, {})
    if isinstance(raw, str) and raw in table:
        return table[raw]
    return DEFAULT_SEVERITY.get(tool, FALLBACK_SEVERITY)


def load_rule_map(path: Path) -> dict[str, str]:
    data = yaml.safe_load(path.read_text()) if path.exists() else None
    if not data:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping")
    bad = {k: v for k, v in data.items() if v not in CATEGORIES}
    if bad:
        raise ValueError(f"{path}: unknown categories {bad}")
    return {str(k): str(v) for k, v in data.items()}


def _rel(prefix: str, name: str) -> str:
    name = name.lstrip("/")
    if name.startswith("fixtures/"):
        return name
    return f"{prefix}/{name}" if name else prefix


def _finding(tool, rule_id, file, start, end, severity, message) -> dict[str, Any]:
    start = int(start) if start and int(start) > 0 else 1
    end = int(end) if end and int(end) >= start else start
    msg = " ".join(str(message or "").split())
    return {
        "tool": tool,
        "rule_id": str(rule_id),
        "file": file,
        "line_start": start,
        "line_end": end,
        "severity": severity,
        "message": msg[:MAX_MESSAGE],
    }


def _load_json(path: Path) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        return None
    return json.loads(path.read_text())


def parse_fmt(text: str) -> list[dict]:
    files = sorted(set(re.findall(r"^--- old/(.+)$", text, flags=re.M)))
    return [
        _finding("terraform-fmt", "fmt", _rel(TF_DIR, f), 1, 1, map_severity("terraform-fmt", "diff"),
                 "File is not in canonical terraform fmt format.")
        for f in files
    ]


def parse_validate(tool: str, data: Any) -> list[dict]:
    out = []
    for d in (data or {}).get("diagnostics", []) or []:
        rng = d.get("range") or {}
        msg = d.get("summary", "")
        if d.get("detail"):
            msg = f"{msg}: {d['detail']}"
        out.append(
            _finding(tool, "validate", _rel(TF_DIR, rng.get("filename", "")),
                     (rng.get("start") or {}).get("line"), (rng.get("end") or {}).get("line"),
                     map_severity(tool, d.get("severity")), msg)
        )
    return out


def parse_tflint(data: Any) -> list[dict]:
    out = []
    for i in (data or {}).get("issues", []) or []:
        rule = i.get("rule") or {}
        rng = i.get("range") or {}
        out.append(
            _finding("tflint", rule.get("name", "unknown"), _rel(TF_DIR, rng.get("filename", "")),
                     (rng.get("start") or {}).get("line"), (rng.get("end") or {}).get("line"),
                     map_severity("tflint", rule.get("severity")), i.get("message", ""))
        )
    for e in (data or {}).get("errors", []) or []:
        rng = e.get("range") or {}
        out.append(
            _finding("tflint", "error", _rel(TF_DIR, rng.get("filename", "")),
                     (rng.get("start") or {}).get("line"), (rng.get("end") or {}).get("line"),
                     map_severity("tflint", "error"), e.get("message", ""))
        )
    return out


def parse_trivy(data: Any) -> list[dict]:
    out = []
    for r in (data or {}).get("Results", []) or []:
        for m in r.get("Misconfigurations", []) or []:
            if m.get("Status", "FAIL") != "FAIL":
                continue
            cm = m.get("CauseMetadata") or {}
            out.append(
                _finding("trivy", m.get("ID") or m.get("AVDID", "unknown"), _rel(SCAN_ROOT, r.get("Target", "")),
                         cm.get("StartLine"), cm.get("EndLine"), map_severity("trivy", m.get("Severity")),
                         f"{m.get('Title', '')}: {m.get('Message', '')}")
            )
    return out


def parse_checkov(data: Any) -> list[dict]:
    reports = data if isinstance(data, list) else [data] if data else []
    out = []
    for rep in reports:
        for c in (rep.get("results") or {}).get("failed_checks", []) or []:
            rng = c.get("file_line_range") or [1, 1]
            out.append(
                _finding("checkov", c.get("check_id", "unknown"), _rel(SCAN_ROOT, c.get("file_path", "")),
                         rng[0], rng[-1], map_severity("checkov", c.get("severity")),
                         f"{c.get('check_name', '')} ({c.get('resource', '')})")
            )
    return out


def k8s_source_index(k8s_dir: Path, repo_root: Path) -> dict[tuple[str, str], tuple[str, int, int]]:
    """(kind, name) -> (repo-relative file, first line, last line) of the source document."""
    index: dict[tuple[str, str], tuple[str, int, int]] = {}
    for path in sorted(k8s_dir.glob("*.yaml")):
        lines = path.read_text().splitlines()
        start = 0
        docs: list[tuple[int, int]] = []
        for n, line in enumerate(lines):
            if line.strip() == "---":
                docs.append((start, n - 1))
                start = n + 1
        docs.append((start, len(lines) - 1))
        for s, e in docs:
            if e < s:
                continue
            try:
                doc = yaml.safe_load("\n".join(lines[s : e + 1]))
            except yaml.YAMLError:
                continue
            if isinstance(doc, dict) and doc.get("kind") and isinstance(doc.get("metadata"), dict):
                key = (str(doc["kind"]), str(doc["metadata"].get("name", "")))
                index.setdefault(key, (path.relative_to(repo_root).as_posix(), s + 1, e + 1))
    return index


def parse_kubeconform(data: Any, index: dict) -> list[dict]:
    out = []
    for r in (data or {}).get("resources", []) or []:
        status = str(r.get("status", "")).removeprefix("status")
        status = status.lower()
        if status not in ("invalid", "error"):
            continue
        file, start, end = index.get((r.get("kind", ""), r.get("name", "")), (K8S_DIR, 1, 1))
        out.append(
            _finding("kubeconform", status, file, start, end, map_severity("kubeconform", status),
                     f"{r.get('kind', '')}/{r.get('name', '')}: {r.get('msg', '')}")
        )
    return out


def finalize(findings: Iterable[dict], rule_map: dict[str, str]) -> list[dict]:
    seen = set()
    result = []
    for f in findings:
        f = dict(f, category=rule_map.get(f"{f['tool']}:{f['rule_id']}", "other"))
        key = (f["file"], f["line_start"], f["line_end"], f["tool"], f["rule_id"])
        if key in seen:
            continue
        seen.add(key)
        result.append(f)
    result.sort(key=lambda f: (f["file"], f["line_start"], f["tool"], f["rule_id"], f["line_end"]))
    return result


def normalize(out_dir: Path, target_root: Path, rule_map_path: Path, require_complete: bool = False) -> list[dict]:
    if require_complete:
        for name in ("tf-validate.json", "tofu-validate.json", "tflint.json", "kubeconform.json", "trivy.json", "checkov.json"):
            path = out_dir / name
            if _load_json(path) is None:
                raise ValueError(f"{path}: missing or empty scanner JSON output")
    rule_map = load_rule_map(rule_map_path)
    findings: list[dict] = []
    fmt = out_dir / "fmt.txt"
    if fmt.exists():
        findings += parse_fmt(fmt.read_text())
    findings += parse_validate("terraform", _load_json(out_dir / "tf-validate.json"))
    findings += parse_validate("tofu", _load_json(out_dir / "tofu-validate.json"))
    findings += parse_tflint(_load_json(out_dir / "tflint.json"))
    findings += parse_kubeconform(
        _load_json(out_dir / "kubeconform.json"), k8s_source_index(target_root / K8S_DIR, target_root)
    )
    findings += parse_trivy(_load_json(out_dir / "trivy.json"))
    findings += parse_checkov(_load_json(out_dir / "checkov.json"))
    return finalize(findings, rule_map)


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--target-root", type=Path, default=Path("."))
    ap.add_argument("--rule-map", type=Path, default=here / "scanners" / "rule_map.yaml")
    ap.add_argument("--require-complete", action="store_true", help="reject missing, empty or null required scanner JSON outputs")
    args = ap.parse_args(argv)
    result = normalize(args.out_dir, args.target_root.resolve(), args.rule_map, args.require_complete)
    (args.out_dir / "normalized.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
