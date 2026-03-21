#!/usr/bin/env bash
# ============================================================
#  PiClaw – Einmalige Reparatur des Install-Pfads
#  Macht: pip install -e piclaw-os/ statt piclaw-os/piclaw/
#  Danach: git pull reicht für alle Updates
#
#  Aufruf: sudo bash fix_install_path.sh
# ============================================================
set -euo pipefail

INSTALL_DIR="/opt/piclaw"
VENV="$INSTALL_DIR/.venv"
PICLAW_USER="piclaw"

echo ""
echo "🔧 PiClaw Install-Pfad reparieren"
echo "=================================="
echo ""

[[ $EUID -ne 0 ]] && { echo "❌ Bitte als root ausführen: sudo bash $0"; exit 1; }

# 1. Services stoppen
echo "  ⏸  Services stoppen..."
systemctl stop piclaw-api piclaw-agent 2>/dev/null || true

# 2. Prüfen ob piclaw-os/ vorhanden
if [[ ! -d "$INSTALL_DIR/piclaw-os" ]]; then
    echo "  ❌ $INSTALL_DIR/piclaw-os nicht gefunden"
    echo "     Bitte erst: cd $INSTALL_DIR && git pull origin main"
    exit 1
fi

# 3. tests/ aus piclaw-os/ verlinken
echo "  📁 tests/ und tools/ zugänglich machen..."
ln -sfn "$INSTALL_DIR/piclaw-os/tests" "$INSTALL_DIR/tests" 2>/dev/null || \
    cp -r "$INSTALL_DIR/piclaw-os/tests" "$INSTALL_DIR/" 2>/dev/null || true

# 4. pip install -e auf piclaw-os/ umstellen
echo "  📦 pip install -e piclaw-os/ ..."
"$VENV/bin/pip" install -e "$INSTALL_DIR/piclaw-os" -q 2>&1 | tail -3 || {
    echo "  ❌ pip install fehlgeschlagen"
    exit 1
}
echo "  ✅ piclaw zeigt jetzt auf piclaw-os/piclaw/"

# 5. Rechte setzen
chown -R "$PICLAW_USER":"$PICLAW_USER" "$INSTALL_DIR" 2>/dev/null || true

# 6. sudoers sicherstellen
SUDOERS_FILE="/etc/sudoers.d/piclaw"
if [[ ! -f "$SUDOERS_FILE" ]]; then
    echo "  🔑 sudoers-Regel setzen..."
    cat > "$SUDOERS_FILE" << 'SUDOEOF'
piclaw ALL=(ALL) NOPASSWD: \
  /bin/systemctl restart piclaw-api, \
  /bin/systemctl restart piclaw-agent, \
  /bin/systemctl restart piclaw-watchdog, \
  /bin/systemctl restart piclaw-crawler, \
  /bin/systemctl stop piclaw-api, \
  /bin/systemctl stop piclaw-agent, \
  /bin/systemctl start piclaw-api, \
  /bin/systemctl start piclaw-agent, \
  /usr/bin/git -C /opt/piclaw pull origin main
SUDOEOF
    chmod 440 "$SUDOERS_FILE"
    echo "  ✅ sudoers gesetzt"
fi

# 7. git pull via sudo ohne Passwort erlauben
echo "  🔑 git pull Rechte für piclaw-user..."
chown -R "$PICLAW_USER":"$PICLAW_USER" "$INSTALL_DIR/.git" 2>/dev/null || true

# 8. Services neu starten
echo "  ▶️  Services starten..."
systemctl start piclaw-api piclaw-agent 2>/dev/null || true

echo ""
echo "✅ Reparatur abgeschlossen!"
echo ""
echo "   Ab jetzt gilt:"
echo "   piclaw update       → git pull + Neustart automatisch"
echo "   piclaw debug        → Debug-Scripts verfügbar"
echo ""
