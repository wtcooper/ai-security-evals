#!/usr/bin/env bash
# Install promptfoo locally and set the air-gap posture. Idempotent.
set -euo pipefail
cd "$(dirname "$0")"

export PROMPTFOO_DISABLE_TELEMETRY=true
export PROMPTFOO_DISABLE_REMOTE_GENERATION=true

if ! command -v npx >/dev/null 2>&1; then
  echo "node/npx not found — install Node >= 18 first." >&2
  exit 1
fi

# Pin promptfoo locally (not global) so runs are reproducible and air-gapped.
npx -y promptfoo@latest --version >/dev/null
echo "promptfoo ready. Air-gap env: PROMPTFOO_DISABLE_TELEMETRY + PROMPTFOO_DISABLE_REMOTE_GENERATION."
echo "Next: python ../_shared/build_corpus.py --tier smoke && npx promptfoo validate -c promptfooconfig.yaml"
