#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# PiClaw OS – Direct Installer v0.9.0
#
# Installs PiClaw OS onto a running Raspberry Pi OS Lite (arm64).
# This is the recommended approach for ALL operating systems
# (Windows, macOS, Linux) – no image build required.
#
# Voraussetzungen:
#   - Raspberry Pi 5 (oder 4) mit Raspberry Pi OS Lite 64-bit (Bookworm)
#   - Internetverbindung
#   - SSH-Zugang oder direkte Verbindung
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/youruser/piclaw-os/main/install.sh | bash
#   # or locally:
#   bash install.sh
#   bash install.sh --api-key sk-ant-XXXXXXXXX --telegram-token 12345:ABCDE
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

BOLD="\e[1m"; GREEN="\e[32m"; CYAN="\e[36m"; YELLOW="\e[33m"; RED="\e[31m"; R="\e[0m"

info()    { echo -e "${GREEN}[✓]${R} $*"; }
section() { echo -e "\n${CYAN}${BOLD}━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R}"; }
warn()    { echo -e "${YELLOW}[!]${R} $*"; }
die()     { echo -e "${RED}[✗]${R} $*" >&2; exit 1; }
prompt()  { echo -en "${BOLD}  → ${R}$* "; }

PICLAW_VERSION="0.9.0"
INSTALL_DIR="/opt/piclaw"
CONFIG_DIR="/etc/piclaw"
LOG_DIR="/var/log/piclaw"
PICLAW_USER="piclaw"
REPO_URL="https://github.com/youruser/piclaw-os"   # ← EDIT if self-hosting

# ── CLI args ──────────────────────────────────────────────────────
API_KEY=""
TELEGRAM_TOKEN=""
TELEGRAM_CHAT_ID=""
SKIP_WIZARD=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --api-key)          API_KEY="$2";           shift 2;;
        --telegram-token)   TELEGRAM_TOKEN="$2";    shift 2;;
        --telegram-chat)    TELEGRAM_CHAT_ID="$2";  shift 2;;
        --skip-wizard)      SKIP_WIZARD=true;       shift;;
        --force)            FORCE=true;             shift;;
        -h|--help)
            echo "Usage: install.sh [--api-key KEY] [--telegram-token TOKEN] [--skip-wizard] [--force]"
            exit 0;;
        *) die "Unknown option: $1";;
    esac
done

# ─────────────────────────────────────────────────────────────────
echo -e "${CYAN}${BOLD}"
cat << 'LOGO'
  ██████╗ ██╗ ██████╗██╗      █████╗ ██╗    ██╗
  ██╔══██╗██║██╔════╝██║     ██╔══██╗██║    ██║
  ██████╔╝██║██║     ██║     ███████║██║ █╗ ██║
  ██╔═══╝ ██║██║     ██║     ██╔══██║██║███╗██║
  ██║     ██║╚██████╗███████╗██║  ██║╚███╔███╔╝
  ╚═╝     ╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝  OS v0.9.0
LOGO
echo -e "${R}"
echo "  KI-Betriebssystem für Raspberry Pi 5"
echo "  Installer – Direct Install auf Raspberry Pi OS"
echo ""

# ── Voraussetzungen prüfen ────────────────────────────────────────
section "Systemprüfung"

[[ $EUID -ne 0 ]] && die "Bitte als root ausführen: sudo bash install.sh"

# Architektur
ARCH=$(uname -m)
[[ "$ARCH" != "aarch64" ]] && die "Nur ARM64 (aarch64) unterstützt. Aktuelle Architektur: $ARCH"
info "Architektur: $ARCH"

# Debian/Raspberry Pi OS
if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    info "OS: $PRETTY_NAME"
    [[ "$ID" != "debian" && "$ID_LIKE" != *"debian"* ]] && \
        warn "Nicht Debian/Raspberry Pi OS – könnte Probleme geben"
else
    warn "/etc/os-release nicht gefunden"
fi

