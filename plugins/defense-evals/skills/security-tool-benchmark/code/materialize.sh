#!/usr/bin/env bash
# Materialise one livecvebench-style task: clone its repo at the vulnerable and fixed commits.
#   bash materialize.sh <EXP>/targets/livecvebench <target-id>
set -euo pipefail
dst="${1:?targets dir}"; tid="${2:?target id}"
row=$(grep -m1 "\"target\": \"$tid\"" "$dst/ground_truth.jsonl" || true)
[ -n "$row" ] || { echo "no ground truth row for $tid" >&2; exit 1; }
repo=$(printf '%s' "$row" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("repo") or "")')
vc=$(printf '%s' "$row" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("vuln_commit") or "")')
fc=$(printf '%s' "$row" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("fix_commit") or "")')
[ -n "$repo" ] && [ -n "$vc" ] || { echo "row lacks repo/vuln_commit: $row" >&2; exit 1; }
case "$repo" in http*) url="$repo";; *) url="https://github.com/$repo";; esac
mkdir -p "$dst/$tid"
[ -d "$dst/$tid/vulnerable/.git" ] || git clone -q "$url" "$dst/$tid/vulnerable"
git -C "$dst/$tid/vulnerable" checkout -q "$vc"
if [ -n "$fc" ]; then
  [ -d "$dst/$tid/fixed/.git" ] || git clone -q "$url" "$dst/$tid/fixed"
  git -C "$dst/$tid/fixed" checkout -q "$fc"
fi
echo "MATERIALIZED=$dst/$tid"
