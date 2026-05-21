#!/usr/bin/env bash
# Start the local LiteLLM proxy on port 4000.
#
# The proxy uses local/litellm_config.yaml and the custom handlers in
# local/mock_handlers.py. Working directory is set to local/ so the custom
# handler module path resolves.
#
# Usage:
#   bash local/start_proxy.sh              # foreground
#   bash local/start_proxy.sh &            # background
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/local"

# Load .env.local for real provider keys when running real models. Optional.
if [ -f "$REPO_ROOT/.env.local" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$REPO_ROOT/.env.local"
    set +a
fi

exec uv run --project "$REPO_ROOT" litellm \
    --config "$REPO_ROOT/local/litellm_config.yaml" \
    --port 4000 \
    --num_workers 1