# Python 3.11+
PY=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
PY_MAJ=$(echo "$PY" | cut -d. -f1)
PY_MIN=$(echo "$PY" | cut -d. -f2)
if [[ $PY_MAJ -lt 3 || ( $PY_MAJ -eq 3 && $PY_MIN -lt 11 ) ]]; then
    warn "Python 3.11+ empfohlen, gefunden: $PY"
else
    info "Python: $PY"
fi

# Speicher prüfen
RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
if [[ $RAM_MB -lt 2000 ]]; then
    warn "Wenig RAM: ${RAM_MB}MB – lokales LLM benötigt mind. 4GB"
else
    info "RAM: ${RAM_MB}MB"
fi

# Disk prüfen
FREE_GB=$(df / | awk 'NR==2{print int($4/1024/1024)}')
[[ $FREE_GB -lt 4 ]] && warn "Wenig freier Speicher: ${FREE_GB}GB (mind. 8GB empfohlen)"
info "Freier Speicher: ${FREE_GB}GB"

# Bestehende Installation?
if [[ -d "$INSTALL_DIR" && "$FORCE" != "true" ]]; then
    warn "PiClaw ist bereits installiert in $INSTALL_DIR"
    prompt "Neu installieren / aktualisieren? [j/N]:"
    read -r ans
    [[ "$ans" != "j" && "$ans" != "J" ]] && die "Installation abgebrochen"
fi

# ── System-User anlegen ───────────────────────────────────────────
section "System-User anlegen"

if ! id "$PICLAW_USER" &>/dev/null; then
    useradd -r -s /bin/bash -d "$INSTALL_DIR" -m "$PICLAW_USER"
    usermod -aG gpio,i2c,spi,dialout,video,audio "$PICLAW_USER" 2>/dev/null || true
    info "User '$PICLAW_USER' angelegt"
else
    info "User '$PICLAW_USER' bereits vorhanden"
fi

# Watchdog-User (isoliert)
if ! id "piclaw-watchdog" &>/dev/null; then
    useradd -r -s /bin/false -d /nonexistent "piclaw-watchdog"
    info "User 'piclaw-watchdog' angelegt (isoliert)"
fi

# ── Abhängigkeiten installieren ───────────────────────────────────
section "System-Abhängigkeiten installieren"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

PKGS=(
    python3 python3-pip python3-venv
    sqlite3 nodejs npm
    network-manager
    i2c-tools
    curl wget git
    htop
)
info "Installiere Pakete: ${PKGS[*]}"
apt-get install -y "${PKGS[@]}"

# QMD (Hybrid Memory)
if ! command -v qmd &>/dev/null; then
    info "Installiere QMD (Hybrid Memory Engine)…"
    npm install -g @tobilu/qmd --silent 2>/dev/null || \
        warn "QMD Installation fehlgeschlagen – Memory-Funktionen eingeschränkt"
fi

info "System-Pakete OK"

# ── PiClaw installieren ───────────────────────────────────────────
section "PiClaw OS installieren"

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR"
chown "$PICLAW_USER":"$PICLAW_USER" "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR"

# Wenn wir aus einem lokalen Verzeichnis installieren (Entwicklungsmodus)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    info "Lokale Installation aus: $SCRIPT_DIR"
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
    rm -rf "$INSTALL_DIR/build" "$INSTALL_DIR/.git" 2>/dev/null || true
else
    info "Klone Repository von $REPO_URL"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || \
        die "Repository konnte nicht geklont werden. Bitte manuell installieren."
fi
chown -R "$PICLAW_USER":"$PICLAW_USER" "$INSTALL_DIR"
info "Dateien installiert"

# Python venv + requirements
info "Python-Umgebung einrichten…"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip

# Core deps
"$INSTALL_DIR/.venv/bin/pip" install --quiet \
    fastapi "uvicorn[standard]" aiohttp \
    psutil tomli-w "croniter>=1.4" \
    websockets httpx \
    rank_bm25

