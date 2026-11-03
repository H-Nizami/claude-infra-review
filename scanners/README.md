# Deterministic scanner policy

Run `scripts/scan.sh . /tmp/cir-scan` after `make tools` and installing
`requirements-scan.txt` into `.venv/`. The target must contain `fixtures/terraform`
and `fixtures/k8s`; scanner policy comes from the script's checkout. The command
returns success when scans finish, including when they find issues. Inspect
`normalized.json` for findings. Tool failures return nonzero.

Before any tool starts, `scripts/check_scanner_policy.py` rejects inline
`checkov:skip`, `checkov.io/skip` annotations, `trivy:ignore`, and `tfsec:ignore`
directives in target Terraform/YAML files. It also rejects symlinked fixture files;
diagnostics contain quoted filenames only. A PR cannot change its scan coverage by
adding target-side suppressions.

`.checkov.yaml` and `.trivyignore` contain the only fixture skips. Each entry explains
its scope. Tests reject more than 15 skips per tool and any skip that overlaps a
seeded scenario's observed rule IDs. `rule_map.yaml` maps observed scanner IDs to
the answer-key category enum; unfamiliar rules remain `other`.

The baseline must produce an empty findings array. The scenario answer keys keep
their original `scanners_expected` hypotheses; observed rule IDs and provenance are
recorded separately. A missed prediction is reported by the eval.

## Provider cache

Terraform and OpenTofu have separate provider caches below `.cache/` (override the
root with `CIR_CACHE_DIR`). The OpenTofu copy excludes `.terraform/` and Terraform's
lock file. On its first init OpenTofu obtains signed provider checksums and writes
its own lock; the scanner caches that generated lock under `tofu-locks/`, keyed by
`versions.tf` contents and OpenTofu version. Later temporary copies restore this
OpenTofu lock before init. Provider packages still undergo normal checksum checks.
Changed constraints are resolved by init rather than forcing a cached selection.

This extends spec section 5.2's lock-free temporary copy: discarding the OpenTofu
lock on every scan forces repeated downloads even with a warm plugin cache.
[OpenTofu documents this checksum behavior](https://opentofu.org/docs/cli/config/config-file/#allowing-the-provider-plugin-cache-to-break-the-dependency-lock-file).
The scanner preserves lock validation and leaves the cache-breaking option off.

## Fake secret fixture

The repository's gitleaks exception requires both the exact S08 patch/answer path
and the exact non-credential-shaped fixture value. It applies only to
`generic-api-key`. In gitleaks 8.30.1, the
[directory source prefilters global allowlist paths](https://github.com/gitleaks/gitleaks/blob/v8.30.1/sources/files.go#L123-L126),
so a global path-and-value allowlist could skip the entire file before examining
its contents. Rule scoping avoids that behavior. Regression tests prove a
different synthetic value remains detectable in S08 and outside it.

Run the local policy checks with:

```sh
.venv/bin/python -m pytest -q tests/test_normalize.py tests/test_scenarios.py tests/test_gitleaks_policy.py
```
