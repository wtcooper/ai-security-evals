#!/usr/bin/env bash
# Guard: every skill folder must be copy-paste self-contained — no reference that
# escapes the folder (sibling skills, tools/, targets/, absolute machine paths).
# A skill dropped into another repo must work on its own.
#
#   bash scripts/check_independence.sh
set -uo pipefail
cd "$(dirname "$0")/.."

# `tools/` is the maintainer build layer — never referenced from a skill. Repo-root `targets/`
# (proxy/dvaa/aigoat) must not be referenced either, EXCEPT by security-tool-benchmark, whose
# runbook emits a runtime experiment tree at $EXP/targets/ (a path it creates, not a repo
# reference) — allowlisted below. `# payload` tags intentional attack strings in probe suites.
# Sibling skill names are read from the tree, so a new skill is covered without editing this file.
names=$(ls -d plugins/*/skills/*/ | xargs -n1 basename | paste -sd'|' -)
escape_base="\\.\\./\\.\\.|\\.\\./(${names})|(^|[^a-zA-Z._/\$-])tools/|/_shared|/Users/|/home/[a-z]"
targets_rule='(^|[^a-zA-Z._/$-])targets/'

fail=0
for d in plugins/*/skills/*/; do
  s=$(basename "$d")
  escape="$escape_base"
  case "$s" in
    security-tool-benchmark) : ;;                        # emits a runtime $EXP/targets/ tree
    *) escape="${escape_base}|${targets_rule}" ;;
  esac
  hits=$(grep -rnE "$escape" "$d" \
    --include='*.md' --include='*.yaml' --include='*.yml' --include='*.js' \
    --include='*.cjs' --include='*.py' --include='*.sh' --include='*.json' 2>/dev/null \
    | grep -v node_modules | grep -v '# payload' || true)
  if [ -n "$hits" ]; then
    echo "FAIL ($s): references that escape the skill folder —" >&2
    echo "$hits" | sed 's/^/    /' >&2
    fail=1
  fi
done

# Intra-skill '..' refs (e.g. adapters/ -> ../lib) must resolve inside the folder.
while IFS=: read -r f _ ref; do
  [ -z "$ref" ] && continue
  tgt="$(dirname "$f")/$ref"
  if [ ! -e "$tgt" ]; then echo "FAIL: unresolved intra ref $f -> $ref" >&2; fail=1; fi
done < <(grep -rnE "\.\./[a-zA-Z0-9_./-]+" plugins/*/skills/*/ \
           --include='*.js' --include='*.cjs' --include='*.py' 2>/dev/null | grep -v node_modules \
           | grep -v '# payload' \
           | awk -F: '{f=$1; l=$2; $1=""; $2=""; s=$0;
                       while (match(s, /\.\.\/[a-zA-Z0-9_.\/-]+/)) { print f ":" l ":" substr(s, RSTART, RLENGTH); s=substr(s, RSTART+RLENGTH) } }')

if [ "$fail" -eq 0 ]; then
  echo "  ok — all skills are copy-paste self-contained (no escaping references)"
fi
exit "$fail"