# Optional (sensor libraries)
"$INSTALL_DIR/.venv/bin/pip" install --quiet \
    smbus2 \
    RPi.GPIO gpiozero 2>/dev/null || \
    warn "GPIO-Bibliotheken nicht installiert (kein Pi? Normal auf Nicht-Pi-Hardware)"

# LLM deps
"$INSTALL_DIR/.venv/bin/pip" install --quiet \
    "discord.py>=2.3" 2>/dev/null || \
    warn "discord.py nicht installiert"

# Install piclaw package itself
"$INSTALL_DIR/.venv/bin/pip" install --quiet -e "$INSTALL_DIR" 2>/dev/null || \
    warn "piclaw package install fehlgeschlagen – versuche manuell"

info "Python-Umgebung OK"

# ── I2C / SPI aktivieren ──────────────────────────────────────────
section "Hardware-Interfaces aktivieren"

# Pi 5: config.txt liegt in /boot/firmware/
CONFIG_TXT=""
for p in /boot/firmware/config.txt /boot/config.txt; do
    [[ -f "$p" ]] && CONFIG_TXT="$p" && break
done

if [[ -n "$CONFIG_TXT" ]]; then
    if ! grep -q "dtparam=i2c_arm=on" "$CONFIG_TXT" 2>/dev/null; then
        echo "dtparam=i2c_arm=on"  >> "$CONFIG_TXT"
        echo "dtparam=spi=on"      >> "$CONFIG_TXT"
        echo "dtoverlay=w1-gpio"   >> "$CONFIG_TXT"
        info "I2C, SPI, 1-Wire in $CONFIG_TXT aktiviert (Neustart nötig)"
    else
        info "I2C bereits aktiviert"
    fi
else
    warn "config.txt nicht gefunden – I2C/SPI bitte manuell aktivieren"
fi

# ── Konfiguration anlegen ─────────────────────────────────────────
section "Konfiguration anlegen"

mkdir -p "$CONFIG_DIR/ipc" "$CONFIG_DIR/skills"
chown -R "$PICLAW_USER":"$PICLAW_USER" "$CONFIG_DIR"

# Generiere API-Token
API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

cat > "$CONFIG_DIR/config.toml" << TOMLEOF
# PiClaw OS v${PICLAW_VERSION} – Konfiguration
# Generiert: $(date)

[agent]
name = "PiClaw"
mode = "hybrid"          # local | cloud | hybrid

[api]
host       = "0.0.0.0"
port       = 7842
secret_key = "${API_TOKEN}"

[llm]
backend  = "local"       # anthropic | openai | ollama | local
model    = "phi3:mini"
api_key  = "${API_KEY}"
base_url = ""
max_tokens  = 2048
temperature = 0.7
timeout     = 60

[memory]
enabled     = true
max_entries = 50000
index_dir   = "${CONFIG_DIR}/memory"

[shell]
enabled      = true
allowed_cmds = ["ls","cat","df","free","top","ps","systemctl","nmcli","i2cdetect","vcgencmd"]

[services]
managed = ["piclaw-agent","piclaw-api","piclaw-crawler"]

[messaging]
telegram_token   = "${TELEGRAM_TOKEN}"
telegram_chat_id = "${TELEGRAM_CHAT_ID}"
discord_token    = ""
threema_id       = ""
whatsapp_token   = ""

[updater]
auto_update    = false
update_channel = "stable"

[hardware]
fan_enabled    = false
fan_pin        = 14

[watchdog]
enabled        = true
heartbeat_file = "${CONFIG_DIR}/heartbeat"
TOMLEOF

chown "$PICLAW_USER":"$PICLAW_USER" "$CONFIG_DIR/config.toml"
chmod 600 "$CONFIG_DIR/config.toml"
info "Konfiguration erstellt: $CONFIG_DIR/config.toml"
info "API-Token: ${API_TOKEN:0:12}… (vollständig: piclaw config token)"

