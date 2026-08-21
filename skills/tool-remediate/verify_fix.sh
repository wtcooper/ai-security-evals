#!/usr/bin/env bash
# Verify one remediation (design §7): a fix counts only if the exploit STOPS AND the functional
# suite stays green AND a regression test was added that fails on the pre-fix commit. Flags
# exploit-only "fixes" and scanner-says-fixed-but-exploit-works.
#   bash verify_fix.sh <EXP> <target-id> <repo> --exploit <cmd> --tests <cmd> [--pre-sha S --post-sha S] [--regression-test path]
# <cmd>s run in <repo>; --exploit must EXIT 0 when the app is still exploitable (like a probe).
set -euo pipefail
exp="${1:?}"; tid="${2:?}"; repo="${3:?}"; shift 3
exploit=""; tests=""; pre=""; post=""; regtest=""
while [ $# -gt 0 ]; do case "$1" in --exploit) exploit="$2"; shift 2;; --tests) tests="$2"; shift 2;;
  --pre-sha) pre="$2"; shift 2;; --post-sha) post="$2"; shift 2;; --regression-test) regtest="$2"; shift 2;;
  *) echo "unknown $1" >&2; exit 2;; esac; done
here="$(cd "$(dirname "$0")" && pwd)"; run=$(basename "$exp")
run_in() { ( cd "$repo" && eval "$1" ); }        # returns the command's exit status
[ -n "$post" ] && git -C "$repo" checkout -q "$post"

# exploit still works? (exit 0 = exploitable)
exploit_works=false; if [ -n "$exploit" ]; then run_in "$exploit" >/dev/null 2>&1 && exploit_works=true; fi
# functional tests green?
tests_pass=false; if [ -n "$tests" ]; then run_in "$tests" >/dev/null 2>&1 && tests_pass=true; fi
# regression test present and does it fail on the pre-fix commit?
reg_added=false; reg_catches=false
if [ -n "$regtest" ] && [ -n "$pre" ]; then
  [ -e "$repo/$regtest" ] && reg_added=true
  git -C "$repo" stash -q 2>/dev/null || true
  git -C "$repo" checkout -q "$pre"
  # bring just the regression test onto the pre-fix tree
  git -C "$repo" checkout -q "$post" -- "$regtest" 2>/dev/null || true
  if [ -n "$tests" ]; then run_in "$tests" >/dev/null 2>&1 || reg_catches=true; fi
  git -C "$repo" checkout -q "$post"
fi
fixed=false; [ "$exploit_works" = false ] && [ "$tests_pass" = true ] && fixed=true
exploit_only=false; [ "$exploit_works" = false ] && [ "$tests_pass" = false ] && exploit_only=true
python3 "$here/lib/manifest.py" "$exp" append-sample "{\"run\":\"$run\",\"arm\":\"fix\",\"target\":\"$tid\",\"sample\":1,\"exploit_works\":$exploit_works,\"tests_pass\":$tests_pass,\"fixed\":$fixed,\"exploit_only_fix\":$exploit_only,\"regression_added\":$reg_added,\"regression_catches_prefix\":$reg_catches}" >/dev/null
echo "FIXED=$fixed EXPLOIT_WORKS=$exploit_works TESTS_PASS=$tests_pass EXPLOIT_ONLY=$exploit_only REG_ADDED=$reg_added REG_CATCHES=$reg_catches"
