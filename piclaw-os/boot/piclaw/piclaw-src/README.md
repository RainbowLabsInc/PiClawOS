# 🦞 PiClaw OS

**Ein KI-Betriebssystem für den Raspberry Pi 5.**  
Flashen wie Raspberry Pi OS, per SSH einloggen, und mit einem Agenten sprechen, der das Gerät vollständig kontrolliert.

> **v0.9.0** – 81 Dateien · ~9.500 Zeilen · Multi-LLM-Routing · Soul · Sub-Agenten · Hardware-Layer · Sensor-Registry · Thermisches LLM-Routing

```
 ┌──────────────────────────────────────────────────────┐
 │                   PiClaw OS v0.9                     │
 │                                                      │
 │  SSH ──→ piclaw          ──→  KI-Agent               │
 │  Browser ──→ :7842       ──→  Dashboard + Chat       │
 │  Telegram/Discord        ──→  Messaging-Hub          │
 │                                                      │
 │  Der Agent kann:                                     │
 │  • Shell-Befehle ausführen (allowlisted)             │
 │  • GPIO / I2C / 1-Wire Sensoren auslesen             │
 │  • Temperatur überwachen & LLM-Routing anpassen      │
 │  • Sub-Agenten erstellen und schedulen               │
 │  • Sich selbst aktualisieren                         │
 │  • Über mehrere LLM-Backends routen                  │
 └──────────────────────────────────────────────────────┘
```

---

## ⚡ Schnellstart (empfohlen für alle Betriebssysteme)

**Kein Image-Build nötig.** Raspberry Pi OS flashen + PiClaw installieren.

```bash
# 1. Raspberry Pi OS Lite 64-bit flashen  →  https://www.raspberrypi.com/software/
# 2. SSH einloggen
ssh pi@raspberrypi.local
# 3. PiClaw installieren
curl -fsSL https://raw.githubusercontent.com/youruser/piclaw-os/main/install.sh | sudo bash
# 4. Einrichten
piclaw setup
# 5. Loslegen
piclaw
```

Web-UI: `http://piclaw.local:7842`

---

## 🏗 Image selbst bauen

Für ein vollständiges `.img`-File das direkt geflasht werden kann.

### Unter Windows

`debootstrap` läuft **nicht nativ auf Windows**. Es gibt zwei Wege:

| Weg | Aufwand | Voraussetzung |
|-----|:-------:|---|
| **Docker Desktop** | ⭐⭐ Empfohlen | Docker Desktop installiert |
| **WSL2** | ⭐⭐⭐ | Windows 10/11, anspruchsvoller |

**→ [Vollständige Windows-Anleitung](docs/windows-build.md)**

```powershell
# Kurzversion mit Docker Desktop (PowerShell):
git clone https://github.com/youruser/piclaw-os
cd piclaw-os
.\build\docker-build.ps1
# Ausgabe: piclaw-os-arm64.img  (→ mit Balena Etcher flashen)
```

### Unter Linux / macOS

```bash
sudo apt install debootstrap qemu-user-static binfmt-support \
                 parted dosfstools e2fsprogs kpartx rsync curl
sudo ./build/build.sh
# optional: sudo ./build/build.sh --output mein.img --size 8G
```

---

## 📁 Projektstruktur

