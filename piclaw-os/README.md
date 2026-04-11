# ð¾ PiClaw OS

**KI-Betriebssystem fÃ¼r den Raspberry Pi 5**  
*v0.15.3 Â· MÃ¤rz 2026*

PiClaw OS verwandelt einen Raspberry Pi 5 in einen autonomen KI-Agenten namens **Dameon**. Er lÃ¤uft 24/7, Ã¼berwacht MarktplÃ¤tze, steuert Smart-Home-GerÃ¤te, reagiert auf Nachrichten und plant Aufgaben â alles natÃ¼rlichsprachlich steuerbar per Terminal, Telegram oder Web-Dashboard.

---

## â¨ Features

| Feature | Beschreibung |
|---|---|
| ð¤ **KI-Agent âDameon"** | Autonomer Agent mit persistenter PersÃ¶nlichkeit (SOUL.md), Memory und natÃ¼rlichsprachlicher Steuerung |
| ð§  **Multi-LLM-Router** | Groq, NVIDIA NIM, Anthropic, OpenAI, Gemini, Mistral, Fireworks, Ollama, lokales GGUF â mit automatischem Fallback |
| ð¡ï¸ **Thermisches Routing** | Wechselt bei Ãberhitzung automatisch auf sparsamere Cloud-Backends |
| ð **Marketplace-Suche** | Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion â mit PLZ, Stadtname, Radius und Preisfilter |
| ðï¸ **Sub-Agenten** | Autonome Hintergrund-Agenten mit Cron, Interval oder Continuous-Schedule |
| â¡ **Direct Tool Mode** | Sub-Agenten ohne LLM â 0 Token-Verbrauch bei Routine-Tasks (z.B. Netzwerk-Monitoring) |
| ð¦ **ClawHub Skills** | Skills von [clawhub.ai](https://clawhub.ai) mit einem Befehl installieren |
| ð¢ **Benachrichtigungen** | Sub-Agenten-Ergebnisse automatisch via Telegram |
| ð¡ **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| ð  **Home Assistant** | REST + WebSocket, 11 Tools, Push-Events in Echtzeit |
| ð§  **Hybrid Memory** | BM25 + Vektor-Suche (QMD), persistente Fakten Ã¼ber GesprÃ¤che hinweg |
| ð **Web-Dashboard** | 8 Tabs: Dashboard Â· Memory Â· Sub-Agenten Â· Soul Â· Hardware Â· Metriken Â· Kamera Â· Chat |
| ð· **Kamera** | Pi Camera v2/v3 + USB-Webcams, KI-Bildbeschreibung |
| ð **Netzwerk-Monitoring** | Neue GerÃ¤te im LAN erkennen und per Telegram melden (LLM-frei) |
| ð§ **Self-Update** | `piclaw update` â git pull + Service-Neustart |

---

## ð Quick Start

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte â¥ 16 GB
- LLM API-Key (optional â lokale Modelle funktionieren offline)

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
piclaw doctor   # Systemcheck â alle grÃ¼n?
piclaw          # Chat starten
```

**Web-Dashboard Ã¶ffnen:** `http://piclaw.local:7842`

---

## ð¤ UnterstÃ¼tzte LLM-Provider

| Key-PrÃ¤fix | Provider | Empfohlenes Modell | Geschwindigkeit |
|---|---|---|---|
| `gsk_` | **Groq** | Kimi K2 / Llama 3.3 70B | â¡ Sehr schnell |
| `nvapi-` | NVIDIA NIM | Kimi K2 / Llama 3.3 70B | ð Gut |
| `sk-ant-` | Anthropic | Claude Sonnet 4 | ð Gut |
| `AIza` | Google Gemini | Gemini 2.0 Flash | ð Gut |
| `fw-` | Fireworks AI | Llama 3.1 70B | ð Gut |
| `sk-` | OpenAI / Mistral | GPT-4o | ð Gut |
| *(leer)* | Lokal / Ollama | Gemma 4 E2B | 🐢 Offline |

```bash
piclaw llm list                          # Alle Backends anzeigen
piclaw llm add --name groq-primary ...   # Backend hinzufÃ¼gen
piclaw llm update groq-primary --priority 9  # PrioritÃ¤t setzen
piclaw llm test groq-primary             # Backend testen
```

---

## ð¦ ClawHub Skills

Skills von [clawhub.ai](https://clawhub.ai) erweitern Dameons FÃ¤higkeiten ohne Code:

```bash
piclaw skill search calendar          # Skill suchen
piclaw skill info caldav-calendar     # Details anzeigen
piclaw skill install caldav-calendar  # Installieren
piclaw skill list                     # Alle installierten Skills
piclaw skill remove caldav-calendar   # Entfernen
```

Nach der Installation wird der SKILL.md-Inhalt automatisch in jeden Chat injiziert â Dameon kennt den Skill sofort.

**Via Telegram:**
```
> Installiere den CalDAV-Kalender Skill von ClawHub
```

Skills liegen in `/etc/piclaw/skills/<slug>/SKILL.md`.

---

## ð Marketplace-Suche

```
> Suche auf Kleinanzeigen nach einem Raspberry Pi 5 in Hamburg unter 80â¬
> Suche auf willhaben.at nach einem Roller in Graz
> Ãberwache Kleinanzeigen auf neue Sonnenschirm-Anzeigen in 21224 Umkreis 20km, prÃ¼fe stÃ¼ndlich
```

UnterstÃ¼tzte Plattformen: **Kleinanzeigen.de Â· eBay.de Â· willhaben.at Â· Web**  
Standort-Erkennung: PLZ, Stadtname (40+ StÃ¤dte DE/AT), Umkreis in km

---

## ðï¸ Sub-Agenten System

```
> Erstelle einen Agenten der tÃ¤glich um 08:00 die CPU-Temperatur meldet
> Ãberwache mein Netzwerk auf neue GerÃ¤te
```

**Schedule-Formate:**
```
once              â einmalig
interval:3600     â alle 60 Minuten
cron:0 8 * * *    â tÃ¤glich um 08:00
continuous        â Endlosschleife
```

**â¡ Direct Tool Mode** â fÃ¼r reine Monitoring-Tasks ohne LLM:

```
Monitor_Netzwerk: 288 Runs/Tag Ã 0 LLM-Calls = 0 Token-Verbrauch
```

**Verwaltung:**
```
> Zeig mir alle laufenden Agenten
> FÃ¼hre den CronJob_0800 jetzt aus
> Stopp den Monitor_Netzwerk
```

---

## ð  Home Assistant

```
> Schalte das Wohnzimmerlicht aus
> Stelle den Thermostat auf 22Â°C
> Welche GerÃ¤te sind gerade eingeschaltet?
```

Push-Events (Bewegung, TÃ¼ren, Rauchmelder) werden automatisch per Telegram gesendet.

---

## ð» CLI-Referenz

```bash
piclaw                       # Chat starten
piclaw setup                 # Einrichtungsassistent
piclaw update                # Update via git pull + Neustart
piclaw doctor                # VollstÃ¤ndiger Systemcheck
piclaw briefing              # Aktuelles Briefing anzeigen
piclaw briefing send         # Briefing via Telegram senden
piclaw llm list              # LLM-Backends anzeigen
piclaw llm test <n>          # Backend direkt testen
piclaw soul show/edit        # PersÃ¶nlichkeit anzeigen/bearbeiten
piclaw skill install <slug>  # ClawHub-Skill installieren
piclaw skill list            # Installierte Skills anzeigen
piclaw skill search <query>  # Skills auf ClawHub suchen
piclaw skill remove <slug>   # Skill entfernen
piclaw messaging test        # Alle Adapter testen
piclaw backup/restore        # Konfiguration sichern/wiederherstellen
piclaw camera snapshot       # Foto + KI-Beschreibung
piclaw debug                 # Interaktives Diagnose-MenÃ¼
```

---

## ðï¸ Architektur

```
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â                    piclaw-api (Port 7842)                â
â          FastAPI Â· REST Â· WebSocket Â· Dashboard          â
ââââââââââââââââââââââââââââ¬âââââââââââââââââââââââââââââââ
                           â IPC (/etc/piclaw/ipc/)
ââââââââââââââââââââââââââââ¼âââââââââââââââââââââââââââââââ
â                   piclaw-agent (Daemon)                  â
â    Agent Â· Multi-LLM-Router Â· Memory Â· Sub-Runner       â
â                                                          â
â  âââââââââââ  âââââââââââ  âââââââââââ  ââââââââââââ  â
â  â Groq    â  â NIM     â  â Ollama  â  â Lokal    â  â
â  â (prio9) â  â (prio7) â  â (prio5) â  â Gemma2B  â  â
â  âââââââââââ  âââââââââââ  âââââââââââ  ââââââââââââ  â
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
           â                              â
    Telegram/Discord               Home Assistant
```

```
piclaw-os/
âââ piclaw/
â   âââ agent.py          # Haupt-Agent (Dameon)
â   âââ api.py            # FastAPI REST + WebSocket
â   âââ cli.py            # Kommandozeile
â   âââ daemon.py         # Service-Einstiegspunkt
â   âââ ipc.py            # IPC zwischen API und Daemon
â   âââ soul.py           # PersÃ¶nlichkeit + ClawHub Skill-Injection
â   âââ llm/              # Multi-LLM-Router + Registry
â   âââ agents/           # Sub-Agenten Runner + Registry
â   âââ memory/           # QMD Hybrid-Memory
â   âââ tools/
â   â   âââ clawhub.py    # ClawHub Skill-Manager
â   â   âââ marketplace.py
â   â   âââ network_monitor.py
â   â   âââ network_security.py
â   â   âââ ...
â   âââ messaging/        # Telegram, Discord, MQTT...
â   âââ hardware/         # Thermal, GPIO, Sensoren, Kamera
âââ systemd/              # Service-Definitionen
âââ docs/                 # HandbÃ¼cher DE + EN
```

**Verzeichnisse auf dem Pi:**
```
/etc/piclaw/
âââ config.toml           # Hauptkonfiguration
âââ SOUL.md               # PersÃ¶nlichkeit von Dameon
âââ subagents.json        # Sub-Agenten Registry
âââ skills/               # Installierte ClawHub-Skills
â   âââ caldav-calendar/
â       âââ SKILL.md
â       âââ clawhub.json
âââ models/               # Lokale GGUF-Modelle
âââ memory/               # QMD Vektordatenbank
âââ ipc/                  # IPC-Trigger
```

---

## ð¡ï¸ Netzwerk-Sicherheit

```
> Scan das Netzwerk auf alle verbundenen GerÃ¤te
> Whois-Lookup fÃ¼r 185.220.101.5
> Blockiere die IP 185.220.101.5
> Deploye eine Labyrinth-Falle auf Port 2222
> Erstelle einen Abuse-Report fÃ¼r 185.220.101.5
```

**Honey Traps:**

| Typ | Beschreibung |
|---|---|
| `labyrinth` | Simuliert SSH-Session â hÃ¤lt Angreifer beschÃ¤ftigt |
| `rickroll` | HTTP-Redirect zu YouTube â fÃ¼r Web-Scanner |
| `sinkhole` | GefÃ¤lschte gzip-Daten â verwirrt automatisierte Tools |

> â ï¸ iptables-Befehle erfordern sudo. Lokale IPs (192.168.x.x) sind automatisch geschÃ¼tzt.

---

## ð ï¸ Troubleshooting

```bash
piclaw doctor                              # VollstÃ¤ndiger Check
journalctl -u piclaw-agent -n 50           # Service-Logs
strings /var/log/piclaw/agent.log | tail   # Agent-Logs
piclaw llm test <n>                        # LLM-Backend testen
```

| Problem | LÃ¶sung |
|---|---|
| Agent antwortet nicht | `piclaw doctor` â LLM-Status prÃ¼fen |
| Telegram sendet nicht | `piclaw messaging test` |
| `piclaw update` fehlgeschlagen | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Sub-Agent startet nicht | `strings /var/log/piclaw/agent.log \| grep <n>` |
| `piclaw skill install` Permission denied | `sudo chown -R piclaw:piclaw /etc/piclaw/skills` |
| Willhaben zeigt falsche Orte | Stadtname oder PLZ angeben |

---

## ðºï¸ Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System (parallele CLI + Telegram Anfragen) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Kamera-Tools vollstÃ¤ndig integriert |
| **v1.0** | **Release** |
| v1.1 | Mehrsprachigkeit (DE / EN / ES) |

---

## ð Lizenz

MIT â Rainbow Labs Inc.

---

## ð Gebaut mit

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) Â· [Ollama](https://ollama.com) Â· [FastAPI](https://fastapi.tiangolo.com) Â· [QMD](https://github.com/tobilu/qmd) Â· [python-telegram-bot](https://python-telegram-bot.org) Â· [Scrapling](https://github.com/D4Vinci/Scrapling) Â· [croniter](https://github.com/pallets/croniter) Â· [ClawHub](https://clawhub.ai)
