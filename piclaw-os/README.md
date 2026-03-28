# 🐾 PiClaw OS

**KI-Betriebssystem für den Raspberry Pi 5**  
*v0.15.2 · März 2026*

PiClaw OS verwandelt einen Raspberry Pi 5 in einen autonomen KI-Agenten namens **Dameon**. Er läuft 24/7, überwacht Marktplätze, steuert Smart-Home-Geräte, reagiert auf Nachrichten und plant Aufgaben – alles natürlichsprachlich steuerbar per Terminal, Telegram oder Web-Dashboard.

---

## ✨ Features

| Feature | Beschreibung |
|---|---|
| 🤖 **KI-Agent „Dameon"** | Autonomer Agent mit persistenter Persönlichkeit (SOUL.md), Memory und natürlichsprachlicher Steuerung |
| 🧠 **Multi-LLM-Router** | Groq, NVIDIA NIM, Anthropic, OpenAI, Gemini, Mistral, Fireworks, Ollama, lokales GGUF – mit automatischem Fallback |
| 🌡️ **Thermisches Routing** | Wechselt bei Überhitzung automatisch auf sparsamere Cloud-Backends |
| 🛒 **Marketplace-Suche** | Kleinanzeigen.de, eBay.de, willhaben.at (🇦🇹) mit PLZ, Stadtname, Radius und Preisfilter |
| 👁️ **Sub-Agenten** | Autonome Hintergrund-Agenten mit Cron, Interval oder Continuous-Schedule |
| 📢 **Benachrichtigungen** | Sub-Agenten-Ergebnisse automatisch via Telegram/Discord |
| 📡 **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| 🏠 **Home Assistant** | REST + WebSocket, 11 Tools, Push-Events in Echtzeit |
| 🧠 **Hybrid Memory** | BM25 + Vektor-Suche (QMD), persistente Fakten über Gespräche hinweg |
| 🌐 **Web-Dashboard** | 8 Tabs: Dashboard · Memory · Sub-Agenten · Soul · Hardware · Metriken · Kamera · Chat |
| 📷 **Kamera** | Pi Camera v2/v3 + USB-Webcams, KI-Bildbeschreibung |
| 🔍 **Netzwerk-Monitoring** | Neue Geräte im LAN erkennen und per Telegram melden |
| 🔧 **Self-Update** | `piclaw update` – git pull + Service-Neustart |

---

## 🚀 Quick Start

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte ≥ 16 GB
- LLM API-Key (optional – lokale Modelle funktionieren offline)

### Installation

**Online (empfohlen):**
```bash
T="DEIN_GITHUB_TOKEN" && curl \
  -H "Authorization: token $T" \
  -H "Accept: application/vnd.github.v3.raw" \
  -sL "https://api.github.com/repos/RainbowLabsInc/PiClawOS/contents/piclaw-os/boot/piclaw/install.sh" \
  | sudo GITHUB_TOKEN="$T" bash
```

**Nach der Installation:**
```bash
piclaw setup    # LLM-Key, Telegram, Home Assistant konfigurieren
piclaw doctor   # Systemcheck – alle grün?
piclaw          # Chat starten
```

**Web-Dashboard öffnen:** `http://piclaw.local:7842`

---

## 🤖 Unterstützte LLM-Provider

Key eingeben – Provider wird automatisch erkannt:

| Key-Präfix | Provider | Empfohlenes Modell | Geschwindigkeit |
|---|---|---|---|
| `gsk_` | **Groq** | Kimi K2 / Llama 3.3 70B | ⚡ Sehr schnell |
| `nvapi-` | NVIDIA NIM | Kimi K2 / Llama 3.3 70B | 🔄 Gut |
| `sk-ant-` | Anthropic | Claude Sonnet 4 | 🔄 Gut |
| `AIza` | Google Gemini | Gemini 2.0 Flash | 🔄 Gut |
| `fw-` | Fireworks AI | Llama 3.1 70B | 🔄 Gut |
| `sk-` | OpenAI / Mistral | GPT-4o | 🔄 Gut |
| *(leer)* | Lokal / Ollama | Gemma 2B / Qwen 2.5 | 🐢 Offline |

### Multi-Backend-Betrieb
Mehrere Backends parallel konfigurieren – der Router wählt automatisch das beste:
```bash
piclaw llm list                          # Alle Backends anzeigen
piclaw llm add --name groq-primary ...   # Weiteres Backend hinzufügen
piclaw llm update groq-primary --priority 9  # Priorität setzen
piclaw llm test groq-primary             # Backend direkt testen
piclaw llm enable/disable <name>         # Backend aktivieren/deaktivieren
```

---

## 🛒 Marketplace-Suche

### Einmalige Suche
```
> Suche auf Kleinanzeigen nach einem Raspberry Pi 5 in Hamburg unter 80€
> Suche auf willhaben.at nach einem Roller in Graz
> Suche auf eBay und Kleinanzeigen nach einem Gartentisch in 21224 Umkreis 30km
```

Unterstützte Plattformen: **Kleinanzeigen.de · eBay.de · willhaben.at · Web**  
Standort-Erkennung: PLZ, Stadtname (40+ Städte DE/AT), Umkreis in km

### Automatisches Monitoring (nur neue Inserate)
```
> Überwache Kleinanzeigen auf neue Sonnenschirm-Anzeigen in 21224 Umkreis 20km, prüfe stündlich
> Beobachte eBay auf neue Raspberry Pi 5 Angebote unter 80€
```

