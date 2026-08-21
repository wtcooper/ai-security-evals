#!/usr/bin/env bash
# osv-scanner adapter — dependency vulnerabilities from the OSV database (lockfiles/manifests/SBOM).
# CLASS: sca, NOT first-party SAST — see adapters/README.md. Deterministic given a pinned OSV snapshot,
# but the OSV database is live, so record the scan date in the manifest. → --repeats 1.
#   adapters/osv-scanner.sh <tree> <out-dir> [--lockfile PATH] [--offline]
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
lockfile=""; offline=""
while [ $# -gt 0 ]; do case "$1" in
  --lockfile) lockfile="$2"; shift 2;; --offline) offline="--offline-vulnerabilities"; shift;; *) shift;; esac; done
command -v osv-scanner >/dev/null || { echo "osv-scanner not installed (brew install osv-scanner)" >&2; exit 1; }
# osv-scanner exits 1 when vulns are FOUND — that is success for us, so only a >1 code is a failure.
set +e
if [ -n "$lockfile" ]; then
  osv-scanner scan source --format sarif --output-file "$out/findings.sarif" $offline --lockfile "$lockfile"
else
  osv-scanner scan source --format sarif --output-file "$out/findings.sarif" $offline "$tree"
fi
code=$?
set -e
[ "$code" -le 1 ] || { echo "osv-scanner failed (exit $code)" >&2; exit "$code"; }
[ -f "$out/findings.sarif" ]
