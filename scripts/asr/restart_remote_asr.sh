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
STOP_WAIT_SECONDS="${STOP_WAIT_SECONDS:-45}"
PATH_EXPORT='PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'
ASR_PORT=8930

start_output="$(
  ssh -o BatchMode=yes -o ConnectTimeout="${SSH_CONNECT_TIMEOUT}" "${REMOTE_HOST}" \
    "set -eu; ${PATH_EXPORT}; command -v ffmpeg >/dev/null; \
     pkill -f '${SERVICE_FILE}' || true; \
     deadline=\$((SECONDS + ${STOP_WAIT_SECONDS})); \
     while :; do \
       old_pids=\$(pgrep -f '${SERVICE_FILE}' || true); \
       listener_pids=\$(lsof -tiTCP:${ASR_PORT} -sTCP:LISTEN || true); \
       if [[ -z \"\$old_pids\" && -z \"\$listener_pids\" ]]; then \
         break; \
       fi; \
       if (( SECONDS >= deadline )); then \
         echo 'Timed out waiting for old ASR process/listener to exit' >&2; \
         echo \"old_pids=\${old_pids:-none}\" >&2; \
         echo \"listener_pids=\${listener_pids:-none}\" >&2; \
         exit 1; \
       fi; \
       sleep 1; \
     done; \
     cd '${ASR_DIR}'; \
     mkdir -p '${ASR_DIR}/logs'; \
     nohup env ${PATH_EXPORT} '${PYTHON_BIN}' '${SERVICE_FILE}' \
       > '${ASR_DIR}/logs/stdout_mlx.log' 2> '${ASR_DIR}/logs/stderr_mlx.log' < /dev/null & \
     new_pid=\$!; \
     sleep 1; \
     if ! kill -0 \"\$new_pid\" 2>/dev/null; then \
       echo \"New ASR process exited immediately (pid=\$new_pid)\" >&2; \
       exit 1; \
     fi; \
     echo \"NEW_PID=\$new_pid\""
)"

NEW_PID="$(printf '%s\n' "${start_output}" | sed -n 's/^NEW_PID=//p' | tail -n 1)"
if [[ ! "${NEW_PID}" =~ ^[0-9]+$ ]]; then
  echo "Failed to capture new ASR PID from remote restart output" >&2
  if [[ -n "${start_output}" ]]; then
    printf '%s\n' "${start_output}" >&2
  fi
  exit 1
fi

for ((i=1; i<=HEALTH_RETRIES; i++)); do
  if ssh -o BatchMode=yes -o ConnectTimeout="${SSH_CONNECT_TIMEOUT}" "${REMOTE_HOST}" \
    "set -eu; \
     listener_pids=\$(lsof -tiTCP:${ASR_PORT} -sTCP:LISTEN || true); \
     [[ -n \"\$listener_pids\" ]]; \
     echo \"\$listener_pids\" | grep -qx '${NEW_PID}'; \
     kill -0 '${NEW_PID}' 2>/dev/null; \
     ps -p '${NEW_PID}' -o command= | grep -F '${SERVICE_FILE}' >/dev/null" \
    >/dev/null 2>&1 && curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null; then
    echo "ASR restarted and healthy (${HEALTH_URL}, pid=${NEW_PID})"
    exit 0
  fi
  sleep "${HEALTH_INTERVAL_SECONDS}"
done

echo "ASR restart timeout: ${HEALTH_URL} not healthy with pid=${NEW_PID} after ${HEALTH_RETRIES} checks" >&2
exit 1
