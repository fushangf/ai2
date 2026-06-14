#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "This removes only the project's Docker named MySQL volume."
echo "The legacy ./data/mysql directory is preserved."
read -r -p "Continue? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
docker compose down -v --remove-orphans
docker compose up --build
