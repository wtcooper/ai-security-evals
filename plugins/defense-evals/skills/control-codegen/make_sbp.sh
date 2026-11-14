#!/usr/bin/env bash
# Arm C/D: produce the Secure Build Plan ONCE from the spec, with our secure-plan plugin, in a
# throwaway session that never sees oracles/probes; capture .ai-security/ as the arm's only
# pre-build diff (design doc §3.1 leakage rule).
#
#   bash make_sbp.sh <EXP> <repo-dir> [--model M] [--branch starting-state] [--sdlc-ref main]
#
# Output: <EXP>/arms/C/.ai-security/{profile.md,plans/<slug>-sbp.md} (D reuses the same files).
# Verifies the SBP cites codeguard rule ids and contains no rule bodies.
set -euo pipefail
exp="${1:?usage: make_sbp.sh <EXP> <repo-dir> [--model M]}"; repo="${2:?repo dir}"; shift 2
model="${SBP_MODEL:-}"; branch="starting-state"
while [ $# -gt 0 ]; do
  case "$1" in --model) model="$2"; shift 2;; --branch) branch="$2"; shift 2;;
    --sdlc-ref) export AISEC_SDLC_REF="$2"; shift 2;; *) echo "unknown $1" >&2; exit 2;; esac
done
here="$(cd "$(dirname "$0")" && pwd)"
eval "$(bash "$here/lib/find_sdlc.sh")"
work=$(mktemp -d); cfg=$(mktemp -d)
trap 'rm -rf "$work" "$cfg"' EXIT

git -C "$repo" worktree add -q "$work/tree" "$branch"
# fresh config dir with ONLY the secure-plan plugin (marketplace = the sdlc repo checkout)
CLAUDE_CONFIG_DIR="$cfg" claude plugin marketplace add "$SDLC_DIR" >/dev/null 2>&1 || true
CLAUDE_CONFIG_DIR="$cfg" claude plugin install ai-security-secure-plan@ai-security-sdlc --scope user >/dev/null 2>&1 || \
  plugin_dir_arg="--plugin-dir $SDLC_DIR/plugins/secure-plan"
prompt='Read SPEC.md. First run the security-profile skill to write .ai-security/profile.md for this application (answer its questions yourself from the spec; do not ask me). Then run the secure-build-plan skill for the feature "implement the whole SPEC.md" and save .ai-security/plans/<feature-slug>-sbp.md. Do not write any application code. Stop when both files exist.'
( cd "$work/tree" && CLAUDE_CONFIG_DIR="$cfg" claude -p "$prompt" ${model:+--model "$model"} ${plugin_dir_arg:-} \
    --permission-mode bypassPermissions --no-session-persistence --strict-mcp-config --setting-sources user,project \
    --output-format stream-json --verbose --max-budget-usd "${SBP_BUDGET_USD:-5}" ) > "$exp/transcripts/sbp-author.jsonl" || true

[ -f "$work/tree/.ai-security/profile.md" ] || { echo "no .ai-security/profile.md produced — see $exp/transcripts/sbp-author.jsonl" >&2; exit 1; }
ls "$work/tree"/.ai-security/plans/*-sbp.md >/dev/null 2>&1 || { echo "no SBP produced" >&2; exit 1; }
rm -rf "$exp/arms/C/.ai-security"; mkdir -p "$exp/arms/C"
cp -R "$work/tree/.ai-security" "$exp/arms/C/.ai-security"
rm -rf "$exp/arms/C/.ai-security/cache" 2>/dev/null || true       # never ship downloaded rule bodies
git -C "$repo" worktree remove --force "$work/tree"

sbp=$(ls "$exp/arms/C"/.ai-security/plans/*-sbp.md | head -1)
cites=$(grep -cE 'codeguard-[0-9]-[a-z-]+' "$sbp" || true)
[ "$cites" -gt 0 ] || echo "WARNING: SBP cites no codeguard rule ids" >&2
if grep -qiE '^\s*(alwaysApply|globs):' "$sbp"; then echo "WARNING: SBP looks like it pasted a rule body (frontmatter found)" >&2; fi
sbp_model=$(python3 -c 'import json,sys
for l in open(sys.argv[1]):
    try: e=json.loads(l)
    except Exception: continue
    m=(e.get("message") or {}).get("model") if isinstance(e,dict) else None
    if m: print(m); break' "$exp/transcripts/sbp-author.jsonl" 2>/dev/null || true)
python3 - "$exp/manifest.json" "$sbp" "$cites" "${sbp_model:-$model}" "$SDLC_SHA" <<'PY'
import json,sys
p,sbp,cites,model,sha=sys.argv[1:]
d=json.load(open(p))
dj={"kind":"files","paths":[".ai-security/profile.md",".ai-security/plans/"+sbp.split("/")[-1]],"author_model":model,"rule_ids_cited":int(cites),"sdlc_sha":sha}
for a in d.get("arms",[]):
    if a.get("name") in ("C","D"):
        a["condition"]=a.get("condition") or ("sbp" if a["name"]=="C" else "sbp+codeguard")
        a["pre_build_diff"]=[x for x in a.get("pre_build_diff",[]) if x.get("kind")!="files"]+[dj]
json.dump(d,open(p,"w"),indent=2); open(p,"a").write("\n")
PY
echo "SBP=$sbp"; echo "SBP_RULE_IDS_CITED=$cites"; echo "SBP_MODEL=${sbp_model:-$model}"
