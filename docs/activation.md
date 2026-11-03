# Activation and operating constraints

Live review is off by default. This page lists the steps to run a live eval or a
CI review on a demo PR, and the constraints that shape the workflow. See the
[team playbook](playbook.md) for rollout guidance.

## Constraints

- S07 changes the database master username. The pinned AWS provider renames an
  `identifier` in place; `username` has ForceNew. Evidence is in its answer key.
- Trusted executable code and policy come from the current default branch. PR
  fixtures are bounded data snapshots with links/submodules rejected. Secret and
  posting jobs never execute a PR checkout's scripts.
- Review targets the default branch only. A moved PR head refuses stale posting.
  Forks receive scanner artifacts, without model secrets or write-token posting.
- The PR base SHA does not always equal the current default-branch tip (GitHub can
  keep an earlier base SHA after main advances). Resolution checks the base
  repository and branch name, and trusted code is pinned to the current
  default-branch checkout. A regression test covers this case.
- The hook matches all tools, constrains read paths, and fails closed on runtime
  failure as well as explicit denial. Local shell support is a narrow convenience,
  not a process sandbox. CI and eval provide no shell tool.
- OpenTofu's first initialization verifies a signed provider download. Its own
  dependency lock is cached separately from Terraform's, so later temporary copies
  can reuse verified provider packages. See [`../scanners/README.md`](../scanners/README.md).
- Budget admission uses persistent reservations. Subscription USD values are
  estimates; external consumption cannot be guaranteed if the CLI overruns its
  per-call limit. CI requires an exact precharged run attempt.
- Same-repo workflow authors remain trusted. A repository secret cannot be
  isolated from someone authorized to change/run workflows in that repository;
  protecting that boundary needs repository/environment access controls.
- `--max-turns` is documented by the action but absent from the pinned local CLI
  help. No fallback retry spends money.
- The eval initializes each scenario repository independently instead of copying
  live Git metadata, and disables automatic Git maintenance in temporary repos.

## Authentication

The workflow uses subscription OAuth through the `CLAUDE_CODE_OAUTH_TOKEN`
repository secret. Check its presence in repository settings without opening its
value.

## Running the live eval

```bash
. .venv/bin/activate
python3 eval/run.py --ledger-show
CIR_ALLOW_CLAUDE=1 python3 eval/run.py --with-claude
```

The local eval allowance is $1.50 estimated, under the $2 total. A budget stop
writes partial results and exits 3; do not raise the allowance to finish all
scenarios. Compare actual token metadata, invalid-output counts, false positives
and S14 before copying any headline into the README.

## Running a CI review on a demo PR

1. Open a demo PR for one scenario with `scripts/open-demo-pr.sh <ID>` and add the
   `claude-review` label. Never merge a demo PR: its seeded change breaks the
   clean fixture baseline.
2. Enable review:

   ```bash
   gh variable set CIR_REVIEW_ENABLED --body true -R H-Nizami/claude-infra-review
   ```

3. Dispatch `infrastructure-review` against a same-repo PR on the default branch.
   The first attempt has no reservation and skips Claude. Note its run ID and PR
   head SHA.
4. Precharge the next attempt locally:

   ```bash
   python3 scripts/reserve_ci.py --run-id RUN_ID --run-attempt 2 --head-sha HEAD_SHA --usd 0.20
   ```

   Replace the placeholders with that run's numeric ID and full head SHA, and
   match the actual next attempt number if it is no longer 2.
5. Commit and push the ledger on `main`, then rerun **all** jobs for the same run
   so the scan job resolves the new default-branch ledger. Never run a different
   attempt against the same reservation.
6. Inspect the `cir-findings` numeric metadata and reconcile any overrun before
   admitting another demo. A precharge already counts against the CI allowance; do
   not add the same cost again with `--ledger-add`.
7. Disable `CIR_REVIEW_ENABLED` again after the demo.

## Release

Confirm the README, diagram and green CI before tagging a release.

## Recovery

Keep activation disabled during changes to instructions, permissions or the
ledger. A scanner crash is an error, not an empty result. An invalid model
response remains a failed review. Failed/interrupted calls retain conservative
spend. Raw model outputs stay gitignored; publish only validated summaries and
numeric metadata. Never inspect authentication files or copy token values into
diagnostics.
