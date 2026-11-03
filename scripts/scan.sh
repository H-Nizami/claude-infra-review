#!/usr/bin/env bash
# Run every deterministic scanner over <target-root>/fixtures and write raw + normalized
# results to <out-dir>. Usage: scripts/scan.sh <target-root> <out-dir>
#
# Scanner findings never fail this script; tool crashes do (exit 1).
# Scanner config (skip lists, rule map) always comes from this script's own checkout,
# never from <target-root>, so a scanned change cannot edit its own skip list.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: scripts/scan.sh <target-root> <out-dir>" >&2
  exit 1
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
target="$(cd "$1" && pwd)"
mkdir -p "$2"
out="$(cd "$2" && pwd)"
tf_dir="fixtures/terraform"
k8s_dir="fixtures/k8s"

for d in "$target/$tf_dir" "$target/$k8s_dir"; do
  [ -d "$d" ] || { echo "scan.sh: missing $d" >&2; exit 1; }
done

# A PR must not suppress checks through comments or Kubernetes annotations.
# Policy diagnostics contain quoted filenames only, never untrusted file contents.
python3 "$root/scripts/check_scanner_policy.py" "$target"

# Pinned binaries from .bin/ (and checkov from .venv/) first; PATH only as a fallback.
pick() {
  local name="$1" p
  for p in "$root/.bin/$name" "$root/.venv/bin/$name"; do
    if [ -x "$p" ]; then echo "$p"; return; fi
  done
  command -v "$name" || { echo "scan.sh: $name not found (run make tools)" >&2; exit 1; }
}
TERRAFORM="$(pick terraform)"
TOFU="$(pick tofu)"
TFLINT="$(pick tflint)"
KUBECONFORM="$(pick kubeconform)"
TRIVY="$(pick trivy)"
CHECKOV="$(pick checkov)"

crash() { echo "scan.sh: $1 crashed (exit $2)" >&2; exit 1; }

# Provider downloads are cached across runs (eval scans every scenario twice).
cache="${CIR_CACHE_DIR:-$root/.cache}"
mkdir -p "$cache/terraform-plugins" "$cache/tofu-plugins" "$cache/kubeconform"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cd "$target"

# 1. terraform fmt (exit 3 = files need formatting, a finding; anything else non-zero = crash)
rc=0
"$TERRAFORM" -chdir="$tf_dir" fmt -check -recursive -diff -no-color >"$out/fmt.txt" 2>"$work/fmt.err" || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then cat "$work/fmt.err" >&2; crash "terraform fmt" "$rc"; fi

# 2. terraform init + validate (validate exit 1 = invalid config, a finding)
TF_PLUGIN_CACHE_DIR="$cache/terraform-plugins" \
  "$TERRAFORM" -chdir="$tf_dir" init -backend=false -input=false -no-color >"$work/tf-init.log" 2>&1 ||
  { cat "$work/tf-init.log" >&2; crash "terraform init" 1; }
rc=0
"$TERRAFORM" -chdir="$tf_dir" validate -json -no-color >"$out/tf-validate.json" || rc=$?
[ "$rc" -le 1 ] || crash "terraform validate" "$rc"

# 3. tofu init + validate in a temp copy without .terraform/ and the lock file
mkdir -p "$work/tofu"
(cd "$tf_dir" && tar --exclude .terraform --exclude .terraform.lock.hcl -cf - .) | (cd "$work/tofu" && tar -xf -)
# Without a lock OpenTofu downloads the large AWS package on every init to establish
# signed checksums, even when the provider cache is warm. Preserve its own verified
# lock separately (never Terraform's registry-specific lock) for later scans. Init
# still verifies cached provider hashes and updates selections if constraints change.
tofu_lock_key="$(python3 -c 'import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes() + sys.argv[2].encode()).hexdigest())' "$tf_dir/versions.tf" "$("$TOFU" version | head -n1)")"
mkdir -p "$cache/tofu-locks"
tofu_lock="$cache/tofu-locks/$tofu_lock_key.hcl"
if [ -f "$tofu_lock" ]; then cp "$tofu_lock" "$work/tofu/.terraform.lock.hcl"; fi
TF_PLUGIN_CACHE_DIR="$cache/tofu-plugins" \
  "$TOFU" -chdir="$work/tofu" init -backend=false -input=false -no-color >"$work/tofu-init.log" 2>&1 ||
  { cat "$work/tofu-init.log" >&2; crash "tofu init" 1; }
