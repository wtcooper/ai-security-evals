#!/usr/bin/env bash
# Open an experiment folder under .evals/<skill>/ and snapshot the inputs, so every
# run is auditable: what corpus/choices/config were used, the engine's native output,
# and the raw transcript all live in one legibly-named directory.
#
#   bash new_experiment.sh <skill> "<label>" [engine]
#
# Folder name is  <label>_<date>  (deduped with -N for same-day reruns). Prints the
# absolute path as the last line (EXP=<path>); the RUN/ANALYZE steps write the
# engine's results, the summary, and the transcript into <EXP>.
set -euo pipefail

skill="${1:?usage: new_experiment.sh <skill> \"<label>\" [engine]}"
label="${2:?provide a short legible label, e.g. acme-prod-cyber-smoke}"
engine="${3:-promptfoo}"

# --- resolve the .evals root: explicit override > git top-level > CWD ---------
if [ -n "${EVALS_DIR:-}" ]; then
  root="$EVALS_DIR"
elif top=$(git rev-parse --show-toplevel 2>/dev/null); then
  root="$top/.evals"
else
  root="$PWD/.evals"
fi

# --- legible folder name: <label>_<date>, deduped with -N ---------------------
slug=$(printf '%s' "$label" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_' '-' | sed 's/^-//; s/-$//')
[ -n "$slug" ] || slug="run"
name="${slug}_$(date +%F)"
exp="$root/$skill/$name"
n=2
while [ -e "$exp" ]; do exp="$root/$skill/${name}-$n"; n=$((n + 1)); done
mkdir -p "$exp/inputs" "$exp/results" "$exp/transcripts"

# --- snapshot whatever inputs this skill actually has -------------------------
for f in promptfooconfig.yaml promptfooconfig.browser.yaml arms.json; do
  [ -f "$f" ] && cp "$f" "$exp/inputs/$f"
done
[ -f objectives/redteam_objectives.json ] && \
  cp objectives/redteam_objectives.json "$exp/inputs/objectives.snapshot.json"

# redacted env: keep the choices (urls, models, filters), mask secret-looking values
if [ -f .env ]; then
  sed -E 's/^([A-Z_]*(KEY|TOKEN|SECRET|PASSWORD|AUTH)[A-Z_]*=).*/\1***REDACTED***/' .env \
    > "$exp/inputs/env.choices"
fi

# host for the record: prefer an exported var, else read it out of .env
host="${TARGET_URL:-${GUARDRAIL_URL:-${SHIM_GATEWAY_URL:-${ATTACKER_BASE_URL:-}}}}"
if [ -z "$host" ] && [ -f .env ]; then
  host=$(grep -E '^(TARGET_URL|GUARDRAIL_URL|SHIM_GATEWAY_URL|ATTACKER_BASE_URL)=' .env \
         | head -1 | cut -d= -f2-)
fi
commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
created=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > "$exp/manifest.json" <<JSON
{
  "skill": "$skill",
  "experiment": "$(basename "$exp")",
  "label": "$label",
  "created": "$created",
  "git_commit": "$commit",
  "engine": "$engine",
  "host": "$host",
  "command": "FILL IN: the exact run command, incl. --filter-* / model / strategy choices",
  "corpus": "FILL IN: source + filter + counts of what actually ran",
  "notes": ""
}
JSON

printf '%s\n' "$exp" > "$root/$skill/.last_experiment"   # convenience pointer
echo "experiment ready: $exp"
echo "  inputs snapshotted; fill the command/corpus fields in manifest.json after the run."
echo "EXP=$exp"
