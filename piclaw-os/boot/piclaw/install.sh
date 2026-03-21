#!/usr/bin/env bash
# ====================================================================
#  PiClaw OS - Boot-Partition Installer v0.11.0
#
#  Dieser Installer wird direkt von der SD-Karte ausgefuehrt.
#  Er liest piclaw.conf aus dem gleichen Ordner und installiert
#  PiClaw OS vollstaendig offline (kein Internet noetig).
#
#  Aufruf (nach SSH-Login):
#    sudo bash /boot/piclaw/install.sh
#
#  Pi 5 (anderer Boot-Pfad):
#    sudo bash /boot/firmware/piclaw/install.sh
# ====================================================================

set -euo pipefail

PICLAW_VERSION="0.13.3"

# --- Farben (SSH-sicher, deaktiviert wenn kein TTY) ----------------
if [ -t 1 ]; then
    BOLD="\e[1m"; GREEN="\e[32m"; CYAN="\e[36m"
    YELLOW="\e[33m"; RED="\e[31m"; GRAY="\e[90m"; R="\e[0m"
else
    BOLD=""; GREEN=""; CYAN=""; YELLOW=""; RED=""; GRAY=""; R=""
fi

ok()      { echo -e "${GREEN}[OK]${R} $*"; }
section() { echo -e "\n${CYAN}${BOLD}=== $* ===${R}"; }
warn()    { echo -e "${YELLOW}[!]${R} $*"; }
info()    { echo -e "${GRAY}    $*${R}"; }
die()     { echo -e "${RED}[FEHLER]${R} $*" >&2; exit 1; }
ask()     { echo -en "${BOLD}  > ${R}$* "; }

# ====================================================================
# SCHRITT 0: Dieses Skript lokalisieren + piclaw.conf einlesen
# ====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_FILE="$SCRIPT_DIR/piclaw.conf"
SRC_DIR="$SCRIPT_DIR/piclaw-src"

echo ""
echo -e "${CYAN}${BOLD}============================================${R}"
echo -e "${CYAN}${BOLD}  PiClaw OS v${PICLAW_VERSION} - Installer${R}"
echo -e "${CYAN}${BOLD}============================================${R}"
echo ""

# piclaw.conf einlesen
if [[ ! -f "$CONF_FILE" ]]; then
    die "piclaw.conf nicht gefunden in: $SCRIPT_DIR\nErwartet: $CONF_FILE"
fi

ok "Konfiguration gefunden: $CONF_FILE"

# Werte aus piclaw.conf parsen (einfaches KEY = "VALUE" Format)
_conf_get() {
    local key="$1"
    local default="${2:-}"
    local val
    val=$(grep -E "^${key}\s*=" "$CONF_FILE" 2>/dev/null \
          | sed 's/.*=\s*"\(.*\)".*/\1/' \
          | tail -1)
    echo "${val:-$default}"
}

PICLAW_LLM_KEY=$(_conf_get "PICLAW_LLM_KEY" "")
PICLAW_LLM_PROVIDER=$(_conf_get "PICLAW_LLM_PROVIDER" "auto")
PICLAW_LLM_MODEL=$(_conf_get "PICLAW_LLM_MODEL" "")
PICLAW_AGENT_NAME=$(_conf_get "PICLAW_AGENT_NAME" "PiClaw")
PICLAW_TELEGRAM_TOKEN=$(_conf_get "PICLAW_TELEGRAM_TOKEN" "")
PICLAW_TELEGRAM_CHAT_ID=$(_conf_get "PICLAW_TELEGRAM_CHAT_ID" "")
PICLAW_WIFI_SSID=$(_conf_get "PICLAW_WIFI_SSID" "")
PICLAW_WIFI_PASSWORD=$(_conf_get "PICLAW_WIFI_PASSWORD" "")
PICLAW_API_PORT=$(_conf_get "PICLAW_API_PORT" "7842")
PICLAW_HOSTNAME=$(_conf_get "PICLAW_HOSTNAME" "piclaw")
PICLAW_FAN_ENABLED=$(_conf_get "PICLAW_FAN_ENABLED" "false")
PICLAW_FAN_PIN=$(_conf_get "PICLAW_FAN_PIN" "14")
PICLAW_AUTO_UPDATE=$(_conf_get "PICLAW_AUTO_UPDATE" "false")

