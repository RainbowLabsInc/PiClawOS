# 🐾 PiClaw OS

**KI-Betriebssystem für Raspberry Pi 5**

PiClaw OS verwandelt einen Raspberry Pi in einen autonomen KI-Assistenten. Der Agent läuft rund um die Uhr, verarbeitet Nachrichten über Telegram/Discord, steuert Smart-Home-Geräte (Home Assistant), durchsucht Marktplätze und überwacht die Hardware.

---

## Features

- **Multi-LLM-Routing** – Anthropic Claude, OpenAI, NVIDIA NIM, Google Gemini, Ollama, lokale Modelle (Gemma 2B, Phi-3, TinyLlama via llama.cpp)
- **Messaging** – Telegram, Discord, Threema, WhatsApp, MQTT
- **Home Assistant** – REST + WebSocket, 11 Tools, Echtzeit-Events
- **Marktplatz-Crawler** – Kleinanzeigen.de, eBay.de, Websuche (nur neue Inserate)
- **Proaktiver Agent** – Morgenbriefing, Abendcheck, Schwellwert-Monitoring
- **Hybrid-Memory (QMD)** – BM25 + Vektorsuche, persistente Fakten
- **Watchdog** – Dienst- und Hardware-Überwachung
- **Web-Dashboard** – 8 Tabs: Dashboard · Memory · Agenten · Soul · Hardware · Metriken · Kamera · Chat

---

## Schnellstart

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte ≥ 16 GB

### Installation

1. **`piclaw-sdcard.zip`** entpacken → `piclaw/` Ordner auf die `bootfs`-Partition der SD-Karte kopieren
2. `piclaw/piclaw.conf` öffnen → API-Key eintragen (optional)
3. SD-Karte einlegen, Pi starten, 60 Sekunden warten
4. SSH verbinden (–t Flag ist Pflicht!):
   ```bash
   ssh -t pi@piclaw.local
   ```
5. Installer starten:
   ```bash
   # Raspberry Pi 5:
   sudo bash /boot/firmware/piclaw/install.sh
   
   # Raspberry Pi 4:
   sudo bash /boot/piclaw/install.sh
   ```
6. Konfiguration via Wizard:
   ```bash
   piclaw setup
   ```

---

## Unterstützte LLM-Provider

| Provider | Key-Format |
|----------|-----------|
| Anthropic Claude | `sk-ant-...` |
| OpenAI GPT | `sk-...` |
| NVIDIA NIM | `nvapi-...` |
| Google Gemini | `AIza...` |
| Ollama (lokal) | kein Key |
| Gemma 2B / Phi-3 / TinyLlama | kein Key, offline |

---

## Lokale Modelle

```bash
piclaw model download              # Gemma 2B Q4 (Standard, ~1.6 GB)
piclaw model download phi3-mini-q4 # Phi-3 Mini (~2.2 GB)
piclaw model download tinyllama-q4 # TinyLlama (~0.7 GB, sehr schnell)
```

---

## CLI-Übersicht

```bash
piclaw              # Chat mit dem Agenten
piclaw setup        # Konfigurations-Wizard
piclaw doctor       # System-Healthcheck
piclaw start/stop   # Dienste steuern
piclaw model download [id]
piclaw briefing send morning
```

---

## Systemdienste

| Dienst | Funktion |
|--------|---------|
| `piclaw-api` | REST API + Web-Dashboard (Port 7842) |
| `piclaw-agent` | Haupt-Agent Daemon |
| `piclaw-watchdog` | Hardware-Überwachung |
| `piclaw-crawler` | Web-Crawler Sub-Agent |

---

## Version

**v0.13.3** – März 2026

Vollständiges Changelog: [CHANGELOG.md](CHANGELOG.md)  
Roadmap: [ROADMAP.md](ROADMAP.md)

---

## Lizenz

MIT License
