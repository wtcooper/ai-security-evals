#!/usr/bin/env bash
# Build ONE sample of ONE arm: cut exp/<arm>/sample<i> from starting-state, add the arm's
# pre-build diff, run the coding agent (Claude Code, fresh throwaway config) on build-prompt.md,
# commit, push, record cost. Everything except the arm's pre-build files is identical across arms.
#
#   bash build_sample.sh <EXP> <repo-dir> <arm> <i> [--model M] [--max-budget-usd X] [--no-push] [--dry-run]
#
# Arms (design doc §3.1): A none | B CodeGuard plugin (agent-side, from setup_codeguard.sh)
#   | C .ai-security/ SBP files (from make_sbp.sh) | D = B+C | E arms/E/<spec>/CLAUDE.md (oracle-specific, upper bound)
# The agent runs with --permission-mode bypassPermissions: run this inside a container/VM, never on
# a host holding real credentials. Not --bare (that disables plugins and would silently kill arm B).
set -euo pipefail
exp="${1:?usage: build_sample.sh <EXP> <repo-dir> <arm> <i>}"; repo="${2:?}"; arm="${3:?}"; i="${4:?}"; shift 4
model="${BUILD_MODEL:-}"; budget="${BUILD_BUDGET_USD:-15}"; push=1; dry=0
while [ $# -gt 0 ]; do
  case "$1" in --model) model="$2"; shift 2;; --max-budget-usd) budget="$2"; shift 2;;
    --no-push) push=0; shift;; --dry-run) dry=1; shift;; *) echo "unknown $1" >&2; exit 2;; esac
done
here="$(cd "$(dirname "$0")" && pwd)"
M="python3 $here/lib/manifest.py"
branch="exp/$arm/sample$i"
spec=$($M "$exp" get benchmark.spec 2>/dev/null | tr -d '"' || true); [ "$spec" = "null" ] && spec=""
target="${spec:-spec}"

# --- tripwire: starting-state must equal its locked tag -----------------------------------
s=$(git -C "$repo" rev-parse starting-state); t=$(git -C "$repo" rev-parse 'starting-state-locked^{commit}')
[ "$s" = "$t" ] || { echo "TRIPWIRE: starting-state was edited ($s != $t) — arms no longer comparable" >&2; exit 1; }
[ -z "$(git -C "$repo" status --porcelain)" ] || { echo "repo has uncommitted changes" >&2; exit 1; }

# --- branch + pre-build diff ---------------------------------------------------------------
git -C "$repo" switch -q starting-state
git -C "$repo" switch -q -c "$branch"
G=(git -C "$repo" -c user.email="${GIT_AUTHOR_EMAIL:-eval@localhost}" -c user.name="${GIT_AUTHOR_NAME:-eval}")
case "$arm" in
  A|B) : ;;
  C|D) [ -d "$exp/arms/C/.ai-security" ] || { echo "run make_sbp.sh first (missing $exp/arms/C/.ai-security)" >&2; exit 1; }
       cp -R "$exp/arms/C/.ai-security" "$repo/.ai-security" ;;
  E)   f="$exp/arms/E/CLAUDE.md"; [ -f "$f" ] || f="$here/arms/E/$spec/CLAUDE.md"
       [ -f "$f" ] || { echo "arm E needs $exp/arms/E/CLAUDE.md (seed: arms/E/<spec>/CLAUDE.md)" >&2; exit 1; }
       cp "$f" "$repo/CLAUDE.md" ;;
  *) echo "unknown arm $arm (A|B|C|D|E)" >&2; exit 1;;
esac
"${G[@]}" add -A
"${G[@]}" commit -q --allow-empty -m "arm $arm: pre-build files"

# --- fresh agent config per sample ---------------------------------------------------------
cfg=$(mktemp -d); trap 'rm -rf "$cfg"' EXIT
plugin_args=()
if [ "$arm" = B ] || [ "$arm" = D ]; then
  tpl="$exp/.claude-config/codeguard"
  [ -d "$tpl" ] || { echo "run setup_codeguard.sh first (missing $tpl)" >&2; exit 1; }
  cp -R "$tpl/." "$cfg/"
  if [ "$(cat "$tpl/.install_method")" = "plugin-dir" ]; then plugin_args=(--plugin-dir "$(cat "$tpl/.plugin_dir")"); fi
