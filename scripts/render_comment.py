#!/usr/bin/env python3
"""Render bounded, escaped review comments from validated findings."""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

from validate_findings import validate

MARKER = "<!-- claude-infra-review:sticky -->"
SEVERITY = {"none": 0, "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def safe(value, limit=1200):
    text = re.sub(r"<[^>]*>", "", str(value))[:limit]
    text = "".join(c for c in text if unicodedata.category(c) not in {"Cc", "Cf"})
    text = html.escape(text, quote=True).replace("@", "@\u200b")
    text = text.replace("://", ":\u200b//").replace("www.", "www.\u200b")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~>])", r"\\\1", text)[:limit]


def changed_lines(diff):
    """Return RIGHT-side hunk line coordinates; no shell or patch execution."""
    result, path, line, in_hunk = {}, None, 0, False
    for text in diff.splitlines():
        if text.startswith("diff --git "):
            path, in_hunk = None, False
        elif text.startswith("+++ b/"):
            path = text[6:]
            result.setdefault(path, set())
        elif text.startswith("@@ "):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", text)
            in_hunk = bool(match)
            if match:
                line = int(match[1])
        elif path and in_hunk:
            if text.startswith("+"):
                result[path].add(line)
                line += 1
            elif text.startswith(" "):
                result[path].add(line)
                line += 1
            elif not text.startswith(("-", "\\")):
                in_hunk = False
    return result


def scanner_document(items):
    findings = []
    ordered = sorted(items, key=lambda i: (-SEVERITY[i['severity']], i['file'], i['line_start'], i['rule_id']))
    for item in ordered[:30]:
        findings.append({
            "file": item["file"], "line_start": item["line_start"],
            "line_end": item.get("line_end", item["line_start"]),
            "severity": item["severity"], "category": item["category"],
            "source": "scanner", "rule_id": item["rule_id"],
            "title": str(item.get("title", item.get("message", item["rule_id"])))[:120],
            "why_it_matters": str(item.get("message", "Deterministic scanner finding."))[:600],
            "suggested_fix": "Inspect the rule and fix the infrastructure configuration.",
            "confidence": 1,
        })
    risk = max((f["severity"] for f in findings), key=lambda s: SEVERITY[s], default="none")
    if risk == "info":
        risk = "none"
    omitted = max(0, len(items) - 30)
    summary = "Deterministic scanners-only review."
    if omitted:
        summary += f" Showing the 30 highest-severity findings; {omitted} additional findings are in the scanner artifact."
    return validate({"summary": summary, "risk_level": risk,
                     "findings": findings, "dropped_scanner_findings": []})


def render(data, diff="", meta=None, head_sha="", run_url="", reason=""):
    validate(data)
    meta = meta or {}
    lines = [MARKER, "## Infrastructure review", "", "Risk: **" + data["risk_level"] + "**",
             "", safe(data["summary"])]
    if reason:
        lines += ["", "Review mode: " + safe(reason, 200)]
    lines += ["", "| Severity | File:line | Title | Source |", "|---|---|---|---|"]
    inline, coordinates = [], changed_lines(diff)
    detail_budget = 32_000
    omitted_details = 0
    for finding in data["findings"]:
        f = finding
        lines.append(f"| {f['severity']} | {safe(f['file'], 300)}:{f['line_start']} | {safe(f['title'], 120)} | {f['source']} |")
        detail = (f"**{safe(f['title'], 120)}** — `{safe(f['rule_id'], 300)}`\n\n"
                  f"Why: {safe(f['why_it_matters'], 600)}\n\nFix: {safe(f['suggested_fix'], 800)}")
        if len(detail) <= detail_budget:
            lines += ["", "<details><summary>Finding details</summary>", "", detail, "", "</details>"]
            detail_budget -= len(detail)
        else:
            omitted_details += 1
        if len(inline) < 10 and f["line_end"] in coordinates.get(f["file"], set()):
            identity = f"{f['file']}\0{f['rule_id']}\0{f['line_start']}"
            marker = "<!-- cir:finding:" + hashlib.sha1(identity.encode()).hexdigest() + " -->"
            inline.append({"commit_id": head_sha, "path": f["file"], "line": f["line_end"],
                           "side": "RIGHT", "body": marker + "\n" + detail})
    if omitted_details:
        lines += ["", f"{omitted_details} additional detail sections are available in the validated findings artifact."]
    if data["dropped_scanner_findings"]:
        lines += ["", "### Dropped scanner findings"]
        dropped_budget, omitted_dropped = 5000, 0
        for item in data["dropped_scanner_findings"]:
            row = f"- {safe(item['tool'], 60)} `{safe(item['rule_id'], 100)}` {safe(item['file'], 150)}: {safe(item['reason'], 300)}"
            if len(row) <= dropped_budget:
                lines.append(row)
                dropped_budget -= len(row)
            else:
                omitted_dropped += 1
        if omitted_dropped:
            lines.append(f"{omitted_dropped} additional exclusions are available in the validated findings artifact.")
    tokens = meta.get("usage") or {}
    def number(value):
        return str(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else "unavailable"
    cost = number(meta.get("estimated_usd", meta.get("total_cost_usd")))
    cost_basis = "token counts × list price" if meta.get("estimated_usd") is not None else "CLI-reported USD estimate; list-price estimate not calculated"
    lines += ["", "---", f"Model: {safe(meta.get('model', 'not run'), 80)}; turns: {number(meta.get('num_turns'))}; "
              f"tokens in/out: {number(tokens.get('input_tokens'))}/{number(tokens.get('output_tokens'))}.",
              f"Estimated cost: {cost} USD (estimate: {cost_basis}; subscription auth is not billed per token).",
              "Commit: " + safe(head_sha, 40) + "."]
    # The URL is trusted workflow metadata, never supplied by model findings.
    if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/\d+", run_url):
        lines.append("[Workflow run](" + run_url + ")")
    return "\n".join(lines) + "\n", inline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--scanners", type=Path)
    parser.add_argument("--diff", type=Path, required=True)
    parser.add_argument("--meta", type=Path)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--run-url", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--output", type=Path, default=Path("comment.md"))
    parser.add_argument("--inline", type=Path, default=Path("inline.json"))
    parser.add_argument("--fail-on", choices=("none", "high", "critical"), default="none")
    args = parser.parse_args()
    try:
        data = json.loads(args.findings.read_text()) if args.findings else scanner_document(json.loads(args.scanners.read_text()))
        meta = json.loads(args.meta.read_text()) if args.meta and args.meta.exists() else {}
        body, inline = render(data, args.diff.read_text(), meta, args.head_sha, args.run_url, args.reason)
        args.output.write_text(body)
        args.inline.write_text(json.dumps(inline) + "\n")
    except (ValueError, KeyError, TypeError, OSError):
        print("Review rendering failed validation", file=sys.stderr)
        return 1
    return int(args.fail_on != "none" and any(SEVERITY[f["severity"]] >= SEVERITY[args.fail_on] for f in data["findings"]))


if __name__ == "__main__":
    sys.exit(main())