# Home Assistant
PICLAW_HA_URL=$(_conf_get "PICLAW_HA_URL" "")
PICLAW_HA_TOKEN=$(_conf_get "PICLAW_HA_TOKEN" "")
PICLAW_HA_NOTIFY=$(_conf_get "PICLAW_HA_NOTIFY_EVENTS" "motion_detected,door_opened,alarm_triggered,smoke_detected,flood_detected")

# LLM-Provider auto-erkennen
if [[ "$PICLAW_LLM_PROVIDER" == "auto" ]]; then
    if [[ "$PICLAW_LLM_KEY" == sk-ant-* ]]; then
        PICLAW_LLM_PROVIDER="anthropic"
        [[ -z "$PICLAW_LLM_MODEL" ]] && PICLAW_LLM_MODEL="claude-sonnet-4-20250514"
    elif [[ "$PICLAW_LLM_KEY" == sk-* ]]; then
        PICLAW_LLM_PROVIDER="openai"
        [[ -z "$PICLAW_LLM_MODEL" ]] && PICLAW_LLM_MODEL="gpt-4o"
    else
        PICLAW_LLM_PROVIDER="local"
        [[ -z "$PICLAW_LLM_MODEL" ]] && PICLAW_LLM_MODEL="gemma2b-q4"
    fi
fi

# Konfiguration anzeigen
echo ""
echo "  Konfiguration aus piclaw.conf:"
echo ""
printf "  %-22s %s\n" "Agent-Name:"    "$PICLAW_AGENT_NAME"
printf "  %-22s %s\n" "LLM-Anbieter:"  "$PICLAW_LLM_PROVIDER"
printf "  %-22s %s\n" "LLM-Modell:"    "$PICLAW_LLM_MODEL"
printf "  %-22s %s\n" "API-Key:"       "$([ -n "$PICLAW_LLM_KEY" ] && echo '***gesetzt***' || echo '(leer - lokales Modell)')"
printf "  %-22s %s\n" "Telegram:"      "$([ -n "$PICLAW_TELEGRAM_TOKEN" ] && echo 'konfiguriert' || echo 'nicht konfiguriert')"
printf "  %-22s %s\n" "Hostname:"      "$PICLAW_HOSTNAME"
printf "  %-22s %s\n" "Web-Port:"      "$PICLAW_API_PORT"
printf "  %-22s %s\n" "Home Assistant:" "$([ -n "$PICLAW_HA_URL" ] && echo "$PICLAW_HA_URL" || echo '(nicht konfiguriert)')"
echo ""

ask "Stimmt alles? Installation starten? [J/n]:"
read -r CONFIRM
if [[ "${CONFIRM,,}" == "n" ]]; then
    echo ""
    echo "  Abgebrochen. piclaw.conf bearbeiten und erneut ausfuehren."
    exit 0
fi

# ====================================================================
# SCHRITT 1: Voraussetzungen pruefen
# ====================================================================
section "Systemprueung"

[[ $EUID -ne 0 ]] && die "Bitte als root ausfuehren: sudo bash $0"

ARCH=$(uname -m)
[[ "$ARCH" != "aarch64" ]] && \
    die "Nur ARM64 (aarch64) unterstuetzt. Gefunden: $ARCH\nDieser Installer ist fuer den Raspberry Pi (arm64)."
ok "Architektur: $ARCH"

if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    ok "OS: $PRETTY_NAME"
    [[ "${ID:-}" != "debian" && "${ID_LIKE:-}" != *"debian"* ]] && \
        warn "Nicht Debian/RPi OS - koennte Probleme geben"
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MIN=$(echo "$PY_VER" | cut -d. -f2)
[[ "${PY_MIN:-0}" -lt 11 ]] && die "Python 3.11+ benoetigt, gefunden: $PY_VER. Bitte Raspberry Pi OS Bookworm (64-bit) verwenden." || ok "Python: $PY_VER (kompatibel)"

RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
[[ $RAM_MB -lt 2000 ]] && warn "Wenig RAM: ${RAM_MB}MB (lokales LLM benoetigt mind. 4GB)" || ok "RAM: ${RAM_MB}MB"

