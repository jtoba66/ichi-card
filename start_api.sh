#!/usr/bin/env bash
# Start the ichi API with the correct database URL.
# Usage: bash start_api.sh
export ICHI_DATABASE_URL=postgresql://ichi:ichi@localhost/ichi_signals
cd ~/ichi-scorecard
mkdir -p data/logs
exec /home/joe/.local/bin/uv run uvicorn ichi.api.main:app --port 8000 --host 0.0.0.0 --log-level warning
