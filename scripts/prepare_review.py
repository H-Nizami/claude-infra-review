#!/usr/bin/env python3
"""Prepare PR data with trusted code; never execute anything from the PR tree."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import uuid


def git(*args):
    return subprocess.check_output(["git", "--no-pager", "-C", os.environ.get("CIR_SOURCE", "."), *args])


def resolve_metadata(data, trusted, repository, default_branch):
    head, base = data["head"]["sha"], data["base"]["sha"]
    if not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)
               for sha in (head, base, trusted)):
        raise ValueError("invalid commit metadata")
    if (data["state"] != "open" or data["base"]["ref"] != default_branch
            or data["base"]["repo"]["full_name"] != repository):
        raise ValueError("PR must target this repository's default branch")
    # GitHub may retain an older PR base SHA after the default branch advances.
    # Trusted executable policy is pinned independently to its current checkout.
    return {"pr": str(data["number"]), "head_sha": head, "base_sha": base,
            "trusted_sha": trusted,
            "is_cross_repo": str(data["head"]["repo"]["full_name"] != repository).lower(),
            "labeled": str(any(x["name"] == "claude-review" for x in data["labels"])).lower()}


def snapshot(head, base, destination):
    if not all(re.fullmatch(r"[0-9a-f]{40}", s) for s in (head, base)):
        raise ValueError("invalid commit metadata")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    diff = git("-c", "core.quotePath=false", "diff", "--no-ext-diff", "--no-textconv", f"{base}...{head}", "--")
    if len(diff) > 1_000_000:
        raise ValueError("diff exceeds review limit")
    (destination / "pr.diff").write_bytes(diff)
    entries = git("ls-tree", "-rz", head, "--", "fixtures/").split(b"\0")
    total = 0
    for entry in filter(None, entries):
        info, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = info.decode().split()
        path = raw_path.decode()
        if mode not in {"100644", "100755"} or kind != "blob" or ".." in path.split("/"):
            raise ValueError("fixture links and submodules are forbidden")
        if not re.fullmatch(r"fixtures/(terraform|k8s)/[A-Za-z0-9_.-]+", path):
            continue
        if not (path.endswith((".tf", ".yaml", ".yml", ".hcl")) or path.endswith(".terraform.lock.hcl")):
            continue
        content = git("cat-file", "blob", oid)
        total += len(content)
        if len(content) > 200_000 or total > 1_000_000:
            raise ValueError("fixture snapshot exceeds review limit")
        target = destination / "files" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    # Executable linter plugin configuration is always trusted policy.
    target = destination / "files/fixtures/terraform/.tflint.hcl"
    target.write_bytes(Path("fixtures/terraform/.tflint.hcl").read_bytes())


def outputs(pr, head, base):
    model = os.environ.get("REVIEW_MODEL") or "claude-sonnet-5-5"
    turns = os.environ.get("REVIEW_TURNS") or "6"
    budget = os.environ.get("REVIEW_BUDGET") or "0.20"
    if model not in {"claude-sonnet-5-5", "claude-haiku-5-5"}:
        raise ValueError("unsupported model")
    if not turns.isdigit() or not 1 <= int(turns) <= 6:
        raise ValueError("turn cap must be 1..6")
    from decimal import Decimal
    if not Decimal("0") < Decimal(budget) <= Decimal("0.20"):
        raise ValueError("per-run estimate cap must be <= 0.20")
    prompt = Path("prompts/review.md").read_text()
    for key, value in (("PR_NUMBER", pr), ("BASE_SHA", base), ("HEAD_SHA", head)):
        prompt = prompt.replace("{{" + key + "}}", value)
    schema = json.dumps(json.loads(Path("schema/findings.schema.json").read_text()), separators=(",", ":"))
    args = (f"--model {model} --max-turns {turns} --max-budget-usd {budget} "
            "--tools Read,Grep,Glob --allowedTools Read,Grep,Glob,StructuredOutput "
            "--disallowedTools Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task,Agent "
            "--permission-mode dontAsk --setting-sources project --strict-mcp-config "
            "--mcp-config '{\"mcpServers\":{}}' --no-session-persistence --json-schema " + shlex.quote(schema))
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        for key, value in (("text", prompt), ("args", args), ("model", model)):
            delimiter = uuid.uuid4().hex
            stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("snapshot", "prompt"))
    parser.add_argument("--pr", default=os.environ.get("PR", ""))
    parser.add_argument("--head", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", ""))
    args = parser.parse_args()
    if not args.pr.isdigit():
        raise ValueError("invalid PR number")
    if args.mode == "snapshot":
        snapshot(args.head, args.base, "cir-input")
    else:
        outputs(args.pr, args.head, args.base)


if __name__ == "__main__":
    main()
