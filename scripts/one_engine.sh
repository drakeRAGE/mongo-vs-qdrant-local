#!/usr/bin/env bash
# POSIX helper for WSL/Linux. On Windows use one_engine.ps1.
set -euo pipefail
ENGINE="${1:-}"
if [[ "$ENGINE" != "mongo" && "$ENGINE" != "qdrant" && "$ENGINE" != "none" ]]; then
  echo "usage: $0 mongo|qdrant|none" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/compose/docker-compose.yml"
PROJECT="vectordb-proof"

docker compose -p "$PROJECT" -f "$COMPOSE" --profile mongo down --remove-orphans || true
docker compose -p "$PROJECT" -f "$COMPOSE" --profile qdrant down --remove-orphans || true
if [[ "$ENGINE" == "none" ]]; then
  echo "No engine running."
  exit 0
fi
mkdir -p "$ROOT/data/docker/mongod" "$ROOT/data/docker/mongot" "$ROOT/data/docker/qdrant"
docker compose -p "$PROJECT" -f "$COMPOSE" --profile "$ENGINE" up -d
echo "Profile $ENGINE is up."
