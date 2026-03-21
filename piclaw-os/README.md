# PiClaw OS

**KI-Betriebssystem für den Raspberry Pi 5**

PiClaw OS verwandelt einen Raspberry Pi 5 in einen autonomen KI-Agenten namens **Dameon**. Er läuft vollständig lokal, unterstützt Cloud-APIs als optionale Backends und kann per Terminal, Telegram oder Web-Dashboard gesteuert werden.

---

## ✨ Features

- 🤖 **KI-Agent "Dameon"** – Natürlichsprachliche Steuerung des Pi
- 🛒 **Marketplace-Suche** – Kleinanzeigen.de mit PLZ und Radius
- 📡 **Multi-LLM-Router** – Automatisches Routing zwischen lokalen und Cloud-Modellen
- 🌡️ **Thermisches Routing** – Wechselt bei Überhitzung automatisch zum sparsamsten Modell
- 📱 **Telegram-Integration** – Nachrichten und Benachrichtigungen
- 🏠 **Home Assistant** – Smart Home Steuerung per Sprache
- 📊 **Web-Dashboard** – Systemstatus auf Port 7842
- 🔍 **Netzwerk-Monitoring** – Neue Geräte erkennen
- 🔧 **`piclaw debug`** – Integrierte Diagnose-Tools

---

## 🚀 Installation

### Online (empfohlen)

```bash
T="DEIN_GITHUB_TOKEN" && curl \
  -H "Authorization: token $T" \
  -H "Accept: application/vnd.github.v3.raw" \
  -sL "https://api.github.com/repos/RainbowLabsInc/PiClawOS/contents/piclaw-os/boot/piclaw/install.sh" \
  | sudo GITHUB_TOKEN="$T" bash
```

### Nach der Installation

```bash
piclaw setup    # LLM-Key, Telegram, Home Assistant konfigurieren
piclaw doctor   # Systemcheck
piclaw          # Chat starten
```

---

## 🔑 Unterstützte LLM-Provider

Key einfach eingeben – Provider wird automatisch erkannt:

| Key-Präfix | Provider | Standard-Modell |
|---|---|---|
| `sk-ant-` | Anthropic | Claude Sonnet 4 |
| `nvapi-` | NVIDIA NIM | Nemotron 70B |
| `AIza` | Google Gemini | Gemini 2.0 Flash |
| `fw-` | Fireworks AI | Llama 3.1 70B |
| `sk-` | OpenAI / Mistral | GPT-4o |
| *(leer)* | Lokal | Gemma 2B (offline) |

---

## 📋 Befehle

```
piclaw              Chat starten
piclaw setup        Konfiguration
piclaw doctor       Systemcheck
piclaw update       Software aktualisieren
piclaw debug        Diagnose-Scripts ausführen
piclaw status       Service-Status
piclaw model        Modell-Verwaltung
piclaw llm          LLM-Registry verwalten
piclaw briefing     Tagesbriefing generieren
```

---

## 🏗️ Architektur

```
piclaw-os/
├── piclaw/          # Python-Paket (Quellcode)
│   ├── agent.py     # Haupt-Agent (Dameon)
│   ├── api.py       # FastAPI REST + WebSocket
│   ├── cli.py       # Kommandozeile
│   ├── llm/         # Multi-LLM-Router
│   ├── agents/      # Sub-Agenten (Watchdog, Crawler, ...)
│   ├── memory/      # QMD Memory System
│   ├── tools/       # Marketplace, Shell, GPIO, ...
│   └── messaging/   # Telegram, Discord, ...
├── tests/           # Automatisierte Tests
│   └── debug/       # Diagnose-Scripts
├── boot/piclaw/     # Installer (SD-Karte)
└── docs/            # Handbücher DE + EN
```

---

## 📄 Lizenz

MIT – Rainbow Labs Inc.
