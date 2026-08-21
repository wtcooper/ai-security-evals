#!/usr/bin/env bash
# Open an experiment folder under .evals/<skill>/ and snapshot the inputs, so every
# run is auditable: what corpus/choices/config were used, the engine's native output,
# and the raw transcript all live in one legibly-named directory.
#
#   bash new_experiment.sh <skill> "<label>" [engine] [options]
#
#   engine   promptfoo (default for app-*/control-isolate) | inspect (control-bench)
#            | git-branch-ab (control-codegen) | detection-bench (tool-*)
#   options  --start-branch B   git-branch-ab: the frozen starting-state branch (default starting-state)
#            --arms A,B,C,D     arm names (git-branch-ab / detection-bench)
#            --k N              samples per arm
#            --spec S           spec id (e.g. spec-01)
#            --tool NAME[@VER]  the tool under test / driving generation
#            --model ID         model under test        --temperature T
#            --benchmark NAME[@VER]                     --pair-on target,sample
#            --repo OWNER/NAME  ephemeral GitHub repo the branches live in
#
# Folder name is  <label>_<date>  (deduped with -N for same-day reruns). Prints the
# absolute path as the last line (EXP=<path>); the RUN/ANALYZE steps write the
# engine's results, findings.jsonl / samples.jsonl, summary.md and transcripts into <EXP>.
# manifest.json is schema v2 (see docs/plans/sdlc-eval-implementation-plan.md P0.3);
# keys still to fill are listed in "_todo" — set them with lib/manifest.py.
set -euo pipefail

skill="${1:?usage: new_experiment.sh <skill> \"<label>\" [engine] [--k N --arms A,B ...]}"
label="${2:?provide a short legible label, e.g. acme-prod-cyber-smoke}"
shift 2
engine=""
if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then engine="$1"; shift; fi

start_branch="starting-state"; arms=""; k=""; spec=""; tool=""; model=""; temperature=""
benchmark=""; pair_on=""; repo=""
while [ $# -gt 0 ]; do
  case "$1" in
    --start-branch) start_branch="$2"; shift 2;;
    --arms) arms="$2"; shift 2;;
    --k) k="$2"; shift 2;;
    --spec) spec="$2"; shift 2;;
    --tool) tool="$2"; shift 2;;
    --model) model="$2"; shift 2;;
    --temperature) temperature="$2"; shift 2;;
    --benchmark) benchmark="$2"; shift 2;;
    --pair-on) pair_on="$2"; shift 2;;
    --repo) repo="$2"; shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

if [ -z "$engine" ]; then
  case "$skill" in
    control-bench) engine="inspect";;
    control-codegen) engine="git-branch-ab";;
    tool-*) engine="detection-bench";;
    *) engine="promptfoo";;
  esac
fi

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
mkdir -p "$exp/inputs" "$exp/results" "$exp/transcripts" "$exp/contamination"
case "$engine" in
  git-branch-ab) mkdir -p "$exp/arms" "$exp/probes" "$exp/branches";;
  detection-bench) mkdir -p "$exp/targets";;
esac

# --- snapshot whatever inputs this skill actually has -------------------------
for f in promptfooconfig.yaml promptfooconfig.browser.yaml arms.json build-prompt.md SPEC.md; do
  [ -f "$f" ] && cp "$f" "$exp/inputs/$f"
done
[ -d specs ] && cp -R specs "$exp/inputs/specs"
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

# --- git-branch-ab: record the frozen starting state + tripwire tag -----------
start_sha="null"; tag_sha="null"; start_warn=""
if [ "$engine" = "git-branch-ab" ]; then
  s=$(git rev-parse "$start_branch" 2>/dev/null || true)
  t=$(git rev-parse "${start_branch}-locked^{commit}" 2>/dev/null || true)
  [ -n "$s" ] && start_sha="\"$s\""
  [ -n "$t" ] && tag_sha="\"$t\""
  if [ -n "$s" ] && [ -n "$t" ] && [ "$s" != "$t" ]; then
    start_warn="WARNING: $start_branch ($s) != ${start_branch}-locked tag ($t) — starting state was edited"
  fi
fi

