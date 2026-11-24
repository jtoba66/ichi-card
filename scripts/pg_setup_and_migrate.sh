#!/usr/bin/env bash
# Run this on HP AFTER: sudo apt install -y postgresql postgresql-client
# It creates the ichi user/db, installs the schema, and migrates SQLite data.
set -euo pipefail

echo "=== Creating PostgreSQL user and database ==="
sudo -u postgres psql -c "CREATE USER ichi WITH PASSWORD 'ichi';" 2>/dev/null || echo "  (user already exists)"
sudo -u postgres psql -c "CREATE DATABASE ichi_signals OWNER ichi;" 2>/dev/null || echo "  (database already exists)"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ichi_signals TO ichi;" 2>/dev/null || true

echo ""
echo "=== Initialising schema ==="
export ICHI_DATABASE_URL="postgresql://ichi:ichi@localhost/ichi_signals"
cd ~/ichi-scorecard
/home/joe/.local/bin/uv run python -c \
    "from ichi.signal.detector import init_db; init_db(); print('schema OK')"

echo ""
echo "=== Migrating SQLite data to PostgreSQL ==="
/home/joe/.local/bin/uv run python scripts/migrate_sqlite_to_pg.py

echo ""
echo "=== Done. Add to your service environment: ==="
echo "  ICHI_DATABASE_URL=postgresql://ichi:ichi@localhost/ichi_signals"