# ── Watchdog-Konfiguration ────────────────────────────────────────
cat > "$CONFIG_DIR/watchdog.toml" << WDEOF
# PiClaw Watchdog-Konfiguration
# Separater Bot-Token (verschieden vom Haupt-Telegram-Bot!)
telegram_token   = ""    # ← AUSFÜLLEN: /newbot via @BotFather
telegram_chat_id = ""    # ← AUSFÜLLEN: deine Telegram User-ID

temp_warn_c  = 75
temp_crit_c  = 80
disk_warn_pct = 85
disk_crit_pct = 95
ram_warn_pct  = 90

check_interval_s  = 60
summary_hour      = 7
heartbeat_timeout = 90
WDEOF

chown "piclaw-watchdog":"piclaw-watchdog" "$CONFIG_DIR/watchdog.toml"
chmod 640 "$CONFIG_DIR/watchdog.toml"

# ── CLI-Tool einrichten ───────────────────────────────────────────
section "CLI-Tool einrichten"

cat > /usr/local/bin/piclaw << CLIEOF
#!/bin/bash
# PiClaw OS – CLI-Wrapper
export PICLAW_CONFIG_DIR="$CONFIG_DIR"
exec "$INSTALL_DIR/.venv/bin/python" -m piclaw.cli "\$@"
CLIEOF
chmod +x /usr/local/bin/piclaw
info "CLI: /usr/local/bin/piclaw"

# ── systemd Services ──────────────────────────────────────────────
section "systemd Services einrichten"

VENV="$INSTALL_DIR/.venv"

# piclaw-api.service
cat > /etc/systemd/system/piclaw-api.service << EOF
[Unit]
Description=PiClaw OS – REST API (Port 7842)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$PICLAW_USER
Group=$PICLAW_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/python -m piclaw.api
Restart=always
RestartSec=5
StandardOutput=append:$LOG_DIR/api.log
StandardError=append:$LOG_DIR/api.log
Environment=PICLAW_CONFIG_DIR=$CONFIG_DIR

[Install]
WantedBy=multi-user.target
EOF

# piclaw-agent.service
cat > /etc/systemd/system/piclaw-agent.service << EOF
[Unit]
Description=PiClaw OS – Background Agent Daemon
After=network-online.target piclaw-api.service
Wants=network-online.target

[Service]
Type=simple
User=$PICLAW_USER
Group=$PICLAW_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/python -m piclaw.daemon
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/agent.log
StandardError=append:$LOG_DIR/agent.log
Environment=PICLAW_CONFIG_DIR=$CONFIG_DIR

[Install]
WantedBy=multi-user.target
EOF

# piclaw-crawler.service
cat > /etc/systemd/system/piclaw-crawler.service << EOF
[Unit]
Description=PiClaw OS – Background Crawler
After=piclaw-agent.service

[Service]
Type=simple
User=$PICLAW_USER
Group=$PICLAW_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/python -m piclaw.agents.crawler
Restart=on-failure
RestartSec=30
StandardOutput=append:$LOG_DIR/crawler.log
StandardError=append:$LOG_DIR/crawler.log
Environment=PICLAW_CONFIG_DIR=$CONFIG_DIR

[Install]
WantedBy=multi-user.target
EOF

# piclaw-watchdog.service (eigener User!)
cat > /etc/systemd/system/piclaw-watchdog.service << EOF
[Unit]
Description=PiClaw OS – Hardware Watchdog (isolated)
After=piclaw-agent.service

[Service]
Type=simple
User=piclaw-watchdog
Group=piclaw-watchdog
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/python -m piclaw.agents.watchdog
Restart=always
RestartSec=30
StandardOutput=append:$LOG_DIR/watchdog.log
StandardError=append:$LOG_DIR/watchdog.log
Environment=PICLAW_CONFIG_DIR=$CONFIG_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable piclaw-api piclaw-agent piclaw-watchdog
info "Services registriert und aktiviert"

# ── Firewall (optional) ───────────────────────────────────────────
if command -v ufw &>/dev/null; then
    ufw allow 7842/tcp comment "PiClaw Web-UI" >/dev/null 2>&1 || true
    info "Firewall: Port 7842 geöffnet"
fi

