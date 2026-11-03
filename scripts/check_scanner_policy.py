#!/usr/bin/env python3
"""Reject target-controlled scanner suppressions before any scanner runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

DIRECTIVE = re.compile(r"(?:checkov\s*:\s*skip|(?:trivy|tfsec)\s*:\s*ignore|checkov\s*\.io\s*/\s*skip)", re.IGNORECASE)


def violations(target: Path) -> list[str]:
    target = target.resolve()
    rejected = []
    for relative in ("fixtures/terraform", "fixtures/k8s"):
        directory = target / relative
        # Never inspect a symlink to content outside the scanned checkout.
        if directory.is_symlink() or not directory.resolve().is_relative_to(target):
            rejected.append(relative)
            continue
        for path in sorted(directory.rglob("*")):
            display = path.relative_to(target).as_posix()
            if path.is_symlink() and ".terraform" in path.relative_to(target).parts and path.suffix.lower() not in {".tf", ".yaml", ".yml"}:
                # Init creates provider-cache directory links, never source files.
                # rglob does not traverse these links; scanners exclude .terraform.
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(target):
                rejected.append(display)
                continue
            if path.suffix.lower() not in {".tf", ".yaml", ".yml"}:
                continue
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    rejected.append(display)
                    continue
                if DIRECTIVE.search(content):
                    rejected.append(display)
    return rejected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    rejected = violations(args.target)
    for path in rejected:
        # JSON quoting neutralizes newlines/control characters in untrusted paths.
        # Never echo repository content, matched annotations, or scanner messages.
        print(f"scanner policy rejected fixture: {json.dumps(path, ensure_ascii=True)}", file=sys.stderr)
    return int(bool(rejected))


if __name__ == "__main__":
    raise SystemExit(main())
