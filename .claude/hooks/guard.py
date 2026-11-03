#!/usr/bin/env python3
"""Fail-closed PreToolUse policy. Independent of repository imports and packages."""
import json
import os
from pathlib import Path
import re
import shlex
import sys


def contained(path, root):
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def docs_path(value, root):
    return isinstance(value, str) and contained(root / value, root / "docs")


def shell_rule(command, root):
    # Shell is a language, not an argv list. Reject expansion/redirection and
    # interpreters rather than attempting to implement a shell parser.
    if not isinstance(command, str) or not command.strip():
        return "malformed Bash input"
    if re.search(r"[$`<>\n\r(){}]", command):
        return "shell expansion or redirection"
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return "malformed shell quoting"
    segments, current = [], []
    for token in tokens:
        if token in (";", "&&", "||", "|", "&"):
            if not current:
                return "empty shell segment"
            segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    for argv in segments:
        # Support env assignments, but no env options capable of altering PATH,
        # loaders or interpreters; unknown options fail closed.
        if argv[0] == "env":
            argv = argv[1:]
            while argv and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*=[A-Za-z0-9_.-]*", argv[0]):
                if argv[0].split("=", 1)[0] != "FOO":
                    return "environment execution wrapper"
                argv = argv[1:]
        if not argv:
            return "empty command"
        tool, args = argv[0], argv[1:]
        if "/" in tool:
            return "executable path is not allowed"
        if any("=" in arg for arg in args if arg.startswith(("--config", "--plugin"))):
            return "executable configuration"
        # A deliberately short local read-command allowlist also blocks unknown
        # network clients, wrappers, aliases, functions, scripts and future verbs.
        if tool == "git":
            if not args or args[0] not in {"diff", "show", "status", "log", "ls-files"}:
                return "git mutation or configuration"
            if any(a.startswith(("--ext-diff", "--textconv", "--output")) for a in args):
                return "git external execution or output"
        elif tool in {"terraform", "tofu"}:
            if not args or args[0] not in {"plan", "validate", "version", "fmt"}:
                return "infrastructure mutation"
            if args[0] == "fmt" and "-check" not in args:
                return "formatter write"
            if any(a.startswith(("-out", "-generate-config-out")) for a in args):
                return "plan output write"
        elif tool == "kubectl":
            if not args or args[0] not in {"get", "describe", "logs", "version", "api-resources", "explain"}:
                return "cluster mutation"
        elif tool == "helm":
            if not args or args[0] not in {"list", "status", "get", "version", "show"}:
                return "helm mutation"
        elif tool == "aws":
            if len(args) < 2 or not (args[1].startswith(("get-", "list-", "describe-"))):
                return "cloud mutation"
            if any(a.startswith(("--endpoint", "--cli-input")) for a in args):
                return "cloud endpoint or executable input"
        elif tool == "gh":
            if not args:
                return "unknown GitHub command"
            if args[0] == "pr" and len(args) > 1 and args[1] in {"view", "diff", "list", "checks"}:
                pass
            elif args[0] == "api":
                if any(a in {"-f", "-F", "--field", "--raw-field", "--input", "--hostname"} or
                       a.startswith(("-f", "-F", "--field=", "--raw-field=", "--input=", "--hostname=")) for a in args):
                    return "GitHub API mutation or endpoint"
                for i, arg in enumerate(args):
                    if arg in {"-X", "--method"} and (i + 1 >= len(args) or args[i + 1] != "GET"):
                        return "GitHub API mutation"
                    if arg.startswith(("-X", "--method=")) and arg not in {"-X", "--method=GET", "-XGET"}:
                        return "GitHub API mutation"
            else:
                return "GitHub mutation"
        elif tool in {"cat", "head", "tail", "wc", "pwd", "ls", "rg", "grep", "find"}:
            if any(a in {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fls", "-fprint", "-fprint0", "-fprintf", "--pre", "--pre-glob"} or
                   a.startswith(("--pre=", "--pre-glob=")) for a in args):
                return "reader execution or write"
        else:
            return "command outside read-only allowlist"
    return None


def decide(payload, environ=None):
    environ = os.environ if environ is None else environ
    root = Path(environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return "malformed hook input"
    name, inputs = payload.get("tool_name"), payload["tool_input"]
    if name == "StructuredOutput":
        # Claude's internal JSON-schema delivery tool has no side effects.
        # Its payload is validated again before any result is posted.
        return None
    if name in {"Read", "Grep", "Glob"}:
        value = inputs.get("file_path") if name == "Read" else inputs.get("path", ".")
        if (not isinstance(value, str) or value.startswith("~") or "$" in value or "`" in value
                or not contained(root / value, root)):
            return "read outside project"
        resolved = (root / value).resolve()
        if any(part in {".git", ".claude-pr", ".credentials.json", "auth.json"} or part.startswith(".env")
               for part in resolved.relative_to(root).parts):
            return "sensitive project path"
        if name in {"Grep", "Glob"}:
            relative = resolved.relative_to(root).parts
            if not relative or relative[0] not in {"fixtures", "cir-input", "docs", "prompts", "schema"}:
                return "recursive reads require an explicit review-data directory"
            for directory, dirs, files in os.walk(resolved, followlinks=False):
                if any((Path(directory) / child).is_symlink() for child in dirs + files):
                    return "recursive reads cannot traverse a tree containing links"
        for key in ("pattern", "glob") if name == "Glob" else ("glob",):
            pattern = inputs.get(key, "")
            if not isinstance(pattern, str) or pattern.startswith(("/", "~")) or ".." in pattern.split("/"):
                return "pattern outside project"
            if any(part.startswith(".env") or part in {".git", ".credentials.json", "auth.json"} for part in pattern.split("/")):
                return "sensitive search pattern"
        return None
    if name in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        value = inputs.get("file_path", inputs.get("notebook_path"))
        if environ.get("CIR_ALLOW_DOCS_WRITES") == "1" and docs_path(value, root):
            return None
        return "writes require opt-in and a resolved docs path"
    if name == "Bash":
        if environ.get("CI") or environ.get("CIR_REVIEW_MODE") == "1":
            return "Bash is disabled in review mode"
        return shell_rule(inputs.get("command"), root)
    return "tool outside read-only allowlist"


def main():
    try:
        payload = json.loads(sys.stdin.read(100_000))
        reason = decide(payload)
    except (ValueError, TypeError, OSError, RuntimeError):
        reason = "malformed hook input"
    if reason:
        # Reasons contain only trusted policy text, never attacker-controlled args.
        print("Blocked: " + reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
