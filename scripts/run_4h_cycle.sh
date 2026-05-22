#!/usr/bin/env bash
# 4-hour OHLCV refresh + signal tracker
# Called by cron 5 minutes after each 4h candle close (00,04,08,12,16,20 UTC)

set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJ/data/logs"
LOG="$LOG_DIR/cycle.log"
MAX_LOG_BYTES=5242880   # 5 MB — truncate oldest half when exceeded

mkdir -p "$LOG_DIR"

# Simple log rotation
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt "$MAX_LOG_BYTES" ]; then
    tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*" | tee -a "$LOG"; }

log "===== 4h cycle START ====="

cd "$PROJ"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

# 1. Refresh OHLCV cache
log "Refreshing OHLCV (1d, 4h, 1w)..."
if "$UV" run ichi refresh --timeframes 1d,4h,1w --workers 8 >> "$LOG" 2>&1; then
    log "Refresh OK"
else
    log "ERROR: Refresh failed (exit $?)"
fi

# 2. Run signal tracker
log "Running tracker..."
if "$UV" run python -m ichi.signal.jobs track >> "$LOG" 2>&1; then
    log "Tracker OK"
else
    log "ERROR: Tracker failed (exit $?)"
fi

log "===== 4h cycle DONE ====="