FREE_GB=$(df / | awk 'NR==2{print int($4/1024/1024)}')
[[ $FREE_GB -lt 4 ]] && warn "Wenig freier Speicher: ${FREE_GB}GB (mind. 8GB empfohlen)" || ok "Freier Speicher: ${FREE_GB}GB"

# ====================================================================
# SCHRITT 2: Hostname setzen
# ====================================================================
section "Hostname konfigurieren"

CURRENT_HOSTNAME=$(hostname)
if [[ "$CURRENT_HOSTNAME" != "$PICLAW_HOSTNAME" ]]; then
    hostnamectl set-hostname "$PICLAW_HOSTNAME" 2>/dev/null || \
        echo "$PICLAW_HOSTNAME" > /etc/hostname
    # /etc/hosts aktualisieren
    sed -i "s/127\.0\.1\.1.*/127.0.1.1\t$PICLAW_HOSTNAME/" /etc/hosts 2>/dev/null || true
    ok "Hostname: $CURRENT_HOSTNAME -> $PICLAW_HOSTNAME"
    info "Erreichbar nach Neustart als: ${PICLAW_HOSTNAME}.local"
else
    ok "Hostname bereits korrekt: $PICLAW_HOSTNAME"
fi

# ====================================================================
# SCHRITT 3: WLAN konfigurieren (falls in piclaw.conf eingetragen)
# ====================================================================
if [[ -n "$PICLAW_WIFI_SSID" ]]; then
    section "WLAN konfigurieren"
    info "SSID: $PICLAW_WIFI_SSID"

    if command -v nmcli &>/dev/null; then
        nmcli dev wifi connect "$PICLAW_WIFI_SSID" \
            password "$PICLAW_WIFI_PASSWORD" 2>/dev/null && \
            ok "WLAN verbunden: $PICLAW_WIFI_SSID" || \
            warn "WLAN-Verbindung fehlgeschlagen - manuell verbinden: nmcli dev wifi connect \"$PICLAW_WIFI_SSID\""
    elif [[ -f /etc/wpa_supplicant/wpa_supplicant.conf ]]; then
        # Fallback: wpa_supplicant
        cat >> /etc/wpa_supplicant/wpa_supplicant.conf << WPAEOF

network={
    ssid="$PICLAW_WIFI_SSID"
    psk="$PICLAW_WIFI_PASSWORD"
}
WPAEOF
        ok "WLAN-Konfiguration geschrieben (wpa_supplicant)"
        warn "Neustart erforderlich damit WLAN aktiv wird"
    else
        warn "Kein WLAN-Manager gefunden - WLAN manuell einrichten"
    fi
fi

# ====================================================================
# SCHRITT 4: Systemabhaengigkeiten installieren
# ====================================================================
section "Systemabhaengigkeiten installieren"

# Internet pruefen
INTERNET=false
if curl -s --max-time 5 https://pypi.org &>/dev/null; then
    INTERNET=true
    ok "Internet: erreichbar"
else
    warn "Kein Internet - nur Offline-Installation moeglich"
    if [[ ! -d "$SRC_DIR" ]]; then
        die "Kein Internet UND kein piclaw-src/ Ordner gefunden.\nBitte entweder:\n  a) Internetverbindung herstellen\n  b) piclaw-src/ Ordner neben install.sh legen"
    fi
fi

export DEBIAN_FRONTEND=noninteractive

PKGS_BASE=(
    python3 python3-pip python3-venv python3-dev
    sqlite3
    curl wget git
    network-manager
    i2c-tools
    avahi-daemon
    htop nano
    libssl-dev libffi-dev
)

PKGS_OPT=(
    nodejs npm        # QMD Memory Engine
    fswebcam          # USB-Webcam Support
    libcamera-apps    # Pi Camera Support
)

info "Installiere Basis-Pakete..."
apt-get update -qq 2>/dev/null
apt-get install -y -qq "${PKGS_BASE[@]}" 2>/dev/null
ok "Basis-Pakete installiert"

info "Installiere optionale Pakete..."
apt-get install -y -qq "${PKGS_OPT[@]}" 2>/dev/null || \
    warn "Einige optionale Pakete nicht verfuegbar (normal auf Lite-Image)"

