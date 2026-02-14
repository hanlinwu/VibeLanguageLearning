#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.docker"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT_DIR}/.env.docker.example" "${ENV_FILE}"
  echo "Created ${ENV_FILE}. Please edit it (at least LLM_API_KEY), then rerun."
  exit 1
fi

docker compose --env-file "${ENV_FILE}" up -d --build

echo "Frontend: http://localhost"
echo "Health:   http://localhost/api/health"
