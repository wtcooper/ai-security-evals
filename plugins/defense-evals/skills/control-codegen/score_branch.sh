#!/usr/bin/env bash
# Score ONE built sample with the held-constant ensemble (design doc §3.3) and fold the results
# into <EXP>/findings.jsonl + samples.jsonl:
#   1. CodeQL (GitHub, dispatched for this branch)   -> results/<arm>/sample<i>/codeql/   (tool=codeql)
#   2. Docker build + run                              -> build_ok
#   3. Dynamic probes  (probes/<spec>)                 -> tool=probe rows (exploitable / oracle_confirmed)
#   4. Acceptance suite (acceptance/<spec>)            -> acceptance_pass / passed / total
#   5. scan-code (LLM review, sdlc run_scan.py) x N    -> tool=scan-code rows, tool_run=r
#   6. optional Semgrep                                -> tool=semgrep rows
#
#   bash score_branch.sh <EXP> <repo-dir> <arm> <i> [--scan-code-repeats 3] [--no-codeql] [--no-docker]
#        [--semgrep] [--port 18080] [--allow-same-family] [--codeql-timeout 1800]
#
# Env: SCORER_MODEL + AISEC_GATEWAY_BASE_URL/AISEC_GATEWAY_API_KEY for scan-code (must be a
# different model family from the generator unless --allow-same-family); DOCKER_NETWORK, SINK_URL
# for SSRF egress probes.
set -euo pipefail
exp="${1:?usage: score_branch.sh <EXP> <repo-dir> <arm> <i>}"; repo="${2:?}"; arm="${3:?}"; i="${4:?}"; shift 4
repeats="${SCAN_CODE_REPEATS:-3}"; do_codeql=1; do_docker=1; do_semgrep=0; port="${PROBE_PORT:-18080}"
allow_same=0; cq_timeout=1800
while [ $# -gt 0 ]; do
  case "$1" in --scan-code-repeats) repeats="$2"; shift 2;; --no-codeql) do_codeql=0; shift;;
    --no-docker) do_docker=0; shift;; --semgrep) do_semgrep=1; shift;; --port) port="$2"; shift 2;;
    --allow-same-family) allow_same=1; shift;; --codeql-timeout) cq_timeout="$2"; shift 2;;
    *) echo "unknown $1" >&2; exit 2;; esac
done
here="$(cd "$(dirname "$0")" && pwd)"
M="python3 $here/lib/manifest.py"; S2F="python3 $here/lib/sarif_to_findings.py"
run=$(basename "$exp"); branch="exp/$arm/sample$i"
spec=$($M "$exp" get benchmark.spec | tr -d '"'); [ "$spec" = null ] && spec="spec"
out="$exp/results/$arm/sample$i"; mkdir -p "$out"
findings="$exp/findings.jsonl"
ctx=(--run "$run" --arm "$arm" --target "$spec" --sample "$i" --spec "$spec")
ctx_json="{\"run\":\"$run\",\"arm\":\"$arm\",\"target\":\"$spec\",\"sample\":$i,\"spec\":\"$spec\"}"

# remove any earlier rows for this (arm,sample) so re-scoring is idempotent
if [ -f "$findings" ]; then
  python3 - "$findings" "$arm" "$i" <<'PY'
import json,sys
p,arm,i=sys.argv[1],sys.argv[2],int(sys.argv[3])
rows=[l for l in open(p) if l.strip() and not ((json.loads(l).get("arm")==arm) and json.loads(l).get("sample")==i)]
open(p,"w").writelines(rows)
PY
fi

# --- worktree for the branch ---------------------------------------------------------------
wt=$(mktemp -d); trap 'git -C "$repo" worktree remove --force "$wt/tree" >/dev/null 2>&1 || true; rm -rf "$wt"' EXIT
git -C "$repo" worktree add -q "$wt/tree" "$branch"
tree="$wt/tree"; sha=$(git -C "$tree" rev-parse HEAD)

# --- 1. CodeQL -----------------------------------------------------------------------------
if [ $do_codeql -eq 1 ]; then
  if r=$(bash "$here/ephemeral_repo.sh" codeql-run --dir "$repo" --ref "$branch" --sha "$sha" --wait --timeout "$cq_timeout" 2>"$out/codeql.log"); then
    echo "$r" | sed 's/^/  codeql: /'
    bash "$here/ephemeral_repo.sh" codeql-alerts --dir "$repo" --ref "$branch" --out "$out/codeql" >>"$out/codeql.log" 2>&1 || true
    [ -f "$out/codeql/alerts.json" ] && $S2F "$out/codeql/alerts.json" --format gh-alerts --tool codeql "${ctx[@]}" --append "$findings"
  else
    echo "  codeql: FAILED (see $out/codeql.log)" >&2
  fi
fi

# --- 2. docker build + run ---------------------------------------------------------------
build_ok=false; base_url="http://localhost:$port"; cname="eval-$arm-$i-$$"
if [ $do_docker -eq 1 ] && [ -f "$tree/Dockerfile" ]; then
  if docker build -q -t "eval-$spec-$arm-$i" "$tree" > "$out/docker-build.log" 2>&1; then
    docker run -d --rm --name "$cname" ${DOCKER_NETWORK:+--network "$DOCKER_NETWORK"} -p "$port:8080" "eval-$spec-$arm-$i" > /dev/null 2>"$out/docker-run.log" || true
    trap 'docker rm -f "$cname" >/dev/null 2>&1 || true; git -C "$repo" worktree remove --force "$wt/tree" >/dev/null 2>&1 || true; rm -rf "$wt"' EXIT
    if python3 -c "import sys; sys.path.insert(0,'$here/lib'); from probelib import wait_for_http; sys.exit(0 if wait_for_http('$base_url/', 90) else 1)"; then
      build_ok=true
    else
      docker logs "$cname" > "$out/docker-run.log" 2>&1 || true
    fi
  fi