# avahi-daemon fuer .local Hostname
systemctl enable avahi-daemon 2>/dev/null || true
systemctl start  avahi-daemon 2>/dev/null || true

# ====================================================================
# SCHRITT 5: PiClaw-Code installieren
# ====================================================================
section "PiClaw OS installieren"

INSTALL_DIR="/opt/piclaw"
CONFIG_DIR="/etc/piclaw"
LOG_DIR="/var/log/piclaw"
PICLAW_USER="piclaw"

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR" "$CONFIG_DIR/memory"

# System-User anlegen
if ! id "$PICLAW_USER" &>/dev/null; then
    useradd -r -s /bin/bash -d "$INSTALL_DIR" -m "$PICLAW_USER"
    usermod -aG gpio,i2c,spi,dialout,video,audio "$PICLAW_USER" 2>/dev/null || true
    ok "System-User '$PICLAW_USER' angelegt"
else
    ok "System-User '$PICLAW_USER' bereits vorhanden"
fi

# Watchdog-User (isoliert, kein Login)
if ! id "piclaw-watchdog" &>/dev/null; then
    useradd -r -s /bin/false -d /nonexistent "piclaw-watchdog"
    ok "User 'piclaw-watchdog' angelegt (isoliert)"
fi
# piclaw-watchdog braucht Gruppe piclaw fuer IPC-Verzeichnis (WAL-Dateien)
usermod -aG "$PICLAW_USER" "piclaw-watchdog" 2>/dev/null || true

# Code kopieren
if [[ -d "$SRC_DIR" ]]; then
    # Offline-Installation: aus piclaw-src/ Ordner auf der SD-Karte
    info "Installiere aus piclaw-src/ (offline)..."
    cp -r "$SRC_DIR"/. "$INSTALL_DIR/"
    # Installer-Skript soll nicht in /opt/piclaw landen
    rm -f "$INSTALL_DIR/install.sh"
    ok "Code aus SD-Karte kopiert: $SRC_DIR -> $INSTALL_DIR"
elif [[ "$INTERNET" == "true" ]]; then
    # Online-Installation: von GitHub klonen
    info "Klone Repository von GitHub..."
    REPO_URL="https://github.com/youruser/piclaw-os"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || \
        die "Repository-Klon fehlgeschlagen.\nBitte piclaw-src/ Ordner neben install.sh legen fuer Offline-Installation."
    ok "Code von GitHub geklont"
fi

chown -R "$PICLAW_USER":"$PICLAW_USER" "$INSTALL_DIR"

# Sicherstellen dass pyproject.toml aktuell ist
if [[ -f "$SCRIPT_DIR/piclaw-src/pyproject.toml" ]]; then
    cp "$SCRIPT_DIR/piclaw-src/pyproject.toml" "$INSTALL_DIR/pyproject.toml"
fi

# Python venv
info "Python-Umgebung einrichten..."
python3 -m venv "$INSTALL_DIR/.venv"
VENV="$INSTALL_DIR/.venv"

"$VENV/bin/pip" install --quiet --upgrade pip setuptools wheel 2>/dev/null

# Kernabhaengigkeiten (immer noetig)
"$VENV/bin/pip" install --quiet \
    "fastapi>=0.111" "uvicorn[standard]>=0.29" \
    "aiohttp>=3.9" "websockets>=12" \
    "psutil>=5.9" "tomli-w>=1.0" "croniter>=1.4" \
    "httpx" "rank_bm25" \
    2>/dev/null

# GPIO (nur Pi)
"$VENV/bin/pip" install --quiet \
    "RPi.GPIO>=0.7.1" "gpiozero>=2.0" "smbus2" \
    2>/dev/null || \
    warn "GPIO-Bibliotheken nicht installiert (nur auf echtem Pi noetig)"

# Messaging
"$VENV/bin/pip" install --quiet \
    "discord.py>=2.3" \
    "aiomqtt>=2.0" \
    2>/dev/null || true

# Threema Gateway (optional)
"$VENV/bin/pip" install --quiet \
    "threema.gateway[e2e]>=8.0" \
    2>/dev/null || true  # optional, teuer - nur wenn konfiguriert

