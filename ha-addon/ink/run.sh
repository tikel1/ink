#!/usr/bin/env sh
set -e

# Home Assistant writes the add-on options here.
OPTS=/data/options.json
get() { python -c "import json;print(json.load(open('$OPTS')).get('$1',''))"; }

export IMAGE_PROVIDER=openai
export PLATFORM_OPENAI_API_KEY="$(get platform_openai_api_key)"
export MASTER_ENCRYPTION_KEY="$(get master_encryption_key)"
export ADMIN_TOKEN="$(get admin_token)"
export PUBLIC_BASE_URL="$(get public_base_url)"
export APP_URL="$(get app_url)"

# Persistent per-add-on storage (survives restarts/updates).
export DATA_DIR=/data/store
mkdir -p "$DATA_DIR"

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
