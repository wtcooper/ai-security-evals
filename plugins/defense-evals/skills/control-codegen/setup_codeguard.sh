#!/usr/bin/env bash
# Arm B/D: "Project CodeGuard, as installed". Builds ONE template Claude Code config dir with
# the real codeguard-security plugin installed from a pinned CodeGuard release, so every B/D
# sample starts from an identical, fresh install (copied per sample; nothing else in it).
#
#   bash setup_codeguard.sh <EXP> [--ref v1.4.0]
#
# Writes <EXP>/.deps/project-codeguard (pinned clone) and <EXP>/.claude-config/codeguard/
# (CLAUDE_CONFIG_DIR template). Records version+sha in manifest arms[B]/[D].pre_build_diff.
# Fallback if `claude plugin marketplace add <path>` is unavailable: build_sample.sh passes
# --plugin-dir <EXP>/.deps/project-codeguard instead (same files, recorded as "plugin-dir").
set -euo pipefail
exp="${1:?usage: setup_codeguard.sh <EXP> [--ref vX.Y.Z]}"; shift
ref="${CODEGUARD_REF:-v1.4.0}"
while [ $# -gt 0 ]; do case "$1" in --ref) ref="$2"; shift 2;; *) echo "unknown $1" >&2; exit 2;; esac; done
here="$(cd "$(dirname "$0")" && pwd)"
deps="$exp/.deps/project-codeguard"; cfg="$exp/.claude-config/codeguard"

if [ ! -d "$deps/.git" ]; then
  mkdir -p "$exp/.deps"
  git clone -q --depth 1 --branch "$ref" https://github.com/cosai-oasis/project-codeguard "$deps"
fi
sha=$(git -C "$deps" rev-parse HEAD)
n_rules=$(ls "$deps"/skills/codeguard/rules/codeguard-*.md 2>/dev/null | wc -l | tr -d ' ')
[ "$n_rules" -gt 0 ] || { echo "no rules under $deps/skills/codeguard/rules — wrong ref?" >&2; exit 1; }

rm -rf "$cfg"; mkdir -p "$cfg"
method="plugin-dir"
if CLAUDE_CONFIG_DIR="$cfg" claude plugin marketplace add "$deps" >/dev/null 2>&1 \
   && CLAUDE_CONFIG_DIR="$cfg" claude plugin install codeguard-security@project-codeguard --scope user >/dev/null 2>&1; then
  if ls "$cfg"/plugins/cache/*/codeguard*/*/skills/codeguard/rules/codeguard-*.md >/dev/null 2>&1 \
     || ls "$cfg"/plugins/cache/*/*/skills/codeguard/rules/codeguard-*.md >/dev/null 2>&1; then
    method="marketplace"
  fi
fi
if [ "$method" = "plugin-dir" ]; then
  echo "marketplace install did not materialise rules under $cfg — build_sample.sh will use --plugin-dir $deps" >&2
fi
printf '%s\n' "$method" > "$cfg/.install_method"
printf '%s\n' "$deps" > "$cfg/.plugin_dir"

diff_json="{\"kind\":\"agent-side plugin\",\"plugin\":\"codeguard-security\",\"ref\":\"$ref\",\"sha\":\"$sha\",\"rules\":$n_rules,\"install\":\"$method\"}"
for arm in B D; do
  python3 - "$exp/manifest.json" "$arm" "$diff_json" <<'PY'
import json,sys
p,arm,dj=sys.argv[1],sys.argv[2],json.loads(sys.argv[3])
d=json.load(open(p))
for a in d.get("arms",[]):
    if a.get("name")==arm:
        a["condition"]=a.get("condition") or ("codeguard" if arm=="B" else "sbp+codeguard")
        a.setdefault("pre_build_diff",[]); a["pre_build_diff"]=[x for x in a["pre_build_diff"] if x.get("plugin")!="codeguard-security"]+[dj]
json.dump(d,open(p,"w"),indent=2); open(p,"a").write("\n")
PY
done
echo "CODEGUARD_REF=$ref"; echo "CODEGUARD_SHA=$sha"; echo "CODEGUARD_RULES=$n_rules"; echo "CODEGUARD_INSTALL=$method"
echo "CLAUDE_CONFIG_TEMPLATE=$cfg"