```
piclaw-os/
├── install.sh                  ← Direktinstaller (kein Image-Build nötig)
├── pyproject.toml              ← Python-Paket v0.9.0
├── build/
│   ├── build.sh                ← Linux/macOS Image-Builder (debootstrap)
│   ├── docker-build.sh         ← Docker Image-Builder (Linux/macOS)
│   ├── docker-build.ps1        ← Docker Image-Builder (Windows PowerShell)
│   └── Dockerfile.builder      ← Docker Builder-Image
├── cloud-init/
│   ├── user-data.yml           ← ⚠ VOR DEM FLASHEN EDITIEREN
│   └── meta-data.yml
├── docs/
│   ├── windows-build.md        ← Windows-Bauanleitung (Docker + WSL2)
│   ├── api-auth.md
│   ├── subagents.md
│   ├── soul.md
│   ├── multi-llm.md
│   └── discord-setup.md
├── systemd/                    ← Service-Definitionen
├── tests/                      ← 87+ Tests
└── piclaw/
    ├── hardware/               ← Hardware-Layer (v0.9)
    │   ├── pi_info.py          ← vcgencmd, Throttle, Clocks, Voltages
    │   ├── i2c_scan.py         ← I2C Bus-Scanner (40+ Geräte erkannt)
    │   ├── sensors.py          ← Named Sensor Registry
    │   ├── thermal.py          ← Thermisches LLM-Routing
    │   └── tools.py            ← Agent-Tools
    ├── llm/                    ← Multi-LLM Routing + Classifier
    ├── memory/                 ← QMD Hybrid-Speicher
    ├── messaging/              ← Telegram/Discord/Threema/WhatsApp
    ├── agents/                 ← Sub-Agenten + Sandboxing + Watchdog
    └── tools/                  ← Shell, GPIO, Network, Services...
```

---

## 🔧 Konfiguration

```bash
# Nach der Installation:
piclaw setup                            # interaktiver Wizard
piclaw config set llm.api_key sk-ant-…  # LLM-Key direkt setzen
nano /etc/piclaw/config.toml            # alle Optionen
```

| Provider | Key-Format | Standard-Modell |
|----------|-----------|----------------|
| Anthropic | `sk-ant-…` | `claude-sonnet-4-20250514` |
| OpenAI | `sk-…` | `gpt-4o` |
| Ollama | – (lokal) | `llama3.2` |
| Phi-3 Mini | – (lokal) | Kein Key, ~4GB RAM |

---

## 🔌 Hardware-Layer

```
Agent-Befehl: "Füge DHT22 auf Pin 4 hinzu, nenn ihn balcony_temp"
             "Lies alle Sensoren aus"
             "Scanne den I2C Bus"
```

**Unterstützte Sensoren:** DHT22, DS18B20, BMP280/BME280, SHT40, BH1750,
ADS1115, INA219, HC-SR501 PIR, HC-SR04, GPIO Input

**Thermisches Routing:**

| Temp | Status | Lokales LLM |
|------|--------|------------|
| < 55°C | 🟢 Cool | ✅ Erlaubt |
| 55–70°C | 🟡 Warm | ✅ Erlaubt |
| 70–80°C | 🟠 Heiß | ⚡ Cloud bevorzugt |
| 80–85°C | 🔴 Kritisch | ❌ Deaktiviert |
| > 85°C | ⚠️ Notfall | ❌ + Alert |

---

## 💻 CLI

```bash
piclaw                  # KI-Agent (interaktiv)
piclaw setup            # Ersteinrichtung
piclaw doctor           # Systemdiagnose
piclaw soul edit        # Persönlichkeit bearbeiten
piclaw agent list       # Sub-Agenten verwalten
piclaw config token     # API-Token anzeigen
piclaw model download   # Phi-3 lokal installieren
piclaw start/stop       # Services
```

---

## 🔒 Sicherheit

- Alle API-Endpunkte per Bearer-Token geschützt (auto-generiert)
- Watchdog als isolierter System-User (`piclaw-watchdog`)
- Sub-Agenten sandbox: Tier-1-Tools (reboot, watchdog-stop etc.) immer gesperrt
- Tamper-proof Watchdog-Log (SQL-Trigger)

---

## 📖 Dokumentation

| Datei | Inhalt |
|-------|--------|
| [docs/windows-build.md](docs/windows-build.md) | **Image-Build auf Windows** |
| [docs/api-auth.md](docs/api-auth.md) | API-Authentifizierung |
| [docs/subagents.md](docs/subagents.md) | Sub-Agenten & Sandboxing |
| [docs/soul.md](docs/soul.md) | Soul-System |
| [docs/multi-llm.md](docs/multi-llm.md) | Multi-LLM Routing |
| [SNAPSHOT.md](SNAPSHOT.md) | Vollständige Architektur |
| [CHANGELOG.md](CHANGELOG.md) | Versionshistorie |

---

Lizenz: MIT
