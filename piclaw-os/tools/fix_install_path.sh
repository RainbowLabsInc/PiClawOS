#!/usr/bin/env bash
# ============================================================
#  PiClaw – Einmalige Reparatur des Install-Pfads
#  Aufruf: sudo bash /opt/piclaw/piclaw-os/tools/fix_install_path.sh
# ============================================================
set -euo pipefail

INSTALL_DIR="/opt/piclaw"
VENV="$INSTALL_DIR/.venv"
PICLAW_USER="piclaw"

echo "" && echo "🔧 PiClaw Install-Pfad reparieren" && echo "==================================" && echo ""

[[ $EUID -ne 0 ]] && { echo "❌ Bitte als root ausführen: sudo bash $0"; exit 1; }

echo "  ⏸  Services stoppen..."
systemctl stop piclaw-api piclaw-agent 2>/dev/null || true

# Pip-Ziel ermitteln
if [[ -f "$INSTALL_DIR/piclaw-os/pyproject.toml" ]]; then
    PIP_TARGET="$INSTALL_DIR/piclaw-os"
    TESTS_SRC="$INSTALL_DIR/piclaw-os/tests"
elif [[ -f "$INSTALL_DIR/pyproject.toml" ]]; then
    PIP_TARGET="$INSTALL_DIR"
    TESTS_SRC="$INSTALL_DIR/piclaw-os/tests"
else
    echo "  ❌ Kein pyproject.toml gefunden"; exit 1
fi
echo "  ℹ  pip-Ziel: $PIP_TARGET"

# tests/ verlinken
if [[ -d "$TESTS_SRC" ]]; then
    ln -sfn "$TESTS_SRC" "$INSTALL_DIR/tests" 2>/dev/null || true
    echo "  ✅ tests/ verlinkt"
fi

# pip install
echo "  📦 pip install -e $PIP_TARGET ..."
"$VENV/bin/pip" install -e "$PIP_TARGET" -q || { echo "  ❌ pip install fehlgeschlagen"; exit 1; }
echo "  ✅ piclaw installiert"

# Rechte
chown -R "$PICLAW_USER":"$PICLAW_USER" "$INSTALL_DIR" 2>/dev/null || true

# sudoers
cat > /etc/sudoers.d/piclaw << 'SUDOEOF'
piclaw ALL=(ALL) NOPASSWD: \
  /bin/systemctl restart piclaw-api, \
  /bin/systemctl restart piclaw-agent, \
  /bin/systemctl stop piclaw-api, \
  /bin/systemctl stop piclaw-agent, \
  /bin/systemctl start piclaw-api, \
  /bin/systemctl start piclaw-agent
SUDOEOF
chmod 440 /etc/sudoers.d/piclaw
echo "  ✅ sudoers gesetzt"

systemctl start piclaw-api piclaw-agent 2>/dev/null || true

echo "" && echo "✅ Fertig! Ab jetzt: piclaw update" && echo ""
