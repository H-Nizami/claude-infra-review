# 0004. Fail-closed guard and trusted review code

## Status

Accepted (2026-10-22).

## Context

A PR can alter instructions and executable scripts. The action restores selected
configuration paths from the base branch, but that does not secure every script,
dependency, prompt, or schema in a checkout of PR code.

## Decision

Keep the standard-library PreToolUse guard under `.claude/hooks/`, fail closed on
malformed input, and resolve docs paths before allowing local edits. Restrict CI
tools to Read/Grep/Glob independently of the hook. Use a trusted checkout for
executable review and posting code; materialize PR inputs as data. Do not execute
PR scripts in a job carrying OAuth or GitHub comment permission.

## Consequences

The workflow deliberately strengthens the original spec's checkout-head steps.
Trusted code changes need to land before a PR can use them. Hooks are one layer,
not an operating-system sandbox. Prompt injection can still distort findings, so
humans inspect results and the S14 regression.

Contract: [Claude Code hooks](https://code.claude.com/docs/en/hooks),
[action security](https://github.com/anthropics/claude-code-action/blob/main/docs/security.md).
