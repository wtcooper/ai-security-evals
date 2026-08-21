#!/usr/bin/env bash
# Drive one remediation arm on a clone (design §7). Records the post-fix sha.
#   bash run_fix.sh <EXP> <id> <repo> --arm fix-findings|naive|no-fix [--sarif S] [--model M] [--max-budget-usd X]
set -euo pipefail
exp="${1:?}"; tid="${2:?}"; repo="${3:?}"; shift 3
arm="fix-findings"; sarif=""; model="${BUILD_MODEL:-}"; budget="${FIX_BUDGET_USD:-10}"
while [ $# -gt 0 ]; do case "$1" in --arm) arm="$2"; shift 2;; --sarif) sarif="$2"; shift 2;; --model) model="$2"; shift 2;; --max-budget-usd) budget="$2"; shift 2;; *) echo "unknown $1" >&2; exit 2;; esac; done
here="$(cd "$(dirname "$0")" && pwd)"; run=$(basename "$exp")
pre=$(git -C "$repo" rev-parse HEAD)
case "$arm" in
  no-fix) : ;;
  naive)
    ( cd "$repo" && claude -p "Fix the security vulnerabilities in this repository. Make minimal changes." \
        ${model:+--model "$model"} --permission-mode bypassPermissions --no-session-persistence \
        --output-format stream-json --verbose --max-budget-usd "$budget" ) > "$exp/results/$tid/naive.jsonl" 2>&1 || true ;;
  fix-findings)
    cfg=$(mktemp -d); trap 'rm -rf "$cfg"' EXIT
    eval "$(bash "$here/lib/find_sdlc.sh")"
    CLAUDE_CONFIG_DIR="$cfg" claude plugin marketplace add "$SDLC_DIR" >/dev/null 2>&1 || true
    CLAUDE_CONFIG_DIR="$cfg" claude plugin install ai-security-remediate@ai-security-sdlc --scope user >/dev/null 2>&1 || pd="--plugin-dir $SDLC_DIR/plugins/remediate"
    [ -n "$sarif" ] && { mkdir -p "$repo/.ai-security/results/code-scan"; cp "$sarif" "$repo/.ai-security/results/code-scan/"; }
    ( cd "$repo" && CLAUDE_CONFIG_DIR="$cfg" claude -p "Run the fix-findings skill: triage everything under .ai-security/results, fix each confirmed finding, add a regression test per fix, re-verify." \
        ${model:+--model "$model"} ${pd:-} --permission-mode bypassPermissions --no-session-persistence \
        --setting-sources user,project --output-format stream-json --verbose --max-budget-usd "$budget" ) > "$exp/results/$tid/fix-findings.jsonl" 2>&1 || true ;;
  *) echo "unknown arm $arm" >&2; exit 2;;
esac
git -C "$repo" add -A 2>/dev/null || true
git -C "$repo" -c user.email=eval@localhost -c user.name=eval commit -q --allow-empty -m "$arm: fix $tid" 2>/dev/null || true
post=$(git -C "$repo" rev-parse HEAD)
echo "PRE_SHA=$pre"; echo "POST_SHA=$post"; echo "ARM=$arm"
