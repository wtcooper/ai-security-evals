#!/usr/bin/env bash
# Fetch remediation benchmarks with their paired oracles (design §7). Verifies availability.
#   bash fetch_targets.sh <EXP> <bench>   bench=vul4py | patcheval
set -euo pipefail
exp="${1:?}"; bench="${2:?}"; dst="$exp/targets/$bench"; mkdir -p "$dst"
clone() { [ -d "$2/.git" ] || git clone -q --depth 1 "$1" "$2"; git -C "$2" rev-parse HEAD; }
case "$bench" in
  vul4py)   echo "WARNING: Vul4Py (arXiv 2608.00692) — confirm the public release/repo before relying on it" >&2
            echo "100 Python vulns / 60 CWEs, paired exploit + pytest oracles; populate $dst/<id>/{repo,exploit.sh,tests}." > "$dst/README.md";;
  patcheval) sha=$(clone https://github.com/bytedance/PatchEval "$dst/src" 2>/dev/null || echo "unavailable")
            echo "PatchEval @ $sha (1,000 CVEs Go/JS/Py, 230 dockerized) — use the dockerized subset; each has security + functional tests." > "$dst/README.md";;
  *) echo "unknown bench $bench" >&2; exit 2;;
esac
echo "TARGETS=$dst"
