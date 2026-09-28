#!/bin/sh
set -eu
cd "$(dirname "$0")"
case "${1:-up}" in
  init)
    if [ ! -f .env ]; then
      umask 077
      { echo "SIGNING_KEY=$(openssl rand -hex 32)"; echo "CONNECTOR_KEY=$(openssl rand -hex 32)"; } > .env
    fi
    ;;
  up)
    "$0" init
    docker compose up --build -d --wait
    echo 'Meridian: http://127.0.0.1:8088 (default port)'
    ;;
  down) docker compose down ;;
  logs) docker compose logs -f --tail=100 ;;
  *) echo 'Usage: ./manage.sh [init|up|down|logs]' >&2; exit 2 ;;
esac
