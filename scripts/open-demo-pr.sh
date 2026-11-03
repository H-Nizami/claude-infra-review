#!/usr/bin/env bash
# Owner-only helper. Running it creates a branch, commit, remote push and draft PR.
# Review the selected patch and ledger budget before running; never called by CI.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo 'usage: scripts/open-demo-pr.sh <S01..S14|N01..N02>' >&2
  exit 2
fi
case "$1" in
  S0[1-9]|S1[0-4]|N0[1-2]) scenario="$1" ;;
  *) echo 'Unknown scenario ID' >&2; exit 2 ;;
esac
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
[ -z "$(git status --porcelain)" ] || { echo 'A clean working tree is required' >&2; exit 2; }
[ "$(git config user.name)" = 'Muhammad Haseeb' ] || { echo 'Set the documented repository author first' >&2; exit 2; }
[ "$(git config user.email)" = '81772627+H-Nizami@users.noreply.github.com' ] || { echo 'Set the documented repository email first' >&2; exit 2; }
patches=(scenarios/"$scenario"-*/patch.diff)
if [ "${#patches[@]}" -ne 1 ] || [ ! -f "${patches[0]}" ]; then
  echo 'Scenario patch missing or ambiguous' >&2
  exit 2
fi
git apply --check "${patches[0]}"
branch="demo/$scenario-$(date -u +%Y%m%dT%H%M%SZ)"
git switch -c "$branch"
git apply "${patches[0]}"
git add -- fixtures/
git commit -m "test: seed $scenario infrastructure review scenario"
git log -1 --format=%B
git push --set-upstream origin "$branch"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT
cat > "$body" <<EOF
Seeded scenario $scenario for infrastructure review evaluation.

Validation: the scenario is intentionally risky and remains validate-only. No cloud resources are applied.
Add the claude-review label only after the CI attempt estimate is precharged in the shared spend ledger.
EOF
gh pr create --draft --head "$branch" --title "Demo: $scenario infrastructure review" --body-file "$body"
