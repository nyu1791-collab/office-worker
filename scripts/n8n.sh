#!/usr/bin/env bash
# n8n 起動＋ワークフロー取込:  ./scripts/n8n.sh up|import|down|logs
set -e
cd "$(dirname "$0")/.."
DC=(docker compose -f docker/n8n/docker-compose.yml)
case "${1:-up}" in
  up) "${DC[@]}" up -d; sleep 8; "${DC[@]}" exec n8n n8n import:workflow --separate --input=/workflows
      echo "n8n: http://localhost:5678  (API: python -m officeworker serve)";;
  import) "${DC[@]}" exec n8n n8n import:workflow --separate --input=/workflows;;
  down) "${DC[@]}" down;;
  logs) "${DC[@]}" logs -f n8n;;
esac