fi
mkdir -p "$exp/transcripts" "$exp/results/$arm/sample$i"
transcript="$exp/transcripts/$arm-sample$i.jsonl"
prompt=$(cat "$repo/build-prompt.md")

t0=$(date +%s)
if [ $dry -eq 1 ]; then
  echo "+ (cd $repo && CLAUDE_CONFIG_DIR=$cfg claude -p <build-prompt.md> ${model:+--model $model} ${plugin_args[*]:-} --permission-mode bypassPermissions --no-session-persistence --strict-mcp-config --setting-sources user,project --output-format stream-json --verbose --max-budget-usd $budget > $transcript)"
  status=0
else
  set +e
  ( cd "$repo" && CLAUDE_CONFIG_DIR="$cfg" claude -p "$prompt" ${model:+--model "$model"} "${plugin_args[@]}" \
      --permission-mode bypassPermissions --no-session-persistence --strict-mcp-config --setting-sources user,project \
      --output-format stream-json --verbose --max-budget-usd "$budget" ) > "$transcript" 2> "$exp/results/$arm/sample$i/agent.stderr"
  status=$?
  set -e
fi
t1=$(date +%s)

# --- commit + push whatever was built ------------------------------------------------------
"${G[@]}" add -A
"${G[@]}" commit -q --allow-empty -m "arm $arm sample$i: generated app (agent exit $status)"
sha=$(git -C "$repo" rev-parse HEAD)
if [ $push -eq 1 ] && [ $dry -eq 0 ]; then bash "$here/ephemeral_repo.sh" push-branch --dir "$repo" --branch "$branch" >/dev/null; fi
git -C "$repo" switch -q starting-state

# --- cost/usage from the final `result` event; codeguard-inertness check for B/D --------------
read -r cost tin tout used_model < <(python3 - "$transcript" <<'PY'
import json,sys
cost=tin=tout=0; model=""
try:
    for l in open(sys.argv[1]):
        try: e=json.loads(l)
        except Exception: continue
        if isinstance(e,dict) and e.get("type")=="result":
            cost=e.get("total_cost_usd") or 0
            u=e.get("usage") or {}
            tin=(u.get("input_tokens") or 0)+(u.get("cache_read_input_tokens") or 0)+(u.get("cache_creation_input_tokens") or 0)
            tout=u.get("output_tokens") or 0
        m=(e.get("message") or {}).get("model") if isinstance(e,dict) else None
        if m and not model: model=m
except FileNotFoundError: pass
print(cost,tin,tout,model or "-")
PY
)
inert=""
if [ "$arm" = B ] || [ "$arm" = D ]; then
  n=$(grep -ci codeguard "$transcript" 2>/dev/null || true)
  [ "${n:-0}" -gt 0 ] || inert="WARNING: arm $arm transcript never mentions codeguard — plugin may be inert (check install/paths before scaling k)"
fi
built=true; [ $status -eq 0 ] || built=false
$M "$exp" append-sample "{\"run\":\"$(basename "$exp")\",\"arm\":\"$arm\",\"target\":\"$target\",\"sample\":$i,\"branch\":\"$branch\",\"sha\":\"$sha\",\"agent_exit\":$status,\"agent_model\":\"$used_model\",\"cost_usd\":$cost,\"tokens_in\":$tin,\"tokens_out\":$tout,\"wall_s\":$((t1-t0)),\"build_ok\":null,\"contaminated\":false}" >/dev/null
$M "$exp" add cost.usd "$cost" >/dev/null; $M "$exp" add cost.tokens_in "$tin" >/dev/null; $M "$exp" add cost.tokens_out "$tout" >/dev/null; $M "$exp" add cost.wall_s "$((t1-t0))" >/dev/null
[ "$used_model" != "-" ] && $M "$exp" set model.id "\"$used_model\"" >/dev/null
echo "BRANCH=$branch"; echo "SHA=$sha"; echo "AGENT_EXIT=$status"; echo "COST_USD=$cost"; echo "WALL_S=$((t1-t0))"
[ -n "$inert" ] && echo "$inert" >&2
exit 0