# PiClaw-Paket selbst
if ! "$VENV/bin/pip" install -e "$INSTALL_DIR" 2>/tmp/piclaw_pip.log; then
    warn "piclaw pip-Installation fehlgeschlagen:"
    tail -5 /tmp/piclaw_pip.log | while read -r line; do warn "  $line"; done
    warn "Manuell beheben: sudo $VENV/bin/pip install -e $INSTALL_DIR"
else
    ok "piclaw Python-Paket installiert"
fi

# QMD (Hybrid Memory) - braucht nodejs
if command -v npm &>/dev/null && [[ "$INTERNET" == "true" ]]; then
    npm install -g @tobilu/qmd --silent 2>/dev/null && \
        ok "QMD Memory Engine installiert" || \
        warn "QMD nicht installiert - Memory-Funktionen eingeschraenkt"
fi

ok "PiClaw-Code installiert in $INSTALL_DIR"

# ====================================================================
# SCHRITT 6: Hardware-Interfaces aktivieren
# ====================================================================
section "Hardware aktivieren"

# Pi 5 nutzt /boot/firmware/, aeltere Pis /boot/
CONFIG_TXT=""
for p in /boot/firmware/config.txt /boot/config.txt; do
    [[ -f "$p" ]] && CONFIG_TXT="$p" && break
done

if [[ -n "$CONFIG_TXT" ]]; then
    CHANGED_HW=false
    if ! grep -q "dtparam=i2c_arm=on" "$CONFIG_TXT"; then
        echo ""                        >> "$CONFIG_TXT"
        echo "# PiClaw Hardware"       >> "$CONFIG_TXT"
        echo "dtparam=i2c_arm=on"      >> "$CONFIG_TXT"
        echo "dtparam=spi=on"          >> "$CONFIG_TXT"
        echo "dtoverlay=w1-gpio"       >> "$CONFIG_TXT"
        CHANGED_HW=true
    fi
    if [[ "$PICLAW_FAN_ENABLED" == "true" ]] && ! grep -q "dtoverlay=pwm" "$CONFIG_TXT"; then
        echo "dtoverlay=pwm,pin=${PICLAW_FAN_PIN},func=2" >> "$CONFIG_TXT"
        CHANGED_HW=true
    fi
    if [[ "$CHANGED_HW" == "true" ]]; then
        ok "I2C, SPI, 1-Wire in $CONFIG_TXT aktiviert"
    else
        ok "Hardware-Interfaces bereits konfiguriert"
    fi
else
    warn "config.txt nicht gefunden - I2C/SPI bitte manuell aktivieren"
fi

# ====================================================================
# SCHRITT 7: Konfigurationsdatei anlegen
# ====================================================================
section "PiClaw-Konfiguration schreiben"

API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

cat > "$CONFIG_DIR/config.toml" << TOMLEOF
# PiClaw OS v${PICLAW_VERSION} - Konfiguration
# Generiert: $(date)
# Bearbeiten: nano $CONFIG_DIR/config.toml
# Wizard:     piclaw setup

agent_name = "${PICLAW_AGENT_NAME}"
log_level  = "INFO"

[llm]
backend     = "${PICLAW_LLM_PROVIDER}"
model       = "${PICLAW_LLM_MODEL}"
api_key     = "${PICLAW_LLM_KEY}"
base_url    = ""
temperature = 0.7
max_tokens  = 4096
timeout     = 60

[api]
host       = "0.0.0.0"
port       = ${PICLAW_API_PORT}
secret_key = "${API_TOKEN}"

[telegram]
token   = "${PICLAW_TELEGRAM_TOKEN}"
chat_id = "${PICLAW_TELEGRAM_CHAT_ID}"

[discord]
token      = ""
channel_id = 0

[hardware]
fan_enabled = ${PICLAW_FAN_ENABLED}
fan_pin     = ${PICLAW_FAN_PIN}
fan_start_c = 50
fan_full_c  = 75

[updater]
auto_check = ${PICLAW_AUTO_UPDATE}
channel    = "stable"

[shell]
enabled = true
timeout = 30

[network]
managed = true

[gpio]
enabled = true

[homeassistant]
url              = "${PICLAW_HA_URL}"
token            = "${PICLAW_HA_TOKEN}"
verify_ssl       = false
notify_on_events = [$(echo "$PICLAW_HA_NOTIFY" | sed 's/,/","/g' | sed 's/^/"/' | sed 's/$/"/' )]
TOMLEOF