Der Agent erstellt automatisch einen Sub-Agenten der nur bei neuen Inseraten benachrichtigt.

---

## 👁️ Sub-Agenten System

Autonome Hintergrund-Jobs die auf Schedule laufen und per Telegram berichten:

```
> Erstelle einen Agenten der täglich um 08:00 Uhr die CPU-Temperatur meldet
> Überwache mein Netzwerk auf neue Geräte
> Erstelle einen Agenten der stündlich mein GitHub-Repo auf neue Issues prüft
```

**Schedule-Formate:**
```
once                  – einmalig
interval:3600         – alle 60 Minuten
cron:0 8 * * *        – täglich um 08:00 (Cron-Syntax)
continuous            – Endlosschleife
```

**Verwaltung:**
```
> Zeig mir alle laufenden Agenten
> Führe den CronJob_0800 jetzt aus
> Stopp den Monitor_Netzwerk
> Lösche den SearchAssistant
```

---

## 🏠 Home Assistant

```
> Schalte das Wohnzimmerlicht aus
> Stelle den Thermostat auf 22°C
> Welche Geräte sind gerade eingeschaltet?
```

Push-Events (Bewegung, Türen, Rauchmelder, Wassersensor) werden automatisch per Telegram gesendet.

---

## 💻 CLI-Referenz

```bash
piclaw                    # Chat starten
piclaw setup              # Einrichtungsassistent
piclaw update             # Update via git pull + Neustart
piclaw doctor             # Vollständiger Systemcheck
piclaw debug              # Interaktives Diagnose-Menü
piclaw llm list           # LLM-Backends anzeigen
piclaw llm test <name>    # Backend direkt testen
piclaw soul show/edit     # Persönlichkeit anzeigen/bearbeiten
piclaw briefing send      # Tagesbriefing senden
piclaw messaging test     # Alle Messaging-Adapter testen
piclaw backup/restore     # Konfiguration sichern/wiederherstellen
piclaw camera snapshot    # Foto + KI-Beschreibung
```

---

## 🏗️ Architektur

```
┌─────────────────────────────────────────────────────────┐
│                    piclaw-api (Port 7842)                │
│          FastAPI · REST · WebSocket · Dashboard          │
└──────────────────────────┬──────────────────────────────┘
                           │ IPC (/etc/piclaw/ipc/)
┌──────────────────────────▼──────────────────────────────┐
│                   piclaw-agent (Daemon)                  │
│    Agent · Multi-LLM-Router · Memory · Sub-Runner       │
│                                                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐  │
│  │ Groq    │  │ NIM     │  │ Ollama  │  │ Lokal    │  │
│  │ (prio9) │  │ (prio7) │  │ (prio5) │  │ Gemma2B  │  │
│  └─────────┘  └─────────┘  └─────────┘  └──────────┘  │
└──────────────────────────────────────────────────────────┘
           │                              │
    Telegram/Discord               Home Assistant
```

```
piclaw-os/
├── piclaw/
│   ├── agent.py          # Haupt-Agent (Dameon)
│   ├── api.py            # FastAPI REST + WebSocket
│   ├── cli.py            # Kommandozeile
│   ├── daemon.py         # Service-Einstiegspunkt
│   ├── ipc.py            # IPC zwischen API und Daemon
│   ├── llm/              # Multi-LLM-Router + Registry
│   ├── agents/           # Sub-Agenten Runner + Registry
│   ├── memory/           # QMD Hybrid-Memory
│   ├── tools/            # Marketplace, Shell, GPIO, Netzwerk...
│   ├── messaging/        # Telegram, Discord, MQTT...
│   └── hardware/         # Thermal, GPIO, Sensoren, Kamera
├── systemd/              # Service-Definitionen
├── tests/debug/          # Diagnose-Scripts
└── docs/                 # Handbücher DE + EN
```

---

## 🛠️ Troubleshooting

```bash
piclaw doctor                              # Vollständiger Check
journalctl -u piclaw-agent -n 50           # Service-Logs
strings /var/log/piclaw/agent.log | tail   # Agent-Logs
piclaw llm test <name>                     # LLM-Backend testen
piclaw messaging test                      # Telegram/Discord testen
```

| Problem | Lösung |
|---|---|
| Agent antwortet nicht | `piclaw doctor` → LLM-Status prüfen |
| Telegram sendet nicht | `piclaw messaging test` |
| `piclaw update` fehlgeschlagen | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Sub-Agent startet nicht | Log prüfen: `strings /var/log/piclaw/agent.log \| grep <name>` |
| Willhaben zeigt falsche Orte | Stadtname oder PLZ in der Anfrage angeben |

---

## 🗺️ Roadmap

- **v0.16** – Emergency Shutdown via schaltbare Steckdose
- **v0.17** – fail2ban Integration (Brute-Force-Schutz)
- **v0.18** – Queue System (parallele CLI + Telegram Anfragen)
- **v0.19** – Willhaben Kategorie-Filter
- **v0.20** – Kamera-Tools vollständig integriert

---

## 📄 Lizenz

MIT – Rainbow Labs Inc.

---

## 🙏 Gebaut mit

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [Ollama](https://ollama.com) · [FastAPI](https://fastapi.tiangolo.com) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org) · [Scrapling](https://github.com/D4Vinci/Scrapling) · [croniter](https://github.com/pallets/croniter)
