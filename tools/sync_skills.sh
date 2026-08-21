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
vendor app-eval        status_policy.js transform_response.js summarize.py extract_transcript.js
vendor app-redteam     status_policy.js transform_response.js extract_transcript.js
vendor control-isolate status_policy.js summarize.py extract_transcript.js
vendor control-bench   status_policy.py

# --- shared eval spine (design doc §2.3): findings/samples contract, paired stats,
#     SARIF normaliser, manifest editor, contamination probe, sdlc locator, probe helpers ---
SPINE="evalstats.py sarif_to_findings.py cwe_map.py manifest.py canary_probe.py find_sdlc.sh probelib.py"
SPINE_SKILLS="control-codegen"
for s in $SPINE_SKILLS; do vendor "$s" $SPINE; done
for s in $(cd "$ROOT/skills" && ls -d tool-* 2>/dev/null); do vendor "$s" $SPINE; done

# --- promptfoo setup script: each promptfoo skill ships its OWN copy (no cross-skill
#     reference) so a skill folder is copy-paste self-contained ---
for s in app-eval app-redteam control-isolate; do
  cp install_dependencies.sh "$ROOT/skills/$s/install_dependencies.sh"
done

# --- experiment scaffolder: every skill ships its own copy (self-contained) ---
for s in app-eval app-redteam control-isolate control-bench $SPINE_SKILLS \
         $(cd "$ROOT/skills" && ls -d tool-* 2>/dev/null); do
  cp new_experiment.sh "$ROOT/skills/$s/new_experiment.sh"
done

# --- ephemeral GitHub repo + CodeQL driver: skills that push branches for scoring ---
REPO_SKILLS="control-codegen tool-codescan tool-remediate"
for s in $REPO_SKILLS; do
  [ -d "$ROOT/skills/$s" ] && cp ephemeral_repo.sh "$ROOT/skills/$s/ephemeral_repo.sh"
done

# --- prebuilt, license-clean corpus (full tier; skills sample at run time) ---
$PY build_corpus.py --tier full --out "$ROOT/skills/app-eval/corpus" >/dev/null
$PY build_corpus.py --tier full --assert guardrail --out "$ROOT/skills/control-isolate/corpus" >/dev/null

# --- prebuilt red-team OBJECTIVE pack (drives promptfoo's local `intent` plugin) ---
$PY build_redteam_objectives.py >/dev/null
mkdir -p "$ROOT/skills/app-redteam/objectives"
cp corpus/redteam_objectives.json corpus/redteam_objectives.smoke.json \
   corpus/redteam_objectives.manifest.json "$ROOT/skills/app-redteam/objectives/"

echo "synced libs + corpus + redteam objectives into app-eval, app-redteam, control-isolate, control-bench, control-codegen, tool-*"
