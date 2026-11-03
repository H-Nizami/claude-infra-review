# Contributing

Claude Code as a read-only infra reviewer: deterministic scanners first, then
Claude explains and risk-ranks findings, with estimated-spend reservations and no
write access. [`CLAUDE.md`](CLAUDE.md) is the review project memory used by the
reviewer itself; this file covers working on the repository.

## Commands

- `make tools`: install pinned binaries into `.bin/`.
- `make lint`: actionlint, shellcheck, `d2 validate`, hygiene checks.
- `make test`: unit and fake-CLI integration tests plus hygiene checks.
- `make diagram`: render `docs/img/architecture.{svg,png}` (PNG 2400–4000 px wide, target 3000).
- `make up` / `make down`: not applicable (CI-only project).

Enabling live review runs is described in [`docs/activation.md`](docs/activation.md).

## Pinned versions

| Tool | Version | Where pinned |
|---|---|---|
| terraform | 1.17.0 | eval scenarios |
| opentofu | 1.13.2 | eval scenarios |
| tflint | v0.64.0 | scan job |
| kubeconform | v0.8.0 | scan job |
| checkov | 3.3.30 | scan job |
| d2 | v0.9.0 | `scripts/tools.sh` |
| actionlint | 1.7.12 | `scripts/tools.sh` |
| gitleaks | 8.30.1 | `scripts/tools.sh`, `security.yml` |
| trivy | v0.76.1 | `scripts/tools.sh`, `security.yml` |
| anthropics/claude-code-action | v1.0.258 = `6b6870e649b5ff408753befeaee5fc7989d4e6a9` | review workflow |
| GitHub Actions | commit SHAs | workflow `uses:` lines; table in [`docs/pins.md`](docs/pins.md) |

Pin every version. Check the upstream docs and `--help` output before upgrading a
tool or relying on a new flag.

## Conventions

- No secrets in the repo. Use placeholders only (for example account `000000000000`, `example.com`).
- No employer references. `scripts/check-hygiene.sh` and `scripts/check-author.sh` enforce the commit and content policy.
- Numbers in the README and diagram come from checked-in eval results. Unmeasured numbers are marked `Not yet measured: …`.
- Scenario counts in the diagram must match `scenarios/`.
- Every GitHub Action is pinned to a full commit SHA with a `# vX.Y.Z` comment.
- Workflows use least-privilege `permissions:` (top level `{}`, each job grants only what it needs).
- Claude gets no GitHub write tools; a deterministic job posts the PR comment (ADR 0002).

## Layout

- `docs/`: architecture diagram source, icons, rendered images, ADRs, pins, playbook, activation guide.
- `scripts/`: diagram rendering, tool installer, hygiene and author checks.
- `.github/workflows/`: CI, security scans, author check, review workflow.
- `fixtures/`, `scenarios/`, `scanners/`: baseline, answer keys, scanner policy.
- `eval/`: deterministic scoring and the persistent estimated-spend ledger.
- `.claude/`, `schema/`, `prompts/`: review guard, skills, output contract, prompt.

## Definition of done

`make lint test diagram` is green and `actionlint` is clean.
