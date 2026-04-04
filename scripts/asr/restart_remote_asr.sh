#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${1:-}"
if [[ -z "${REMOTE_HOST}" ]]; then
  echo "Usage: $0 <asr_host>" >&2
  exit 2
fi
ASR_DIR="${ASR_DIR:-/Users/${USER}/asr-service}"
PYTHON_BIN="${PYTHON_BIN:-$ASR_DIR/.venv-mlx/bin/python}"
SERVICE_FILE="${SERVICE_FILE:-$ASR_DIR/server_mlx.py}"
HEALTH_URL="${HEALTH_URL:-http://$REMOTE_HOST:8930/health}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-10}"
HEALTH_RETRIES="${HEALTH_RETRIES:-40}"
HEALTH_INTERVAL_SECONDS="${HEALTH_INTERVAL_SECONDS:-3}"
PATH_EXPORT='PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'

ssh -o BatchMode=yes -o ConnectTimeout="${SSH_CONNECT_TIMEOUT}" "${REMOTE_HOST}" \
  "set -e; ${PATH_EXPORT}; command -v ffmpeg >/dev/null; pkill -f '${SERVICE_FILE}' || true; \
   cd '${ASR_DIR}'; nohup env ${PATH_EXPORT} '${PYTHON_BIN}' '${SERVICE_FILE}' \
   > '${ASR_DIR}/logs/stdout_mlx.log' 2> '${ASR_DIR}/logs/stderr_mlx.log' < /dev/null &"

for ((i=1; i<=HEALTH_RETRIES; i++)); do
  if curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null; then
    echo "ASR restarted and healthy (${HEALTH_URL})"
    exit 0
  fi
  sleep "${HEALTH_INTERVAL_SECONDS}"
done

echo "ASR restart timeout: ${HEALTH_URL} not healthy after ${HEALTH_RETRIES} checks" >&2
exit 1
