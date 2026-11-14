#!/usr/bin/env bash
# Replay adapter: score a SARIF file that some tool already produced, without running the tool.
# Use it to bring results from a scanner that has no adapter here (a SaaS scanner, a CI export),
# and for the keyless smoke test. It is not a scanner.
#   adapters/replay.sh <tree> <out-dir> --sarif <file.sarif>
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
sarif=""
while [ $# -gt 0 ]; do case "$1" in --sarif) sarif="$2"; shift 2;; *) shift;; esac; done
[ -f "$sarif" ] || { echo "replay: --sarif <file> is required and must exist" >&2; exit 1; }
cp "$sarif" "$out/findings.sarif"
