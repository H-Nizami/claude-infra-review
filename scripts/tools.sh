#!/usr/bin/env bash
# Install pinned CLI tools into ./.bin, verified against sha256 sums copied from each
# project's published checksums file. Usage: scripts/tools.sh [d2] [actionlint] [gitleaks] [trivy]
# [terraform] [tofu] [tflint] [kubeconform] (no arguments = the first four; scanner tools by name).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
bin="$root/.bin"
mkdir -p "$bin"

case "$(uname -s)" in
  Darwin) os=darwin ;;
  Linux) os=linux ;;
  *) echo "tools.sh: unsupported OS $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64 | aarch64) arch=arm64 ;;
  x86_64 | amd64) arch=amd64 ;;
  *) echo "tools.sh: unsupported arch $(uname -m)" >&2; exit 1 ;;
esac
plat="$os-$arch"

D2_VERSION=0.9.0
ACTIONLINT_VERSION=1.7.12
GITLEAKS_VERSION=8.30.1
TRIVY_VERSION=0.76.1
TERRAFORM_VERSION=1.17.0
TOFU_VERSION=1.13.2
TFLINT_VERSION=0.64.0
KUBECONFORM_VERSION=0.8.0

# Sets: url, sum, member (path of the binary inside the archive).
resolve() {
  local tool="$1" asset=""
  url="" sum="" member=""
  case "$tool" in
    d2)
      case "$plat" in
        darwin-arm64) asset=macos-arm64; sum=eaf6c0c143e56dd9fa97bfb6df25ea9c1ebce40245f056a0768cf1a6c15d3064 ;;
        darwin-amd64) asset=macos-amd64; sum=cad39576a480d6bb02ea142fef1726647914b0d2da51ccc9b30b660a2b1babf0 ;;
        linux-amd64) asset=linux-amd64; sum=5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9 ;;
        linux-arm64) asset=linux-arm64; sum=ac2c028697199479acb321db1e3d68caee9f2ba492ed73caa3cd13f3829bf913 ;;
      esac
      url="https://github.com/terrastruct/d2/releases/download/v${D2_VERSION}/d2-v${D2_VERSION}-${asset}.tar.gz"
      member="d2-v${D2_VERSION}/bin/d2"
      ;;
    actionlint)
      case "$plat" in
        darwin-arm64) sum=aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f ;;
        darwin-amd64) sum=5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644 ;;
        linux-amd64) sum=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 ;;
        linux-arm64) sum=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6 ;;
      esac
      url="https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_${os}_${arch}.tar.gz"
      member="actionlint"
      ;;
    gitleaks)
      local garch="$arch"
      [ "$arch" = amd64 ] && garch=x64
      case "$plat" in
        darwin-arm64) sum=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
        darwin-amd64) sum=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709 ;;
        linux-amd64) sum=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
        linux-arm64) sum=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;;
      esac
      url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_${os}_${garch}.tar.gz"
      member="gitleaks"
      ;;
    trivy)
      case "$plat" in
        darwin-arm64) asset=macOS-ARM64; sum=11a9b6cd2752011b54f01ea4bd0dbfa9f0c41dc6538d5a3f9d23955f471bf4e5 ;;
        darwin-amd64) asset=macOS-64bit; sum=7aa762eacd582052d053b62dcf972a1ab058abe39a57ccae234ed8894945b6b7 ;;
        linux-amd64) asset=Linux-64bit; sum=c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0 ;;
        linux-arm64) asset=Linux-ARM64; sum=e174dff2a6dba5e3ae41f8d0537a6324405bd08132497340304c6b20e0f16a1f ;;
      esac
      url="https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_${asset}.tar.gz"
      member="trivy"
      ;;
    terraform)
      # https://releases.hashicorp.com/terraform/1.17.0/terraform_1.17.0_SHA256SUMS
      case "$plat" in
        darwin-arm64) sum=7472a54cca911d46c0e399a5ebbce44444912d0d4dad7495f37f1fa51e7ca6b7 ;;
        darwin-amd64) sum=3773397524196e4ebbf7167e2b9fb478dff1962d555d649f616ba97ca446a143 ;;
        linux-amd64) sum=c168cab7c637a8769fdb90089ddd19de701bc6ff8aca64dc2e2185fe46f59f67 ;;
        linux-arm64) sum=f32478134ffc6d710eec474bbd316652cdddc0f4e336973a3745e8d3a3309cdf ;;
      esac
      url="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_${os}_${arch}.zip"
      member="terraform"
      ;;
    tofu)
      # https://github.com/opentofu/opentofu/releases/download/v1.13.2/tofu_1.13.2_SHA256SUMS
      case "$plat" in
        darwin-arm64) sum=0d1cdc85f38992055b48e7fb161304a2ddfe2e5ee0ff68ffec9d0349c8bd1b59 ;;
        darwin-amd64) sum=dc6e4eb1d3ed6550c2ef052596f933dbcd8c806957665ea83ae7537147cb3074 ;;
        linux-amd64) sum=ac05d9952662c7db28dd57e93f0a68018837bfdf9342384ec0987977c16a9645 ;;
        linux-arm64) sum=88e2d9e3f94f97b76ab2faf55ade87578f56aed19c5e45fa139d70e994366d1f ;;
      esac
      url="https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_${os}_${arch}.tar.gz"
      member="tofu"
      ;;
    tflint)
      # https://github.com/terraform-linters/tflint/releases/download/v0.64.0/checksums.txt
      case "$plat" in
        darwin-arm64) sum=2496e9cb3d24992d553b45e7c87a0fdc9449ca975233876247a9bfeda857e6c0 ;;
        darwin-amd64) sum=0f3a9fd17526014646a2dfc3f9122f7b4161abe3d6b0f0f03f9014483ddf4d19 ;;
        linux-amd64) sum=cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537 ;;
        linux-arm64) sum=560da89aacf59389d4eb029730dd5b109b7288096c32f2726a0d9e783a5ea8eb ;;
      esac
      url="https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_${os}_${arch}.zip"
      member="tflint"
      ;;
    kubeconform)
      # https://github.com/yannh/kubeconform/releases/download/v0.8.0/CHECKSUMS
      case "$plat" in
        darwin-arm64) sum=f84f4dfbebf4a6b0b230385fa065a39ea35e02608c2b50d025dcf64775a69d67 ;;
        darwin-amd64) sum=71dbc87ac9f24099a62b93570e65aa06312ba6ac8aea63b7f86e9d999edf5a92 ;;
        linux-amd64) sum=9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883 ;;
        linux-arm64) sum=1f53fc8e81258197a35e8603054162a5af1de8c5af13746c71ab680d9534ed87 ;;
      esac
      url="https://github.com/yannh/kubeconform/releases/download/v${KUBECONFORM_VERSION}/kubeconform-${os}-${arch}.tar.gz"
      member="kubeconform"
      ;;
    *)
      echo "tools.sh: unknown tool '$tool' (known: d2 actionlint gitleaks trivy terraform tofu tflint kubeconform)" >&2
      exit 1
      ;;
  esac
  if [ -z "$sum" ]; then
    echo "tools.sh: no pinned checksum for $tool on $plat" >&2
    exit 1
  fi
}

