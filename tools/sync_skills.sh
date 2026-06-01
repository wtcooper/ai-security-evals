#!/usr/bin/env bash
# Vendor the canonical runtime libs (tools/lib) and the prebuilt corpus into each
# standalone skill, so every skill folder is self-contained (no cross-skill imports).
#
# tools/ is the single source of truth; skills get committed copies. CI runs this +
# `git diff --exit-code` to ensure the vendored copies never drift.
#
#   bash tools/sync_skills.sh
set -euo pipefail
cd "$(dirname "$0")"                 # tools/
ROOT=".."
PY="${PYTHON:-$ROOT/.venv/bin/python}"

vendor() {  # vendor <skill> <lib-file>...
  local skill="$1"; shift
  mkdir -p "$ROOT/skills/$skill/lib"
  for f in "$@"; do cp "lib/$f" "$ROOT/skills/$skill/lib/$f"; done
}

# --- runtime libs per skill (only what each one uses) ---
vendor app-eval        status_policy.js transform_response.js summarize.py
vendor app-redteam     status_policy.js transform_response.js
vendor control-isolate status_policy.js summarize.py
vendor control-bench   status_policy.py

# --- prebuilt, license-clean corpus (full tier; skills sample at run time) ---
$PY build_corpus.py --tier full --out "$ROOT/skills/app-eval/corpus" >/dev/null
$PY build_corpus.py --tier full --assert guardrail --out "$ROOT/skills/control-isolate/corpus" >/dev/null

# --- prebuilt red-team OBJECTIVE pack (drives promptfoo's local `intent` plugin) ---
$PY build_redteam_objectives.py >/dev/null
mkdir -p "$ROOT/skills/app-redteam/objectives"
cp corpus/redteam_objectives.json corpus/redteam_objectives.smoke.json \
   corpus/redteam_objectives.manifest.json "$ROOT/skills/app-redteam/objectives/"

echo "synced libs + corpus + redteam objectives into app-eval, app-redteam, control-isolate, control-bench"
