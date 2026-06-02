#!/usr/bin/env bash
# Guard: every skill folder must be copy-paste self-contained — no reference that
# escapes the folder (sibling skills, tools/, targets/, absolute machine paths).
# A skill dropped into another repo must work on its own.
#
#   bash scripts/check_independence.sh
set -uo pipefail
cd "$(dirname "$0")/.."

# References that would break once the folder is copied out on its own.
escape='\.\./\.\.|\.\./(app-eval|app-redteam|control-isolate|control-bench)|(^|[^a-zA-Z._-])(tools|targets)/|/_shared|/Users/|/home/[a-z]'

fail=0
for d in skills/*/; do
  s=$(basename "$d")
  hits=$(grep -rnE "$escape" "$d" \
    --include='*.md' --include='*.yaml' --include='*.yml' --include='*.js' \
    --include='*.cjs' --include='*.py' --include='*.sh' --include='*.json' 2>/dev/null \
    | grep -v node_modules || true)
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
done < <(grep -rnoE "\.\./[a-zA-Z0-9_./-]+" skills/*/ \
           --include='*.js' --include='*.cjs' --include='*.py' 2>/dev/null | grep -v node_modules)

if [ "$fail" -eq 0 ]; then
  echo "  ok — all skills are copy-paste self-contained (no escaping references)"
fi
exit "$fail"