# --- JSON helpers -------------------------------------------------------------
jstr() { if [ -z "$1" ]; then printf 'null'; else printf '"%s"' "$(printf '%s' "$1" | sed 's/"/\\"/g')"; fi; }
jnum() { if [ -z "$1" ]; then printf 'null'; else printf '%s' "$1"; fi; }
jarms() {  # "A,B" -> [{"name":"A"},{"name":"B"}]
  if [ -z "$1" ]; then printf '[]'; return; fi
  printf '['; local first=1 a
  IFS=',' read -ra _arr <<< "$1"
  for a in "${_arr[@]}"; do
    [ $first -eq 1 ] || printf ','
    printf '{"name":"%s","condition":null,"pre_build_diff":[],"branch_glob":"exp/%s/sample*"}' "$a" "$a"
    first=0
  done; printf ']'
}
jsplit() { # "a,b" -> ["a","b"]
  if [ -z "$1" ]; then printf 'null'; return; fi
  printf '['; local first=1 a; IFS=',' read -ra _arr <<< "$1"
  for a in "${_arr[@]}"; do [ $first -eq 1 ] || printf ','; printf '"%s"' "$a"; first=0; done; printf ']'
}
tool_name="${tool%%@*}"; tool_ver=""; [ "$tool" != "$tool_name" ] && tool_ver="${tool#*@}"
bench_name="${benchmark%%@*}"; bench_ver=""; [ "$benchmark" != "$bench_name" ] && bench_ver="${benchmark#*@}"
todo=""
add_todo() { todo="${todo:+$todo,}\"$1\""; }
[ -n "$tool" ] || add_todo "tool.name"
[ -n "$model" ] || add_todo "model.id"
[ -n "$k" ] || add_todo "k"
[ -n "$arms" ] || add_todo "arms"
add_todo "scorers"; add_todo "model.cutoff"; add_todo "cost.usd"
[ "$engine" = "git-branch-ab" ] && { [ -n "$spec" ] || add_todo "benchmark.spec"; }
[ "$engine" = "detection-bench" ] && { [ -n "$benchmark" ] || add_todo "benchmark.name"; }
[ -n "$pair_on" ] || pair_on="target,sample"

cat > "$exp/manifest.json" <<JSON
{
  "schema_version": 2,
  "skill": "$skill",
  "experiment": "$(basename "$exp")",
  "label": "$label",
  "created": "$created",
  "git_commit": "$commit",
  "engine": "$engine",
  "host": "$host",
  "command": "FILL IN: the exact run command, incl. --filter-* / model / strategy choices",
  "corpus": "FILL IN: source + filter + counts of what actually ran",
  "notes": "",
  "tool": {"name": $(jstr "$tool_name"), "version": $(jstr "$tool_ver")},
  "model": {"id": $(jstr "$model"), "temperature": $(jnum "$temperature"), "family": null, "cutoff": null},
  "benchmark": {"name": $(jstr "$bench_name"), "version": $(jstr "$bench_ver"), "spec": $(jstr "$spec")},
  "arms": $(jarms "$arms"),
  "k": $(jnum "$k"),
  "paired": true,
  "pair_on": $(jsplit "$pair_on"),
  "scorers": [],
  "starting_state": {"branch": $(jstr "$([ "$engine" = git-branch-ab ] && printf '%s' "$start_branch")"), "sha": $start_sha, "tag_sha": $tag_sha},
  "repo": {"remote": $(jstr "$repo"), "visibility": null, "archived": false},
  "contamination": {"canary_probe": null, "contaminated_targets": [], "trace_audit": null},
  "cost": {"usd": 0, "tokens_in": 0, "tokens_out": 0, "wall_s": 0},
  "_todo": [$todo]
}
JSON

printf '%s\n' "$exp" > "$root/$skill/.last_experiment"   # convenience pointer
echo "experiment ready: $exp"
[ -n "$start_warn" ] && echo "  $start_warn" >&2
if [ "$engine" = "git-branch-ab" ]; then
  echo "  starting-state branch '$start_branch' @ ${start_sha//\"/}"
  echo "  drop each arm's pre-build files in arms/<name>/; scoring writes results/<arm>/sample<i>/, findings.jsonl, samples.jsonl."
else
  echo "  inputs snapshotted; fill the command/corpus fields in manifest.json after the run."
fi
echo "  remaining manifest fields: [$todo]  (lib/manifest.py <EXP> set <key> <value>)"
echo "EXP=$exp"
