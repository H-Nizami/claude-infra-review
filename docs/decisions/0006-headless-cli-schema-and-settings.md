# 0006. Match the CLI schema dialect and load trusted settings explicitly

## Status

Accepted (2026-10-23), observed with Claude Code 2.1.309.

## Context

The first live startup rejected the draft 2020-12 schema before producing model
usage. The CLI also warned that project permissions in a new temporary workspace
were ignored until that workspace was trusted. Unit tests using a fake CLI cannot
exercise either startup behavior.

## Decision

Use JSON Schema draft 7, which expresses this contract without losing any of its
constraints. Select the matching Python validator from the declared dialect.
Pass the trusted `.claude/settings.json` explicitly with `--settings` in local
eval, as the action already does. Keep the tool restriction, project-only setting
sources, MCP isolation, and output validation. Allow the CLI's internal
`StructuredOutput` delivery tool through the hook and permission allow-list;
it only returns data. The built-in tool set remains Read/Grep/Glob. Blocking that
delivery tool caused repeated output attempts until the smoke budget was reached.

## Consequences

Temporary eval workspaces need no interactive trust acceptance. Failed startup
attempts remain conservatively charged in the ledger when no usage is available.
Future CLI upgrades need a live smoke review before a larger measurement run.
