#!/usr/bin/env bash
# End-to-end tests for all four skills against REAL models via the local LiteLLM
# gateway. target = gemini-3-flash-preview, judge/attacker/grader = gemini-3.1-flash-lite.
#
# Requires GCP_AI_STUDIO_API_KEY in .env (Google AI Studio free tier). Kept tiny to
# stay under free-tier rate limits. Usage:
#   bash e2e/run_e2e.sh [app-eval|control-isolate|control-bench|app-redteam|all]
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
WHICH="${1:-all}"
export PROMPTFOO_DISABLE_TELEMETRY=true PROMPTFOO_DISABLE_REMOTE_GENERATION=true
PY=.venv/bin/python
PASS=0; FAIL=0
note() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }

cleanup() { pkill -f "litellm --config" 2>/dev/null; pkill -f injection_shim.py 2>/dev/null; }
trap cleanup EXIT

# --- preflight ---
grep -q GCP_AI_STUDIO_API_KEY .env 2>/dev/null || { echo "Set GCP_AI_STUDIO_API_KEY in .env first."; exit 1; }
note "Starting LiteLLM gateway (:4000)"
cleanup; sleep 1
bash targets/proxy/start_proxy.sh >/tmp/e2e_proxy.log 2>&1 &
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:4000/health/readiness && break; sleep 2; done
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health/readiness)" = "200" ] \
  && echo "  gateway up" || { echo "  gateway failed; see /tmp/e2e_proxy.log"; exit 1; }
$PY skills/_shared/build_corpus.py --tier smoke >/dev/null 2>&1

run_app_eval() {
  note "app-eval  (real target gemini-flash + judge gemini-flash-lite)"
  # -j 1 + a small sample: the free tier rate-limits (429) aggressively. The harness
  # retries 429 transiently, but keep the footprint small or runs crawl.
  npx promptfoo eval -c e2e/app-eval.e2e.yaml --filter-sample 4 -j 1 \
    --output /tmp/e2e_app_eval.json --no-progress-bar --no-cache >/tmp/e2e_app_eval.log 2>&1
  $PY skills/_shared/summarize.py /tmp/e2e_app_eval.json | tee /tmp/e2e_app_eval.summary
  grep -q "errors excluded: 0" /tmp/e2e_app_eval.summary && grep -q "answer" /tmp/e2e_app_eval.summary \
    && ok "app-eval ran with real models, no errors" || bad "app-eval (see /tmp/e2e_app_eval.log)"
}

run_control_isolate() {
  note "control-isolate  (real LiteLLM content-filter, 403 blocks)"
  npx promptfoo eval -c e2e/control-isolate.e2e.yaml -j 2 \
    --output /tmp/e2e_ci.json --no-progress-bar --no-cache >/tmp/e2e_ci.log 2>&1
  $PY skills/_shared/summarize.py /tmp/e2e_ci.json | tee /tmp/e2e_ci.summary
  grep -q "block 3" /tmp/e2e_ci.summary && grep -q "403" /tmp/e2e_ci.summary \
    && ok "content-filter 403 blocks auto-classified (no env)" || bad "control-isolate (see /tmp/e2e_ci.log)"
}

run_control_bench() {
  note "control-bench  (A/B: baseline vs content-filter, real gemini via shim+Inspect)"
  command -v $PY >/dev/null && $PY -c "import inspect_ai" 2>/dev/null || { bad "control-bench: inspect_ai not installed (pip install inspect_ai)"; return; }
  ( cd skills/control-bench
    for a in "baseline:8951:[]" "guarded:8952:[\"content-filter\"]"; do
      n=${a%%:*}; rest=${a#*:}; p=${rest%%:*}; g=${rest#*:}
      SHIM_CONNECTOR=litellm SHIM_GATEWAY_URL=http://127.0.0.1:4000 SHIM_GATEWAY_KEY=sk-mock \
        SHIM_ARM="{\"name\":\"$n\",\"model\":\"\",\"guardrails\":$g}" \
        "$ROOT/$PY" injection_shim.py "$p" >/tmp/e2e_shim_$n.log 2>&1 &
    done )
  sleep 3
  export BASELINE_BASE_URL=http://127.0.0.1:8951/v1 BASELINE_API_KEY=sk-mock GUARDED_BASE_URL=http://127.0.0.1:8952/v1 GUARDED_API_KEY=sk-mock
  rm -rf /tmp/e2e_cb_logs
  ( cd e2e && "$ROOT/.venv/bin/inspect" eval inspect_e2e_task.py \
      --model "openai-api/baseline/gemini-3-flash-preview,openai-api/guarded/gemini-3-flash-preview" \
      --log-dir /tmp/e2e_cb_logs >/tmp/e2e_cb.log 2>&1 )
  $PY - <<'PY' | tee /tmp/e2e_cb.summary
from inspect_ai.log import list_eval_logs, read_eval_log
acc={}
for p in list_eval_logs("/tmp/e2e_cb_logs"):
    log=read_eval_log(p)
    a=next((s.metrics["accuracy"].value for s in (log.results.scores or []) if "accuracy" in s.metrics),None)
    acc["guarded" if "guarded" in log.eval.model else "baseline"]=a
print(f"A/B: baseline {acc.get('baseline')} -> content-filter {acc.get('guarded')}")
PY
  pkill -f injection_shim.py 2>/dev/null
  grep -q "baseline 1.0 -> content-filter 0.0" /tmp/e2e_cb.summary \
    && ok "control reduced attack success 1.0 -> 0.0" || bad "control-bench (see /tmp/e2e_cb.log)"
}

run_app_redteam() {
  note "app-redteam  (real attacker+grader gemini-flash-lite, basic strategy)"
  rm -f e2e/redteam.yaml
  npx promptfoo redteam run -c e2e/app-redteam.e2e.yaml --max-concurrency 1 --force \
    --output /tmp/e2e_rt.json >/tmp/e2e_rt.log 2>&1
  rm -f e2e/redteam.yaml
  grep -qiE "Red team scan complete|passed" /tmp/e2e_rt.log \
    && ok "redteam ran end-to-end (target+grader; adaptive strategies need remote gen)" \
    || bad "app-redteam (see /tmp/e2e_rt.log)"
}

case "$WHICH" in
  app-eval) run_app_eval ;;
  control-isolate) run_control_isolate ;;
  control-bench) run_control_bench ;;
  app-redteam) run_app_redteam ;;
  all) run_app_eval; sleep 20; run_control_isolate; sleep 20; run_control_bench; sleep 20; run_app_redteam ;;
  *) echo "unknown: $WHICH"; exit 2 ;;
esac

note "e2e summary"
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
