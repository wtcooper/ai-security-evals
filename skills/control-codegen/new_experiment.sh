#!/usr/bin/env bash
# Open an experiment folder under .evals/control-codegen/ to capture one rule-efficacy
# study: which spec + build prompt were held constant, what rule arms were compared, and
# the per-arm scan results. The generated apps themselves live in git branches; this
# folder holds the scoring + the audit trail that ties branches -> findings.
#
#   bash new_experiment.sh "<label>" "<starting-state-branch>"
#
# Folder name is  <label>_<date>  (deduped with -N for same-day reruns). Prints the
# absolute path as the last line (EXP=<path>).
set -euo pipefail

label="${1:?usage: new_experiment.sh \"<label>\" \"<starting-state-branch>\"}"
start_branch="${2:-starting-state}"
skill="control-codegen"

# --- resolve the .evals root: explicit override > git top-level > CWD ---------
if [ -n "${EVALS_DIR:-}" ]; then
  root="$EVALS_DIR"
elif top=$(git rev-parse --show-toplevel 2>/dev/null); then
  root="$top/.evals"
else
  root="$PWD/.evals"
fi

slug=$(printf '%s' "$label" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_' '-' | sed 's/^-//; s/-$//')
[ -n "$slug" ] || slug="run"
name="${slug}_$(date +%F)"
exp="$root/$skill/$name"
n=2
while [ -e "$exp" ]; do exp="$root/$skill/${name}-$n"; n=$((n + 1)); done
# one results/ subdir per arm is created at scan time; arms/ holds rule-file snapshots
mkdir -p "$exp/results" "$exp/arms"

commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
start_sha=$(git rev-parse --short "$start_branch" 2>/dev/null || echo "NOT-FOUND")
created=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > "$exp/manifest.json" <<JSON
{
  "skill": "$skill",
  "experiment": "$(basename "$exp")",
  "label": "$label",
  "created": "$created",
  "git_commit": "$commit",
  "engine": "git-branch-ab",
  "starting_state_branch": "$start_branch",
  "starting_state_sha": "$start_sha",
  "spec": "FILL IN: which specs/spec-XX file was used",
  "agent": "FILL IN: coding agent + model + temperature/seed policy (held constant)",
  "k_samples": "FILL IN: samples per arm",
  "arms": "FILL IN: list of {name, condition A|B|C, rules_path, branch}",
  "scanner_ensemble": "FILL IN: exact scanner + version + ruleset (held constant)",
  "dynamic": "FILL IN: BaxBench / ASan+fuzz, or none",
  "notes": ""
}
JSON

printf '%s\n' "$exp" > "$root/$skill/.last_experiment"
echo "experiment ready: $exp"
echo "  starting-state branch '$start_branch' @ $start_sha"
echo "  drop each arm's rule files in arms/<name>/ and its scan output in results/<name>/."
echo "EXP=$exp"