# Watchdog-Konfiguration
cat > "$CONFIG_DIR/watchdog.toml" << WDEOF
# PiClaw Watchdog-Konfiguration
# Separater Bot-Token (verschieden vom Haupt-Telegram-Bot!)
telegram_token   = ""
telegram_chat_id = ""

temp_warn_c       = 75
temp_crit_c       = 80
disk_warn_pct     = 85
disk_crit_pct     = 95
ram_warn_pct      = 90
check_interval_s  = 60
summary_hour      = 7
heartbeat_timeout = 90
WDEOF

chown "$PICLAW_USER":"$PICLAW_USER" "$CONFIG_DIR/config.toml"
chown "piclaw-watchdog":"piclaw-watchdog" "$CONFIG_DIR/watchdog.toml"
chmod 600 "$CONFIG_DIR/config.toml"
chmod 640 "$CONFIG_DIR/watchdog.toml"
chown -R "$PICLAW_USER":"$PICLAW_USER" "$CONFIG_DIR"
chown "piclaw-watchdog":"piclaw-watchdog" "$CONFIG_DIR/watchdog.toml"

# Watchdog-Log-Verzeichnis mit korrekten Rechten
mkdir -p "$CONFIG_DIR/logs/watchdog"
chown -R "piclaw-watchdog":"piclaw-watchdog" "$CONFIG_DIR/logs/watchdog"
chmod 750 "$CONFIG_DIR/logs/watchdog"

# IPC-Verzeichnis: piclaw schreibt jobs.db, piclaw-watchdog schreibt watchdog.db
# Gruppe "piclaw" für gemeinsamen Zugriff
mkdir -p "$CONFIG_DIR/ipc"
chown piclaw:piclaw "$CONFIG_DIR/ipc"
chmod 1777 "$CONFIG_DIR/ipc"  # sticky + alle schreiben
# Datenbankdateien voranlegen mit korrekten Rechten
touch "$CONFIG_DIR/ipc/jobs.db"
chown piclaw:piclaw "$CONFIG_DIR/ipc/jobs.db"
chmod 664 "$CONFIG_DIR/ipc/jobs.db"
touch "$CONFIG_DIR/ipc/watchdog.db"
chown piclaw-watchdog:piclaw-watchdog "$CONFIG_DIR/ipc/watchdog.db"
chmod 664 "$CONFIG_DIR/ipc/watchdog.db"

# Models-Verzeichnis sicherstellen
mkdir -p "$CONFIG_DIR/models"
chown -R "$PICLAW_USER":"$PICLAW_USER" "$CONFIG_DIR/models"
chmod 755 "$CONFIG_DIR/models"

ok "Konfiguration: $CONFIG_DIR/config.toml"

# ====================================================================
# SCHRITT 8: CLI-Wrapper anlegen
# ====================================================================
section "CLI-Tool einrichten"

cat > /usr/local/bin/piclaw << CLIEOF
#!/bin/bash
# PiClaw OS CLI-Wrapper
export PICLAW_CONFIG_DIR="${CONFIG_DIR}"
exec "${VENV}/bin/python" -m piclaw.cli "\$@"
CLIEOF
chmod +x /usr/local/bin/piclaw

# Shell-Alias fuer den Pi-Hauptnutzer
PI_USER=${SUDO_USER:-pi}
PI_HOME=$(getent passwd "$PI_USER" | cut -d: -f6 2>/dev/null || echo "/home/$PI_USER")
if [[ -d "$PI_HOME" ]]; then
    RC_FILE="$PI_HOME/.bashrc"
    if ! grep -q "piclaw" "$RC_FILE" 2>/dev/null; then
        cat >> "$RC_FILE" << ALIASEOF

# PiClaw OS
alias piclaw='piclaw'
echo "  PiClaw OS bereit. Tippe: piclaw"
ALIASEOF
    fi
fi

ok "CLI: /usr/local/bin/piclaw"

# ====================================================================
# SCHRITT 9: systemd Services einrichten
# ====================================================================
section "Services einrichten"

