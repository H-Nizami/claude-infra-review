# Rolling infrastructure review out to a team

## Goals and non-goals

Give reviewers a repeatable first pass over Terraform/OpenTofu and Kubernetes
changes. Deterministic scanners provide evidence; Claude combines that evidence
with policy and the diff. Humans decide whether a change is safe to merge. This
kit never approves PRs, changes infrastructure, or pushes fixes.

## Auth options

This workflow uses `CLAUDE_CODE_OAUTH_TOKEN` supplied by the repository owner. The
owner creates, sets, rotates, and revokes it; contributors never copy it into files
or logs. The secret is already configured in this repository. Check its presence
in repository settings without opening its value.

An `anthropic_api_key` is an alternative action input, with API billing rather than
subscription access. Bedrock, Vertex, Foundry, and workload identity federation are
deployment alternatives; they are not configured here. Choose one identity path
for a pilot and check the action's [authentication documentation](https://github.com/anthropics/claude-code-action/blob/main/docs/configuration.md)
before changing providers. Keep credentials restricted to the Claude job.

## Permission modes and tool allow-lists

CI and the eval expose Read, Grep, and Glob for repository access. The internal
StructuredOutput tool only delivers the schema JSON and has no side effects. The explicit tool list restricts
availability; the allow-list preapproves those read tools. Bash, file editing,
network tools, and delegation are disabled. The eval isolates project settings and
MCP configuration rather than inheriting personal plugins and servers.

The Claude job's GitHub token has `contents: read` and `pull-requests: read`. A
separate job has comment permission. Giving the action a read-only token also
contains its bundled GitHub tools. Forks never receive the OAuth secret.

## Hooks

`.claude/hooks/guard.py` is a standard-library PreToolUse hook. Malformed input and
unknown tool names fail closed. Exit 2 blocks a tool call with a reason; exit 0
permits it. Local docs editing needs `CIR_ALLOW_DOCS_WRITES=1` and a path resolving
inside `docs/`; CI and eval never enable it.

Keep hook commands self-contained under `.claude/`, which the action restores
from the PR base. Executable scripts, prompt, schema, dependencies, and the poster
also come from a trusted checkout. Merely restoring the hook does not make all
files from a PR safe to execute. Extend guard tests before changing its command
policy. See the [hook contract](https://code.claude.com/docs/en/hooks).

## Skills

`review-terraform` and `review-k8s` are short instructions with `name` and
`description` frontmatter. They direct attention to policy, stateful replacement,
IAM widening, host access, exposure, and operating limits. Add a skill when a new
type of infrastructure needs a distinct checklist. Keep each under 150 lines and
point to the shared severity rubric in `CLAUDE.md`.

## Prompt injection

Diffs, files, scanner messages, comments, and commit text are untrusted data. A
comment claiming security approval cannot override policy. S14 seeds that attack
alongside an open RDP rule; its injection finding is tracked separately.

Containment combines trusted executable code, read-only tools and token, schema
validation, and deterministic rendering. Model text is escaped before posting,
including HTML, Markdown links, and mentions. This limits effects of a compromised
answer; it cannot guarantee that the answer detects every risk. Review findings
against the actual diff.

## Cost control

The committed ledger starts at $0 of a $2 total **estimated** budget: $1.50 for
local eval and $0.50 for CI demos. Read it with `python3 eval/run.py --ledger-show`.
Eval reserves a per-call allowance before starting the CLI and records cost even
when a call fails. `--budget-usd` can lower the cap; it cannot raise it.

`--max-turns`, `--max-budget-usd`, timeouts, the `claude-review` label, and
`CIR_REVIEW_ENABLED` limit exposure. Subscription dollar values are estimates from
token counts and public list prices, not invoices. Unknown prices remain
unverified. A CLI that ignores its per-call limit can overrun a reservation;
the harness records the overrun and stops subsequent calls. It cannot reverse
usage already consumed.

GitHub runners do not share a writable local ledger. CI refuses a live call
without a precharged reservation on the trusted default branch for its exact
head SHA, run ID, and run attempt. The owner creates that reservation with
`scripts/reserve_ci.py` after a dry dispatch, commits it, and reruns all jobs for
the reserved attempt. A rerun needs its own reservation. Reconcile any reported
overrun before admitting another demo. Labels and concurrency alone do not enforce
a dollar cap. See the [activation guide](activation.md).

## Review rules

Use the severity rubric in `CLAUDE.md`. Critical/high findings need a human
response before rollout; lower findings can enter the normal backlog. Every
scanner finding must be retained or explicitly dropped with a reason. Review
those reasons when a scanner finding disappears.

`CIR_FAIL_ON` defaults to `none`; `high` and `critical` opt into a failure gate.
Posting a finding is never an approval or a request-changes review. When a finding
is wrong, add a regression scenario and explain any answer-key change rather than
silently tuning a score.

## Measuring it

Run `python3 eval/run.py --scenarios all --out .cache/scanners-replay` for a
free scanners-only baseline that preserves the published live report. Read
[`../eval/results/latest.md`](../eval/results/latest.md) for TP/FP/FN by scenario,
prediction mismatches, and semantic-only coverage. The two negative controls
measure false positives at medium severity or higher. The broader FP count means
findings that do not match the answer key at its required location/category/severity;
that includes lower-severity warnings about an expected risk, and does not prove
every unmatched warning is incorrect.

Add a patch relative to `fixtures/` and a post-patch answer key for a new scenario.
Keep scanner predictions unchanged after observation; record observed IDs with
provenance. Matching permits a three-line tolerance, and the generic `other`
category matches any expected category, so inspect the matched evidence too.

Live eval is an owner decision. After explicit approval, the owner runs
`CIR_ALLOW_CLAUDE=1 python3 eval/run.py --with-claude`. Never substitute a fake-CLI
test or scanners-only score for a measured Claude result.

## Rollout plan

Start on one private repository with CI activation disabled. Check baseline
scanners, guard tests, schema rejection, and renderer escaping. The owner enables
the variable and labels one same-repo demo PR only after checking the ledger.
Record its metadata before the next run.

Compare scanner and Claude detections, false positives, latency, estimated cost,
invalid outputs, and prompt-injection responses. Expand to more repositories only
after humans find comments useful. Default-on review requires a centralized budget
service and an explicit change to the label gate.

## Limits and failure modes

These are seeded examples, not evidence of coverage on arbitrary production PRs.
There is no AWS plan or apply, cluster deployment, or real cloud validation.
Provider schemas and scanner rules change; version pins and answer provenance
make changes reviewable, but network-provided rule/schema data can still vary.

Scanner crashes fail the scan rather than masquerading as a clean review. Invalid
model output fails validation. A skipped/failed Claude pass uses an explicitly
labelled scanner result. Fork PRs receive scanner artifacts; the workflow skips
model execution and comment posting for forks. Inline findings only attach to lines
actually present on the right side of a diff and are capped at ten.

Do not enable live runs until costs, authentication, model availability, and the
trusted workflow are checked in the target repository. Measured README claims
come only from a completed live eval.