verify() {
  # $1 = file, $2 = expected sha256
  if command -v sha256sum >/dev/null; then
    echo "$2  $1" | sha256sum -c -
  else
    echo "$2  $1" | shasum -a 256 -c -
  fi
}

hash_of() {
  if command -v sha256sum >/dev/null; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# Temp dir of the current download; removed on any exit, including failures under set -e.
tmp=""
trap '[ -z "$tmp" ] || rm -rf "$tmp"' EXIT

# The stamp holds "<archive sha256> <binary sha256>". On skip, the installed binary is
# re-hashed, so a replaced or corrupted .bin/<tool> is reinstalled.
install_tool() {
  local tool="$1" stamp archive
  resolve "$tool"
  stamp="$bin/.$tool.sha256"
  if [ -x "$bin/$tool" ] && [ -f "$stamp" ] &&
    [ "$(cat "$stamp")" = "$sum $(hash_of "$bin/$tool")" ]; then
    echo "tools.sh: $tool already installed (binary checksum matches), skipping"
    return
  fi
  tmp="$(mktemp -d)"
  archive="$tmp/$(basename "$url")"
  echo "tools.sh: downloading $url"
  curl -fsSL --retry 3 -o "$archive" "$url"
  if ! (cd "$tmp" && verify "$(basename "$archive")" "$sum"); then
    echo "tools.sh: checksum mismatch for $tool, aborting" >&2
    exit 1
  fi
  case "$archive" in
    *.zip) unzip -q -o "$archive" "$member" -d "$tmp" ;;
    *) tar -xzf "$archive" -C "$tmp" "$member" ;;
  esac
  install -m 0755 "$tmp/$member" "$bin/$tool"
  echo "$sum $(hash_of "$bin/$tool")" > "$stamp"
  rm -rf "$tmp"
  tmp=""
  echo "tools.sh: installed $tool -> .bin/$tool"
}

if [ "$#" -eq 0 ]; then
  set -- d2 actionlint gitleaks trivy
fi
for t in "$@"; do
  install_tool "$t"
done
