#!/usr/bin/env bash
# CodeQL CLI adapter (local — no GitHub repo needed). Uses `codeql` if on PATH, else the
# `gh codeql` extension (gh extension install github/gh-codeql). CLASS: sast. Deterministic → --repeats 1.
#   adapters/codeql.sh <tree> <out-dir> [--language <lang>] [--suite security-extended|security-and-quality]
# Compiled languages need a build: set CODEQL_BUILD="<build cmd>" (Java/C/C++/C#/Go).
# For the GitHub code-scanning path instead (keeps the scanner config out of the agent's view), see
# SKILL.md → RUN (ephemeral_repo.sh + workflow_dispatch).
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
lang=""; suite="security-extended"
while [ $# -gt 0 ]; do case "$1" in --language) lang="$2"; shift 2;; --suite) suite="$2"; shift 2;; *) shift;; esac; done

if command -v codeql >/dev/null; then CQL=(codeql)
elif gh codeql --version >/dev/null 2>&1; then CQL=(gh codeql)
else echo "codeql not found (install the CLI, or: gh extension install github/gh-codeql)" >&2; exit 1; fi

# Language detection: most common CODEQL-SUPPORTED source extension (config/docs are ignored, so a
# repo with more yaml than code still resolves to its actual language). Pass --language to override.
if [ -z "$lang" ]; then
  ext=$(find "$tree" -type f -not -path '*/node_modules/*' -not -path '*/.git/*' \
          \( -name '*.py' -o -name '*.js' -o -name '*.jsx' -o -name '*.ts' -o -name '*.tsx' \
             -o -name '*.java' -o -name '*.go' -o -name '*.rb' -o -name '*.cs' -o -name '*.swift' \
             -o -name '*.rs' -o -name '*.c' -o -name '*.h' -o -name '*.cpp' -o -name '*.cc' -o -name '*.hpp' \) \
          2>/dev/null \
        | sed -n 's/.*\.\([A-Za-z]*\)$/\1/p' | tr 'A-Z' 'a-z' | sort | uniq -c | sort -rn | awk 'NR==1{print $2}')
  case "$ext" in
    py) lang=python;; js|jsx|ts|tsx) lang=javascript;; java) lang=java;; go) lang=go;;
    rb) lang=ruby;; cs) lang=csharp;; c|h|cpp|cc|hpp) lang=cpp;; swift) lang=swift;; rs) lang=rust;;
    *) echo "no CodeQL-supported source files found in $tree — pass --language" >&2; exit 1;;
  esac
  echo "detected language: $lang" >&2
fi

db="$out/db"; rm -rf "$db"
"${CQL[@]}" database create "$db" --source-root "$tree" --language "$lang" \
    ${CODEQL_BUILD:+--command "$CODEQL_BUILD"} --overwrite
"${CQL[@]}" database analyze "$db" --format=sarifv2.1.0 --output "$out/findings.sarif" \
    "codeql/${lang}-queries:codeql-suites/${lang}-${suite}.qls"
[ -f "$out/findings.sarif" ]
