#!/usr/bin/env bash
# Trivy adapter — SCA (dependency CVEs) + misconfig (IaC/Dockerfile) + secrets over a filesystem tree.
# CLASS: sca/misconfig/secret, NOT first-party SAST — see adapters/README.md before comparing it
# head-to-head with semgrep/codeql on a SAST ground truth. Deterministic → --repeats 1.
#   adapters/trivy.sh <tree> <out-dir> [--scanners vuln,misconfig,secret] [--severity LOW,...]
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
scanners="vuln,misconfig,secret"; severity=""
while [ $# -gt 0 ]; do case "$1" in
  --scanners) scanners="$2"; shift 2;; --severity) severity="$2"; shift 2;; *) shift;; esac; done
command -v trivy >/dev/null || { echo "trivy not installed (brew install trivy)" >&2; exit 1; }
# trivy exits non-zero only on real errors here (no --exit-code), so failures surface honestly.
trivy fs --format sarif --output "$out/findings.sarif" --scanners "$scanners" \
  ${severity:+--severity "$severity"} --quiet "$tree"
[ -f "$out/findings.sarif" ]