elif [ $do_docker -eq 1 ]; then
  echo "  no Dockerfile in $branch — build_ok=false" >&2
fi

# --- 3/4. probes + acceptance ------------------------------------------------------------
acc_pass=null; acc_passed=0; acc_total=0; n_expl=0
if [ "$build_ok" = true ]; then
  if [ -d "$here/probes/$spec" ]; then
    (cd "$here" && python3 -m pytest "probes/$spec" -q -p no:cacheprovider --base-url "$base_url" \
        --findings-out "$out/probes.jsonl" --ctx "$ctx_json" ${SINK_URL:+--sink-url "$SINK_URL"} \
        > "$out/probes.log" 2>&1) || true
    if [ -f "$out/probes.jsonl" ]; then cat "$out/probes.jsonl" >> "$findings"; n_expl=$(wc -l < "$out/probes.jsonl" | tr -d ' '); fi
  fi
  if [ -d "$here/acceptance/$spec" ]; then
    (cd "$here" && python3 -m pytest "acceptance/$spec" -q -p no:cacheprovider --base-url "$base_url" \
        --acceptance-out "$out/acceptance.jsonl" --ctx "$ctx_json" > "$out/acceptance.log" 2>&1) || true
    if [ -f "$out/acceptance.jsonl" ]; then
      read -r acc_passed acc_total < <(python3 -c 'import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(sum(1 for r in rows if r["passed"]), len(rows))' "$out/acceptance.jsonl")
      [ "$acc_total" -gt 0 ] && { [ "$acc_passed" -eq "$acc_total" ] && acc_pass=true || acc_pass=false; }
    fi
  fi
  docker rm -f "$cname" >/dev/null 2>&1 || true
fi

# --- 5. scan-code (LLM review) x repeats -----------------------------------------------------
if [ "$repeats" -gt 0 ] && [ -n "${SCORER_MODEL:-}" ]; then
  gen_model=$($M "$exp" get model.id | tr -d '"')
  fam() { case "$1" in claude*|anthropic*) echo anthropic;; gpt*|o[0-9]*|openai*) echo openai;; gemini*|google*) echo google;;
           *llama*|meta*) echo meta;; qwen*|alibaba*) echo alibaba;; deepseek*) echo deepseek;; mistral*|mixtral*) echo mistral;; *) echo "$1";; esac; }
  if [ "$(fam "$gen_model")" = "$(fam "$SCORER_MODEL")" ] && [ $allow_same -eq 0 ]; then
    echo "  scan-code: SCORER_MODEL ($SCORER_MODEL) is the same family as the generator ($gen_model) — refusing (self-preference bias); pass --allow-same-family to override" >&2
  else
    scan_dir=$(bash "$here/lib/find_sdlc.sh" --plugin code-scan --skill scan-code)
    for r in $(seq 1 "$repeats"); do
      d="$out/scan-code/run$r"; mkdir -p "$d"
      if AISEC_MODEL="$SCORER_MODEL" python3 "$scan_dir/scripts/run_scan.py" --path "$tree" --out "$d" > "$d/run.log" 2>&1; then
        sarif=$(ls "$d"/*.sarif 2>/dev/null | head -1)
        [ -n "$sarif" ] && $S2F "$sarif" --tool scan-code --tool-run "$r" --strip-prefix "$tree" "${ctx[@]}" --append "$findings"
      else
        echo "  scan-code run$r failed (see $d/run.log)" >&2
      fi
    done
  fi
elif [ "$repeats" -gt 0 ]; then
  echo "  scan-code skipped: set SCORER_MODEL (+ AISEC_GATEWAY_BASE_URL/AISEC_GATEWAY_API_KEY)" >&2
fi

# --- 6. optional semgrep -----------------------------------------------------------------
if [ $do_semgrep -eq 1 ] && command -v semgrep >/dev/null; then
  (cd "$tree" && semgrep --config p/security-audit --config p/secrets --sarif --output "$out/semgrep.sarif" . >/dev/null 2>&1) || true
  [ -f "$out/semgrep.sarif" ] && $S2F "$out/semgrep.sarif" --tool semgrep "${ctx[@]}" --append "$findings"
fi

# --- fold into samples.jsonl -------------------------------------------------------------
$M "$exp" append-sample "{\"run\":\"$run\",\"arm\":\"$arm\",\"target\":\"$spec\",\"sample\":$i,\"branch\":\"$branch\",\"sha\":\"$sha\",\"build_ok\":$build_ok,\"acceptance_pass\":$acc_pass,\"acceptance_passed\":$acc_passed,\"acceptance_total\":$acc_total,\"exploitable_count\":$n_expl}" >/dev/null
echo "BUILD_OK=$build_ok"; echo "ACCEPTANCE=$acc_passed/$acc_total"; echo "EXPLOITABLE=$n_expl"; echo "RESULTS=$out"
