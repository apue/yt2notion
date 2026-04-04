#!/bin/bash
# Batch transcription with ASR server auto-restart every BATCH_SIZE segments
# macOS compatible

set -e

ASR_HOST="yangtian@192.168.0.16"
WORKSPACE="workspace/1000755501308"
BATCH_SIZE=20
TOTAL_SEGMENTS=89
URL="https://podcasts.apple.com/us/podcast/133-%E8%B0%A2%E8%B5%9B%E5%AE%81-%E5%85%B3%E4%BA%8E%E5%81%9A%E7%A0%94%E7%A9%B6%E7%9A%84%E4%B8%80%E5%88%87-%E4%B8%8B/id1634356920?i=1000755501308"

get_progress() {
    python3 -c "import json; d=json.loads(open('${WORKSPACE}/transcripts.json').read()); print(len(d))"
}

restart_asr() {
    echo "$(date): Restarting ASR server..."
    ssh "$ASR_HOST" "pkill -9 -f 'python server.py' || true"
    sleep 5
    ssh "$ASR_HOST" "cd ~/asr-service && nohup .venv/bin/python server.py > logs/stdout.log 2> logs/stderr.log &"
    for i in $(seq 1 60); do
        if curl -s --max-time 5 "http://192.168.0.16:8930/health" >/dev/null 2>&1; then
            echo "$(date): ASR server ready"
            return 0
        fi
        sleep 2
    done
    echo "$(date): ERROR: ASR server failed to start"
    return 1
}

current=$(get_progress)
echo "$(date): Starting. Progress: ${current}/${TOTAL_SEGMENTS}"

while [ "$current" -lt "$TOTAL_SEGMENTS" ]; do
    target=$((current + BATCH_SIZE))
    [ "$target" -gt "$TOTAL_SEGMENTS" ] && target=$TOTAL_SEGMENTS

    echo "$(date): Batch ${current}→${target}. Launching pipeline..."

    # Launch pipeline in background
    uv run yt2notion "$URL" --dry-run -v --from transcribe --resume "$WORKSPACE" &
    PID=$!

    # Monitor until batch target or timeout (15 min per segment max)
    max_wait=$((BATCH_SIZE * 900))
    waited=0
    last_progress=$current

    while kill -0 "$PID" 2>/dev/null && [ "$waited" -lt "$max_wait" ]; do
        sleep 60
        waited=$((waited + 60))
        new_progress=$(get_progress)

        if [ "$new_progress" != "$last_progress" ]; then
            echo "$(date): Progress: ${new_progress}/${TOTAL_SEGMENTS}"
            last_progress=$new_progress
        fi

        if [ "$new_progress" -ge "$target" ]; then
            echo "$(date): Batch target reached!"
            kill "$PID" 2>/dev/null || true
            wait "$PID" 2>/dev/null || true
            break
        fi

        # Detect stall: if no progress in 10 min, restart
        if [ "$((waited % 600))" -eq 0 ] && [ "$new_progress" -eq "$current" ] && [ "$waited" -gt 600 ]; then
            echo "$(date): Stall detected. Restarting..."
            kill "$PID" 2>/dev/null || true
            wait "$PID" 2>/dev/null || true
            break
        fi
    done

    # Cleanup if still running
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true

    current=$(get_progress)
    echo "$(date): Batch done. Progress: ${current}/${TOTAL_SEGMENTS}"

    if [ "$current" -lt "$TOTAL_SEGMENTS" ]; then
        restart_asr
    fi
done

echo "$(date): All ${TOTAL_SEGMENTS} segments transcribed!"
