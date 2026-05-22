#!/usr/bin/env bash
# ============================================================
# Ichi Scorecard — Ubuntu setup script
# Run once on the HP Ubuntu machine as user 'joe'
# Usage: bash deploy/setup_ubuntu.sh
# ============================================================
set -euo pipefail

PROJ="/home/joe/ichi-scorecard"
REPO="https://github.com/jtoba66/ichi-card.git"

echo ""
echo "================================================"
echo " Ichi Scorecard — Ubuntu install"
echo "================================================"
echo ""

# ── 1. System deps ────────────────────────────────────────────
echo "[1/7] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip curl git rsync

# ── 2. Install uv ────────────────────────────────────────────
echo "[2/7] Installing uv..."
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi
echo "  uv $(uv --version)"

# ── 3. Clone repo ─────────────────────────────────────────────
echo "[3/7] Cloning repo..."
if [ -d "$PROJ/.git" ]; then
    echo "  Repo already exists — pulling latest..."
    git -C "$PROJ" pull
else
    git clone "$REPO" "$PROJ"
fi

# ── 4. Python venv + deps ─────────────────────────────────────
echo "[4/7] Installing Python dependencies..."
cd "$PROJ"
uv sync

# ── 5. Create data dirs (rsync will fill them) ────────────────
echo "[5/7] Creating data directories..."
mkdir -p "$PROJ/data/ohlcv"
mkdir -p "$PROJ/data/logs"

# ── 6. Cron: 4h cycle at :05 past each 4h candle close (UTC) ─
echo "[6/7] Installing cron job (UTC 00,04,08,12,16,20 + 5min)..."
chmod +x "$PROJ/scripts/run_4h_cycle.sh"
CRON_LINE="5 0,4,8,12,16,20 * * * /bin/bash $PROJ/scripts/run_4h_cycle.sh"
# Add only if not already present
if ! crontab -l 2>/dev/null | grep -qF "run_4h_cycle"; then
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "  Cron installed"
else
    echo "  Cron already present — skipping"
fi

# ── 7. Systemd services ───────────────────────────────────────
echo "[7/7] Installing systemd services..."
sudo cp "$PROJ/deploy/ichi-api.service"       /etc/systemd/system/
sudo cp "$PROJ/deploy/ichi-dashboard.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ichi-api ichi-dashboard
sudo systemctl restart ichi-api ichi-dashboard

echo ""
echo "================================================"
echo " Install complete!"
echo ""
echo " Services:"
echo "   FastAPI   → http://localhost:8000"
echo "   Dashboard → http://localhost:7890/ichi-scorecard.html"
echo ""
echo " NEXT: copy your data from the Mac:"
echo "   (run this on the Mac, replace HP_IP with HP's IP)"
echo ""
echo "   rsync -avz --progress \\"
echo "     ~/Documents/tradera/ichi-scorecard/data/ \\"
echo "     joe@HP_IP:/home/joe/ichi-scorecard/data/"
echo ""
echo " Then restart services:"
echo "   ssh joe@HP_IP 'sudo systemctl restart ichi-api'"
echo ""
echo " Check service status:"
echo "   sudo systemctl status ichi-api"
echo "   sudo systemctl status ichi-dashboard"
echo "   tail -f /home/joe/ichi-scorecard/data/logs/cycle.log"
echo "================================================"