tofu_lock_tmp="$(mktemp "$cache/tofu-locks/.lock.XXXXXXXX")"
cp "$work/tofu/.terraform.lock.hcl" "$tofu_lock_tmp"
mv "$tofu_lock_tmp" "$tofu_lock"
rc=0
"$TOFU" -chdir="$work/tofu" validate -json -no-color >"$out/tofu-validate.json" || rc=$?
[ "$rc" -le 1 ] || crash "tofu validate" "$rc"

# 4. tflint (exit 2 = issues found, a finding)
"$TFLINT" --chdir="$tf_dir" --init --no-color >"$work/tflint-init.log" 2>&1 ||
  { cat "$work/tflint-init.log" >&2; crash "tflint --init" 1; }
rc=0
"$TFLINT" --chdir="$tf_dir" --format json --no-color >"$out/tflint.json" || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then crash "tflint" "$rc"; fi

# 5. kustomize render + kubeconform (exit 1 = invalid resources, a finding)
if command -v kubectl >/dev/null; then
  kubectl kustomize "$k8s_dir" >"$out/k8s.rendered.yaml" || crash "kubectl kustomize" $?
else
  kustomize build "$k8s_dir" >"$out/k8s.rendered.yaml" || crash "kustomize build" $?
fi
rc=0
"$KUBECONFORM" -strict -summary -cache "$cache/kubeconform" -output json "$out/k8s.rendered.yaml" >"$out/kubeconform.json" || rc=$?
[ "$rc" -le 1 ] || crash "kubeconform" "$rc"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$out/kubeconform.json" ||
  crash "kubeconform (no JSON output)" 1

# 6. trivy config (exit 0 regardless of findings unless --exit-code is set)
for fmt in json sarif; do
  "$TRIVY" config --quiet --format "$fmt" --ignorefile "$root/scanners/.trivyignore" \
    --skip-dirs "$tf_dir/.terraform" --output "$out/trivy.$fmt" fixtures || crash "trivy config" $?
done

# 7. checkov (--soft-fail: failed checks exit 0; a crash leaves no parseable output)
rm -rf "$work/checkov"
"$CHECKOV" --config-file "$root/scanners/.checkov.yaml" -d fixtures --soft-fail \
  -o json -o sarif --output-file-path "$work/checkov" >"$work/checkov.log" 2>&1 ||
  { cat "$work/checkov.log" >&2; crash "checkov" 1; }
cp "$work/checkov/results_json.json" "$out/checkov.json" || crash "checkov (no JSON output)" 1
cp "$work/checkov/results_sarif.sarif" "$out/checkov.sarif" || crash "checkov (no SARIF output)" 1

# Tool versions (first line of each --version)
{
  echo "{"
  echo "  \"terraform\": \"$("$TERRAFORM" version | head -n1)\","
  echo "  \"tofu\": \"$("$TOFU" version | head -n1)\","
  echo "  \"tflint\": \"$("$TFLINT" --version | head -n1)\","
  echo "  \"kubeconform\": \"$("$KUBECONFORM" -v | head -n1)\","
  echo "  \"trivy\": \"$("$TRIVY" --version | head -n1)\","
  echo "  \"checkov\": \"$("$CHECKOV" --version | head -n1)\""
  echo "}"
} >"$out/tool-versions.json"

# 8. normalize
python3 "$root/scripts/normalize.py" "$out" --target-root "$target" --rule-map "$root/scanners/rule_map.yaml" --require-complete
echo "scan.sh: $(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$out/normalized.json") normalized findings -> $out/normalized.json"
