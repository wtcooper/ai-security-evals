#!/usr/bin/env bash
# CodeQL CLI adapter (local, no GitHub). Deterministic → run with --repeats 1.
#   adapters/codeql.sh <tree> <out-dir> [--language <lang>] [--suite <qls>]
# <language> defaults to autodetect; for compiled languages CodeQL must be able to build the tree
# (set CODEQL_BUILD or make the tree buildable). For the GitHub code-scanning path instead, see
# SKILL.md → RUN (ephemeral_repo.sh + workflow_dispatch).
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
lang=""; suite="security-extended"
while [ $# -gt 0 ]; do case "$1" in --language) lang="$2"; shift 2;; --suite) suite="$2"; shift 2;; *) shift;; esac; done
command -v codeql >/dev/null || { echo "codeql CLI not installed (https://github.com/github/codeql-cli-binaries)" >&2; exit 1; }
db="$out/db"
if [ -n "$lang" ]; then
  codeql database create "$db" --source-root "$tree" --language "$lang" ${CODEQL_BUILD:+--command "$CODEQL_BUILD"} --overwrite -q
else
  codeql database create "$db" --source-root "$tree" --db-cluster --language "$(codeql resolve languages --format=json 2>/dev/null >/dev/null; echo javascript)" --overwrite -q 2>/dev/null || \
  codeql database create "$db" --source-root "$tree" --language javascript --overwrite -q
fi
codeql database analyze "$db" --format=sarifv2.1.0 --output "$out/findings.sarif" "codeql/$(basename "$db")-queries:codeql-suites/${suite}" -q 2>/dev/null || \
codeql database analyze "$db" --format=sarifv2.1.0 --output "$out/findings.sarif" --sarif-category codeql -q
[ -f "$out/findings.sarif" ]
