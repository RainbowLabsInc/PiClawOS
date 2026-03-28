# 🐾 PiClaw OS

**KI-Betriebssystem für den Raspberry Pi 5**  
*v0.15.3 · März 2026*

PiClaw OS verwandelt einen Raspberry Pi 5 in einen autonomen KI-Agenten namens **Dameon**. Er läuft 24/7, überwacht Marktplätze, steuert Smart-Home-Geräte, reagiert auf Nachrichten und plant Aufgaben – alles natürlichsprachlich steuerbar per Terminal, Telegram oder Web-Dashboard.

---

## ✨ Features

| Feature | Beschreibung |
|---|---|
| 🤖 **KI-Agent „Dameon"** | Autonomer Agent mit persistenter Persönlichkeit (SOUL.md), Memory und natürlichsprachlicher Steuerung |
| 🧠 **Multi-LLM-Router** | Groq, NVIDIA NIM, Anthropic, OpenAI, Gemini, Mistral, Fireworks, Ollama, lokales GGUF – mit automatischem Fallback |
| 🌡️ **Thermisches Routing** | Wechselt bei Überhitzung automatisch auf sparsamere Cloud-Backends |
| 🛒 **Marketplace-Suche** | Kleinanzeigen.de, eBay.de, willhaben.at mit PLZ, Stadtname, Radius und Preisfilter |
| 👁️ **Sub-Agenten** | Autonome Hintergrund-Agenten mit Cron, Interval oder Continuous-Schedule |
| ⚡ **Direct Tool Mode** | Sub-Agenten ohne LLM – 0 Token-Verbrauch bei Routine-Tasks (z.B. Netzwerk-Monitoring) |
| 📦 **ClawHub Skills** | Skills von [clawhub.ai](https://clawhub.ai) mit einem Befehl installieren |
| 📢 **Benachrichtigungen** | Sub-Agenten-Ergebnisse automatisch via Telegram |
| 📡 **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| 🏠 **Home Assistant** | REST + WebSocket, 11 Tools, Push-Events in Echtzeit |
| 🧠 **Hybrid Memory** | BM25 + Vektor-Suche (QMD), persistente Fakten über Gespräche hinweg |
| 🌐 **Web-Dashboard** | 8 Tabs: Dashboard · Memory · Sub-Agenten · Soul · Hardware · Metriken · Kamera · Chat |
| 📷 **Kamera** | Pi Camera v2/v3 + USB-Webcams, KI-Bildbeschreibung |
| 🔍 **Netzwerk-Monitoring** | Neue Geräte im LAN erkennen und per Telegram melden (LLM-frei) |
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

| Key-Präfix | Provider | Empfohlenes Modell | Geschwindigkeit |
|---|---|---|---|
| `gsk_` | **Groq** | Kimi K2 / Llama 3.3 70B | ⚡ Sehr schnell |
| `nvapi-` | NVIDIA NIM | Kimi K2 / Llama 3.3 70B | 🔄 Gut |
| `sk-ant-` | Anthropic | Claude Sonnet 4 | 🔄 Gut |
| `AIza` | Google Gemini | Gemini 2.0 Flash | 🔄 Gut |
| `fw-` | Fireworks AI | Llama 3.1 70B | 🔄 Gut |
| `sk-` | OpenAI / Mistral | GPT-4o | 🔄 Gut |
| *(leer)* | Lokal / Ollama | Gemma 2B / Qwen 2.5 | 🐢 Offline |

```bash
piclaw llm list                          # Alle Backends anzeigen
piclaw llm add --name groq-primary ...   # Backend hinzufügen
piclaw llm update groq-primary --priority 9  # Priorität setzen
piclaw llm test groq-primary             # Backend testen
```

---

## 📦 ClawHub Skills

Skills von [clawhub.ai](https://clawhub.ai) erweitern Dameons Fähigkeiten ohne Code:

```bash
piclaw skill search calendar          # Skill suchen
piclaw skill info caldav-calendar     # Details anzeigen
piclaw skill install caldav-calendar  # Installieren
piclaw skill list                     # Alle installierten Skills
piclaw skill remove caldav-calendar   # Entfernen
```

Nach der Installation wird der SKILL.md-Inhalt automatisch in jeden Chat injiziert – Dameon kennt den Skill sofort.

**Via Telegram:**
```
> Installiere den CalDAV-Kalender Skill von ClawHub
```

Skills liegen in `/etc/piclaw/skills/<slug>/SKILL.md`.

---

## 🛒 Marketplace-Suche

```
> Suche auf Kleinanzeigen nach einem Raspberry Pi 5 in Hamburg unter 80€
> Suche auf willhaben.at nach einem Roller in Graz
> Überwache Kleinanzeigen auf neue Sonnenschirm-Anzeigen in 21224 Umkreis 20km, prüfe stündlich
```

Unterstützte Plattformen: **Kleinanzeigen.de · eBay.de · willhaben.at · Web**  
Standort-Erkennung: PLZ, Stadtname (40+ Städte DE/AT), Umkreis in km

---

## 👁️ Sub-Agenten System

```
> Erstelle einen Agenten der täglich um 08:00 die CPU-Temperatur meldet
> Überwache mein Netzwerk auf neue Geräte
```

**Schedule-Formate:**
```
once              – einmalig
interval:3600     – alle 60 Minuten
cron:0 8 * * *    – täglich um 08:00
continuous        – Endlosschleife
```

**⚡ Direct Tool Mode** – für reine Monitoring-Tasks ohne LLM:

```
Monitor_Netzwerk: 288 Runs/Tag × 0 LLM-Calls = 0 Token-Verbrauch
```

**Verwaltung:**
```
> Zeig mir alle laufenden Agenten
> Führe den CronJob_0800 jetzt aus
> Stopp den Monitor_Netzwerk
```

---

## 🏠 Home Assistant

```
> Schalte das Wohnzimmerlicht aus
> Stelle den Thermostat auf 22°C
> Welche Geräte sind gerade eingeschaltet?
```

Push-Events (Bewegung, Türen, Rauchmelder) werden automatisch per Telegram gesendet.

---

## 💻 CLI-Referenz

```bash
piclaw                       # Chat starten
piclaw setup                 # Einrichtungsassistent
piclaw update                # Update via git pull + Neustart
piclaw doctor                # Vollständiger Systemcheck
piclaw briefing              # Aktuelles Briefing anzeigen
piclaw briefing send         # Briefing via Telegram senden
piclaw llm list              # LLM-Backends anzeigen
piclaw llm test <n>          # Backend direkt testen
piclaw soul show/edit        # Persönlichkeit anzeigen/bearbeiten
piclaw skill install <slug>  # ClawHub-Skill installieren
piclaw skill list            # Installierte Skills anzeigen
piclaw skill search <query>  # Skills auf ClawHub suchen
piclaw skill remove <slug>   # Skill entfernen
piclaw messaging test        # Alle Adapter testen
piclaw backup/restore        # Konfiguration sichern/wiederherstellen
piclaw camera snapshot       # Foto + KI-Beschreibung
piclaw debug                 # Interaktives Diagnose-Menü
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
│   ├── soul.py           # Persönlichkeit + ClawHub Skill-Injection
│   ├── llm/              # Multi-LLM-Router + Registry
│   ├── agents/           # Sub-Agenten Runner + Registry
│   ├── memory/           # QMD Hybrid-Memory
│   ├── tools/
│   │   ├── clawhub.py    # ClawHub Skill-Manager
│   │   ├── marketplace.py
│   │   ├── network_monitor.py
│   │   ├── network_security.py
│   │   └── ...
│   ├── messaging/        # Telegram, Discord, MQTT...
│   └── hardware/         # Thermal, GPIO, Sensoren, Kamera
├── systemd/              # Service-Definitionen
└── docs/                 # Handbücher DE + EN
```

**Verzeichnisse auf dem Pi:**
```
/etc/piclaw/
├── config.toml           # Hauptkonfiguration
├── SOUL.md               # Persönlichkeit von Dameon
├── subagents.json        # Sub-Agenten Registry
├── skills/               # Installierte ClawHub-Skills
│   └── caldav-calendar/
│       ├── SKILL.md
│       └── clawhub.json
├── models/               # Lokale GGUF-Modelle
├── memory/               # QMD Vektordatenbank
└── ipc/                  # IPC-Trigger
```

---

## 🛡️ Netzwerk-Sicherheit

```
> Scan das Netzwerk auf alle verbundenen Geräte
> Whois-Lookup für 185.220.101.5
> Blockiere die IP 185.220.101.5
> Deploye eine Labyrinth-Falle auf Port 2222
> Erstelle einen Abuse-Report für 185.220.101.5
```

**Honey Traps:**

| Typ | Beschreibung |
|---|---|
| `labyrinth` | Simuliert SSH-Session – hält Angreifer beschäftigt |
| `rickroll` | HTTP-Redirect zu YouTube – für Web-Scanner |
| `sinkhole` | Gefälschte gzip-Daten – verwirrt automatisierte Tools |

> ⚠️ iptables-Befehle erfordern sudo. Lokale IPs (192.168.x.x) sind automatisch geschützt.

---

## 🛠️ Troubleshooting

```bash
piclaw doctor                              # Vollständiger Check
journalctl -u piclaw-agent -n 50           # Service-Logs
strings /var/log/piclaw/agent.log | tail   # Agent-Logs
piclaw llm test <n>                        # LLM-Backend testen
```

| Problem | Lösung |
|---|---|
| Agent antwortet nicht | `piclaw doctor` → LLM-Status prüfen |
| Telegram sendet nicht | `piclaw messaging test` |
| `piclaw update` fehlgeschlagen | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Sub-Agent startet nicht | `strings /var/log/piclaw/agent.log \| grep <n>` |
| `piclaw skill install` Permission denied | `sudo chown -R piclaw:piclaw /etc/piclaw/skills` |
| Willhaben zeigt falsche Orte | Stadtname oder PLZ angeben |

---

## 🗺️ Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System (parallele CLI + Telegram Anfragen) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Kamera-Tools vollständig integriert |
| **v1.0** | **Release** |
| v1.1 | Mehrsprachigkeit (DE / EN / ES) |

---

## 📄 Lizenz

MIT – Rainbow Labs Inc.

---

## 🙏 Gebaut mit

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [Ollama](https://ollama.com) · [FastAPI](https://fastapi.tiangolo.com) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org) · [Scrapling](https://github.com/D4Vinci/Scrapling) · [croniter](https://github.com/pallets/croniter) · [ClawHub](https://clawhub.ai)