# piclaw-api
cat > /etc/systemd/system/piclaw-api.service << EOF
[Unit]
Description=PiClaw OS - REST API + Web-UI (Port ${PICLAW_API_PORT})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${PICLAW_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python -m piclaw.api
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/api.log
StandardError=append:${LOG_DIR}/api.log
Environment=PICLAW_CONFIG_DIR=${CONFIG_DIR}

[Install]
WantedBy=multi-user.target
EOF

# piclaw-agent
cat > /etc/systemd/system/piclaw-agent.service << EOF
[Unit]
Description=PiClaw OS - Background Agent Daemon
After=network-online.target piclaw-api.service

[Service]
Type=simple
User=${PICLAW_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python -m piclaw.daemon
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/agent.log
StandardError=append:${LOG_DIR}/agent.log
Environment=PICLAW_CONFIG_DIR=${CONFIG_DIR}

[Install]
WantedBy=multi-user.target
EOF

# piclaw-watchdog (isolierter User)
cat > /etc/systemd/system/piclaw-watchdog.service << EOF
[Unit]
Description=PiClaw OS - Hardware Watchdog
After=piclaw-agent.service

[Service]
Type=simple
User=piclaw-watchdog
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python -m piclaw.agents.watchdog
Restart=always
RestartSec=30
StandardOutput=append:${LOG_DIR}/watchdog.log
StandardError=append:${LOG_DIR}/watchdog.log
Environment=PICLAW_CONFIG_DIR=${CONFIG_DIR}

[Install]
WantedBy=multi-user.target
EOF

# piclaw-crawler (Web-Crawler Sub-Agent)
cat > /etc/systemd/system/piclaw-crawler.service << SVCEOF
[Unit]
Description=PiClaw OS - Web Crawler Agent
After=piclaw-agent.service

[Service]
Type=simple
User=${PICLAW_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python -m piclaw.agents.crawler
Restart=always
RestartSec=15
StandardOutput=append:${LOG_DIR}/crawler.log
StandardError=append:${LOG_DIR}/crawler.log
Environment=PICLAW_CONFIG_DIR=${CONFIG_DIR}

[Install]
WantedBy=multi-user.target
SVCEOF

# piclaw-qmd-update Timer (stündlich, niedrige Priorität)
cat > /etc/systemd/system/piclaw-qmd-update.service << SVCEOF
[Unit]
Description=PiClaw OS - QMD Memory Index Update

[Service]
Type=oneshot
User=${PICLAW_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/nice -n 19 ${VENV}/bin/python -m piclaw.memory.qmd_update
StandardOutput=append:${LOG_DIR}/qmd-update.log
StandardError=append:${LOG_DIR}/qmd-update.log
Environment=PICLAW_CONFIG_DIR=${CONFIG_DIR}
SVCEOF

cat > /etc/systemd/system/piclaw-qmd-update.timer << TMREOF
[Unit]
Description=PiClaw OS - QMD stündliches Update

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
TMREOF

# ── Sudoers: piclaw darf eigene Services neu starten ──────────────────
SUDOERS_FILE="/etc/sudoers.d/piclaw"
cat > "$SUDOERS_FILE" << 'SUDOEOF'
# PiClaw: allow piclaw user to restart its own services without password
piclaw ALL=(ALL) NOPASSWD: \
  /bin/systemctl restart piclaw-api, \
  /bin/systemctl restart piclaw-agent, \
  /bin/systemctl restart piclaw-watchdog, \
  /bin/systemctl restart piclaw-crawler, \
  /bin/systemctl stop piclaw-api, \
  /bin/systemctl stop piclaw-agent, \
  /bin/systemctl start piclaw-api, \
  /bin/systemctl start piclaw-agent
SUDOEOF
chmod 440 "$SUDOERS_FILE"
ok "Sudoers-Regel gesetzt: piclaw kann eigene Services neu starten"

systemctl daemon-reload
systemctl enable piclaw-api piclaw-agent piclaw-watchdog piclaw-crawler 2>/dev/null
systemctl enable piclaw-qmd-update.timer 2>/dev/null
ok "Services registriert: piclaw-api, piclaw-agent, piclaw-watchdog, piclaw-crawler"
ok "Timer registriert: piclaw-qmd-update.timer (stündlich)"  

# Firewall
if command -v ufw &>/dev/null; then
    ufw allow "${PICLAW_API_PORT}/tcp" comment "PiClaw Web-UI" >/dev/null 2>&1 || true
    ok "Firewall: Port ${PICLAW_API_PORT} geoeffnet"
fi

# ====================================================================
# SCHRITT 10: Services starten + Gesundheitscheck
# ====================================================================
section "Services starten"

systemctl start piclaw-api  2>/dev/null && ok "piclaw-api gestartet"  || warn "piclaw-api Start fehlgeschlagen"
sleep 3
systemctl start piclaw-agent 2>/dev/null && ok "piclaw-agent gestartet" || warn "piclaw-agent Start fehlgeschlagen"

# Health-Check
API_UP=false
echo -n "  Warte auf API"
for i in {1..30}; do
    echo -n "."
    if curl -s "http://localhost:${PICLAW_API_PORT}/health" &>/dev/null; then
        API_UP=true
        break
    fi
    sleep 2
done
echo ""

if [[ "$API_UP" == "true" ]]; then
    ok "API erreichbar: http://localhost:${PICLAW_API_PORT}/health"
else
    warn "API antwortet noch nicht (kann 30-60s dauern)"
    info "Logs pruefen: journalctl -u piclaw-api -n 20"
fi

# ====================================================================
# ABSCHLUSS
# ====================================================================

HOST_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "DEINE-IP")

# ── Lokales Modell herunterladen (vor Abschluss-Banner) ──────────────
if [[ -z "$PICLAW_LLM_KEY" && "$PICLAW_LLM_PROVIDER" == "local" ]]; then
    echo ""
    echo -e "  ${BOLD}Lokales LLM gewählt – Gemma 2B herunterladen? (Standard, empfohlen)${R}"
    echo -e "  ${GRAY}~1.6 GB, dauert 3–10 Minuten  (Phi-3: piclaw model download phi3-mini-q4)${R}"
    echo ""
    read -r -p "  Jetzt herunterladen? [J/n]: " DL_ANSWER
    DL_ANSWER="${DL_ANSWER:-j}"
    if [[ "${DL_ANSWER,,}" == "j" || "${DL_ANSWER,,}" == "y" ]]; then
        section "Gemma 2B herunterladen"
        if "$VENV/bin/piclaw" model download gemma2b-q4; then
            ok "Gemma 2B heruntergeladen"
        else
            warn "Download fehlgeschlagen – später manuell: piclaw model download"
        fi
    else
        info "Modell später herunterladen: piclaw model download  (~1.6 GB)"
    fi
    echo ""
fi

echo ""
echo -e "${GREEN}${BOLD}============================================${R}"
echo -e "${GREEN}${BOLD}  PiClaw OS ${PICLAW_VERSION} - Installation fertig!${R}"
echo -e "${GREEN}${BOLD}============================================${R}"
echo ""
echo "  Agent-Name:   ${PICLAW_AGENT_NAME}"
echo "  LLM:          ${PICLAW_LLM_PROVIDER} / ${PICLAW_LLM_MODEL}"
echo ""
echo "  Web-Dashboard:"
echo "    http://${HOST_IP}:${PICLAW_API_PORT}"
echo "    http://${PICLAW_HOSTNAME}.local:${PICLAW_API_PORT}"
echo ""
echo "  API-Token (erste 12 Zeichen):"
echo "    $(echo "$API_TOKEN" | head -c 12)..."
echo "    Vollstaendig: piclaw config token"
echo ""
echo -e "  ${BOLD}Naechste Schritte:${R}"
echo ""


echo "  1. Konfiguration verfeinern:"
echo "       piclaw setup"
echo ""
echo "  2. KI-Agent im Terminal starten:"
echo "       piclaw"
echo ""
echo "  3. Web-Dashboard im Browser oeffnen:"
echo "       http://${PICLAW_HOSTNAME}.local:${PICLAW_API_PORT}"
echo ""

# Neustart-Hinweis wenn Hardware-Config geaendert
if [[ -n "$CONFIG_TXT" ]]; then
    echo -e "  ${YELLOW}[!]${R} I2C/SPI wurden aktiviert."
    echo "      Bitte neu starten: sudo reboot"
    echo ""
fi

echo "  Viel Spass mit deinem KI-Pi!"
echo ""
