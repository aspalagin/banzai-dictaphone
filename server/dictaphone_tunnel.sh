#!/bin/bash
set -euo pipefail

LOGFILE=/tmp/cf-dictaphone-tunnel.log
CONF_FILE=${DICTAPHONE_TUNNEL_CONF:-/var/lib/banzai-dictaphone/tunnel.conf}
TARGET_URL=${DICTAPHONE_TUNNEL_TARGET_URL:-http://127.0.0.1:8097}

mkdir -p "$(dirname "$CONF_FILE")"
> "$LOGFILE"

cloudflared tunnel --url "$TARGET_URL" --no-autoupdate 2>&1 | tee "$LOGFILE" &
CF_PID=$!

NEW_URL=""
for _ in $(seq 1 60); do
  NEW_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGFILE" | tail -1 || true)
  if [ -n "$NEW_URL" ]; then
    break
  fi
  sleep 1
done

if [ -z "$NEW_URL" ]; then
  echo "[$(date -Is)] ERROR: Cloudflare tunnel URL was not detected" >&2
  wait "$CF_PID"
  exit 1
fi

cat > "$CONF_FILE" <<EOF
TUNNEL_URL=${NEW_URL}
DICTAPHONE_HTTP_URL=${NEW_URL}
DICTAPHONE_WS_URL=${NEW_URL/https:/wss:}/v1/stream
UPDATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo "[$(date -Is)] Dictaphone tunnel: ${NEW_URL}"
wait "$CF_PID"
