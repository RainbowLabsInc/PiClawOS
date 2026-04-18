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

# Kern-Fix: piclaw/ als Symlink auf piclaw-os/piclaw/ setzen
# Damit zeigt der editable install auf den git-verwalteten Code
echo "  🔗 piclaw/ → piclaw-os/piclaw/ (Symlink)..."
if [[ -d "$INSTALL_DIR/piclaw-os/piclaw" ]]; then
    if [[ -d "$INSTALL_DIR/piclaw" && ! -L "$INSTALL_DIR/piclaw" ]]; then
        mv "$INSTALL_DIR/piclaw" "$INSTALL_DIR/piclaw.bak"
        echo "  ℹ  Alte piclaw/ gesichert als piclaw.bak/"
    fi
    ln -sfn "$INSTALL_DIR/piclaw-os/piclaw" "$INSTALL_DIR/piclaw"
    echo "  ✅ Symlink gesetzt"
else
    echo "  ⚠️  piclaw-os/piclaw/ nicht gefunden – Symlink nicht möglich"
fi

# tests/ verlinken
if [[ -d "$INSTALL_DIR/piclaw-os/tests" ]]; then
    ln -sfn "$INSTALL_DIR/piclaw-os/tests" "$INSTALL_DIR/tests" 2>/dev/null || true
    echo "  ✅ tests/ verlinkt"
fi

# pip install -e /opt/piclaw (pyproject.toml liegt dort)
echo "  📦 pip install -e $INSTALL_DIR ..."
"$VENV/bin/pip" install -e "$INSTALL_DIR/piclaw-os" -q || { echo "  ❌ pip install fehlgeschlagen"; exit 1; }
echo "  ✅ piclaw installiert"

# Rechte
chown -R "$PICLAW_USER":"$PICLAW_USER" "$INSTALL_DIR" 2>/dev/null || true
chown -R "$PICLAW_USER":"$PICLAW_USER" /var/log/piclaw 2>/dev/null || true

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

echo "" && echo "✅ Fertig! git pull → Änderungen sofort aktiv." && echo ""
