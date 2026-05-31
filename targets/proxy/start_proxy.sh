#!/usr/bin/env bash
# Start the shared LiteLLM proxy (AI gateway) on port 4000.
#
# This proxy is the gateway the test apps and the eval skills point at. It uses
# targets/proxy/litellm_config.yaml and the custom handlers in
# targets/proxy/mock_handlers.py. The working directory is set to the proxy dir so
# the custom handler module path resolves.
#
# Usage:
#   bash targets/proxy/start_proxy.sh              # foreground
#   bash targets/proxy/start_proxy.sh &            # background
set -euo pipefail

PROXY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$PROXY_DIR/../.." && pwd)"
cd "$PROXY_DIR"

# Load real provider keys (e.g. GCP_AI_STUDIO_API_KEY, OPENAI_API_KEY) for real
# models. Both .env and .env.local at the repo root are sourced (.local wins).
set -a
for f in "$REPO_ROOT/.env" "$REPO_ROOT/.env.local"; do
    # shellcheck disable=SC1090
    [ -f "$f" ] && . "$f"
done
set +a

exec uv run --project "$REPO_ROOT" litellm \
    --config "$PROXY_DIR/litellm_config.yaml" \
    --port 4000 \
    --num_workers 1
