# Pinned versions

Looked up on 2026-10-22. GitHub Actions are pinned to the full commit SHA the release tag resolves to (`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`). Binaries are pinned to an exact version and verified against the sha256 in the project's published checksums file (see `scripts/tools.sh`).

## GitHub Actions

| Action | Tag | Commit SHA | Looked up |
|---|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` | 2026-10-22 |
| `actions/setup-python` | v7.1.0 | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | 2026-10-22 |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | 2026-10-22 |
| `actions/download-artifact` | v5.0.0 | `634f93cb2916e3fdff6788551b99b062d0335ce0` | 2026-10-22 |
| `anthropics/claude-code-action` | v1.0.258 | `6b6870e649b5ff408753befeaee5fc7989d4e6a9` | 2026-10-22 |

## Binaries (`scripts/tools.sh`)

| Tool | Version | Checksums file |
|---|---|---|
| d2 | v0.9.0 | https://github.com/terrastruct/d2/releases/download/v0.9.0/SHA256SUMS |
| actionlint | 1.7.12 | https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_checksums.txt |
| gitleaks | 8.30.1 | https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_checksums.txt |
| trivy | 0.76.1 | https://github.com/aquasecurity/trivy/releases/download/v0.76.1/trivy_0.76.1_checksums.txt |
| terraform | 1.17.0 | https://releases.hashicorp.com/terraform/1.17.0/terraform_1.17.0_SHA256SUMS |
| opentofu | 1.13.2 | https://github.com/opentofu/opentofu/releases/download/v1.13.2/tofu_1.13.2_SHA256SUMS |
| tflint | 0.64.0 | https://github.com/terraform-linters/tflint/releases/download/v0.64.0/checksums.txt |
| kubeconform | 0.8.0 | https://github.com/yannh/kubeconform/releases/download/v0.8.0/CHECKSUMS |

Sums are hardcoded for `darwin-arm64`, `darwin-amd64`, `linux-amd64` and `linux-arm64`. Other platforms fail with a clear error.

## Python and fixture dependencies

Direct Python pins are in `requirements.txt` (PyYAML 6.0.3, jsonschema 4.26.0,
pytest 9.1.1) and `requirements-scan.txt` (checkov 3.3.30). These are exact direct
pins, not a complete transitive dependency lock. Package metadata was checked
against PyPI on 2026-10-22.

The AWS provider is fixed in `fixtures/terraform/versions.tf`, with its Terraform
dependency lock committed. TFLint's AWS plugin version is fixed in
`fixtures/terraform/.tflint.hcl`; the podinfo image uses a digest in
`fixtures/k8s/deployment.yaml`. No provider is applied to an account.
