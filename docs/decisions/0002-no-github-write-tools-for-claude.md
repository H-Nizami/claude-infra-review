# 0002. Claude gets no GitHub write tools; a deterministic step posts the comment

## Status

Accepted (2026-10-22). Implemented in [`.github/workflows/review.yml`](../../.github/workflows/review.yml) and [`scripts/post_comment.py`](../../scripts/post_comment.py).

## Context

The reviewer reads pull request content: diffs, file contents, commit messages and scanner output. All of that is attacker-controlled on a public or multi-contributor repo. A model that reads untrusted text and also holds write access (comment, push, approve, call `gh`) can be steered by prompt injection into using that access.

## Decision

- The Claude step runs with read-only tools (Read/Grep/Glob) and a read-only GitHub token. It produces only a findings JSON object that must validate against a schema.
- A separate job with no LLM renders that JSON and posts the sticky PR comment and inline notes through the GitHub REST API.
- Instructions found inside PR content are treated as data and reported as a finding, never followed.

## Consequences

- A successful prompt injection can at worst distort the findings JSON, which is schema-checked before posting; it cannot push code, approve, or post free text outside the rendered template.
- Posting logic is plain code that can be unit-tested and reviewed.
- Claude cannot ask follow-up questions on the PR or react to replies; the review is one shot per run.
