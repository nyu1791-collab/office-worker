#!/usr/bin/env bash
# n8n を Docker なしで起動（要 Node.js）: ./scripts/n8n-local.sh [import]
set -e
cd "$(dirname "$0")/.."
export GENERIC_TIMEZONE=Asia/Tokyo N8N_DIAGNOSTICS_ENABLED=false N8N_BLOCK_ENV_ACCESS_IN_NODE=false
[ -f .env ] && export $(grep -E '^(OW_API_TOKEN|OW_API_URL)=' .env | xargs) || true
flag="$HOME/.n8n/.officeworker_imported"
if [ "${1:-up}" = import ] || [ ! -f "$flag" ]; then
  npx --yes n8n import:workflow --separate --input=n8n/workflows
  mkdir -p "$(dirname "$flag")"; touch "$flag"
  [ "${1:-up}" = import ] && exit 0
fi
echo "n8n: http://localhost:5678  (API: python -m officeworker serve)"
npx --yes n8n start