# ── Abschluss-Wizard ──────────────────────────────────────────────
if [[ "$SKIP_WIZARD" != "true" ]]; then
    section "Ersteinrichtung"
    echo ""
    echo "  Installation abgeschlossen! Kurze Ersteinrichtung:"
    echo ""

    if [[ -z "$API_KEY" ]]; then
        prompt "LLM API-Key eingeben (Anthropic/OpenAI) oder Enter für lokal:"
        read -r entered_key
        if [[ -n "$entered_key" ]]; then
            # Detect provider
            if [[ "$entered_key" == sk-ant-* ]]; then
                PROV="anthropic"; MODEL="claude-sonnet-4-20250514"
            elif [[ "$entered_key" == sk-* ]]; then
                PROV="openai"; MODEL="gpt-4o"
            else
                PROV="anthropic"; MODEL="claude-sonnet-4-20250514"
            fi
            sed -i "s|api_key  = \"${API_KEY}\"|api_key  = \"${entered_key}\"|" "$CONFIG_DIR/config.toml"
            sed -i "s|backend  = \"local\"|backend  = \"${PROV}\"|" "$CONFIG_DIR/config.toml"
            sed -i "s|model    = \"phi3:mini\"|model    = \"${MODEL}\"|" "$CONFIG_DIR/config.toml"
            info "LLM: $PROV / $MODEL"
        else
            warn "Kein API-Key – lokales Modell (Phi-3 Mini)"
            warn "Installieren: piclaw model download"
        fi
    fi

    if [[ -z "$TELEGRAM_TOKEN" ]]; then
        prompt "Telegram Bot-Token (von @BotFather) oder Enter überspringen:"
        read -r tg_tok
        if [[ -n "$tg_tok" ]]; then
            prompt "Telegram Chat-ID (deine User-ID von @userinfobot):"
            read -r tg_chat
            sed -i "s|telegram_token   = \"\"|telegram_token   = \"${tg_tok}\"|" "$CONFIG_DIR/config.toml"
            sed -i "s|telegram_chat_id = \"\"|telegram_chat_id = \"${tg_chat}\"|" "$CONFIG_DIR/config.toml"
            info "Telegram konfiguriert"
        fi
    fi
fi

# ── Services starten ──────────────────────────────────────────────
section "Services starten"

systemctl start piclaw-api
sleep 2
systemctl start piclaw-agent
sleep 1
systemctl start piclaw-watchdog

API_UP=false
for i in {1..10}; do
    if curl -s http://localhost:7842/health &>/dev/null; then
        API_UP=true; break
    fi
    sleep 1
done

# ── Abschluss ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R}"
echo -e "${GREEN}${BOLD}  ✅ PiClaw OS v${PICLAW_VERSION} – Installation abgeschlossen!${R}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${R}"
echo ""

HOST=$(hostname -I | awk '{print $1}')
echo "  Web-UI:   http://${HOST}:7842"
echo "  API-Token: $(grep secret_key "$CONFIG_DIR/config.toml" | cut -d'"' -f2 | head -c 16)…"
echo ""
echo "  Befehle:"
echo "    piclaw              – Interaktiver AI-Agent"
echo "    piclaw setup        – Konfiguration anpassen"
echo "    piclaw doctor       – Systemstatus"
echo "    piclaw start/stop   – Services"
echo ""

if [[ "$API_UP" == "true" ]]; then
    echo -e "  ${GREEN}API läuft: http://${HOST}:7842/health${R}"
else
    echo -e "  ${YELLOW}API startet noch (kann 30–60s dauern)${R}"
    echo "  Logs: journalctl -u piclaw-api -f"
fi

if [[ -f "/boot/firmware/config.txt" ]]; then
    echo ""
    echo -e "  ${YELLOW}⚠️  I2C/SPI wurden aktiviert – Neustart empfohlen: sudo reboot${R}"
fi

echo ""
echo "  Dokumentation: $INSTALL_DIR/docs/"
echo "  Konfiguration: $CONFIG_DIR/config.toml"
echo ""
