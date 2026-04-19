#!/usr/bin/env bash
# NEXUS v4.0 — Setup script (Linux/macOS)
# Installs Python dependencies and prepares the environment.

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " NEXUS v4.0 — Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "[✗] python3 not found. Please install Python 3.8 or later."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[✓] Python ${PY_VERSION} detected"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "[•] Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
# shellcheck disable=SC1091
source .venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip --quiet

# Install dependencies
if [ -f "requirements.txt" ]; then
    echo "[•] Installing dependencies from requirements.txt..."
    pip install -r requirements.txt --quiet
else
    echo "[•] Installing baseline dependencies..."
    pip install requests pyyaml --quiet
fi

echo ""
echo "[✓] Setup complete."
echo ""
echo "Next step: validate your hardware"
echo "    source .venv/bin/activate"
echo "    python tools/validate_v4.py --target <BMC_IP> --user <user> --pass <password>"
echo ""
