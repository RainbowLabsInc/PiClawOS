# Ã°ÂÂÂ¾ PiClaw OS

**KI-Betriebssystem fÃÂ¼r den Raspberry Pi 5**  
*v0.15.3 ÃÂ· MÃÂ¤rz 2026*

PiClaw OS verwandelt einen Raspberry Pi 5 in einen autonomen KI-Agenten namens **Dameon**. Er lÃÂ¤uft 24/7, ÃÂ¼berwacht MarktplÃÂ¤tze, steuert Smart-Home-GerÃÂ¤te, reagiert auf Nachrichten und plant Aufgaben Ã¢ÂÂ alles natÃÂ¼rlichsprachlich steuerbar per Terminal, Telegram oder Web-Dashboard.

---

## Ã¢ÂÂ¨ Features

| Feature | Beschreibung |
|---|---|
| Ã°ÂÂ¤Â **KI-Agent Ã¢ÂÂDameon"** | Autonomer Agent mit persistenter PersÃÂ¶nlichkeit (SOUL.md), Memory und natÃÂ¼rlichsprachlicher Steuerung |
| Ã°ÂÂ§Â  **Multi-LLM-Router** | Groq, NVIDIA NIM, Anthropic, OpenAI, Gemini, Mistral, Fireworks, lokales Gemma 4 E2B Ã¢ÂÂ mit automatischem Fallback |
| Ã°ÂÂÂ¡Ã¯Â¸Â **Thermisches Routing** | Wechselt bei ÃÂberhitzung automatisch auf sparsamere Cloud-Backends |
| Ã°ÂÂÂ **Marketplace-Suche** | Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion Ã¢ÂÂ mit PLZ, Stadtname, Radius und Preisfilter |
| Ã°ÂÂÂÃ¯Â¸Â **Sub-Agenten** | Autonome Hintergrund-Agenten mit Cron, Interval oder Continuous-Schedule |
| Ã¢ÂÂ¡ **Direct Tool Mode** | Sub-Agenten ohne LLM Ã¢ÂÂ 0 Token-Verbrauch bei Routine-Tasks (z.B. Netzwerk-Monitoring) |
| Ã°ÂÂÂ¦ **ClawHub Skills** | Skills von [clawhub.ai](https://clawhub.ai) mit einem Befehl installieren |
| Ã°ÂÂÂ¢ **Benachrichtigungen** | Sub-Agenten-Ergebnisse automatisch via Telegram |
| Ã°ÂÂÂ¡ **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| Ã°ÂÂÂ  **Home Assistant** | REST + WebSocket, 11 Tools, Push-Events in Echtzeit |
| Ã°ÂÂ§Â  **Hybrid Memory** | BM25 + Vektor-Suche (QMD), persistente Fakten ÃÂ¼ber GesprÃÂ¤che hinweg |
| Ã°ÂÂÂ **Web-Dashboard** | 8 Tabs: Dashboard ÃÂ· Memory ÃÂ· Sub-Agenten ÃÂ· Soul ÃÂ· Hardware ÃÂ· Metriken ÃÂ· Kamera ÃÂ· Chat |
| Ã°ÂÂÂ· **Kamera** | Pi Camera v2/v3 + USB-Webcams, KI-Bildbeschreibung |
| Ã°ÂÂÂ **Netzwerk-Monitoring** | Neue GerÃÂ¤te im LAN erkennen und per Telegram melden (LLM-frei) |
| Ã°ÂÂÂ§ **Self-Update** | `piclaw update` Ã¢ÂÂ git pull + Service-Neustart |

---

## Ã°ÂÂÂ Quick Start

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte Ã¢ÂÂ¥ 16 GB
- LLM API-Key (optional Ã¢ÂÂ lokale Modelle funktionieren offline)

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
piclaw doctor   # Systemcheck Ã¢ÂÂ alle grÃÂ¼n?
piclaw          # Chat starten
```

**Web-Dashboard ÃÂ¶ffnen:** `http://piclaw.local:7842`

---

## Ã°ÂÂ¤Â UnterstÃÂ¼tzte LLM-Provider

| Key-PrÃÂ¤fix | Provider | Empfohlenes Modell | Geschwindigkeit |
|---|---|---|---|
| `gsk_` | **Groq** | Kimi K2 / Llama 3.3 70B | Ã¢ÂÂ¡ Sehr schnell |
| `nvapi-` | NVIDIA NIM | Kimi K2 / Llama 3.3 70B | Ã°ÂÂÂ Gut |
| `sk-ant-` | Anthropic | Claude Sonnet 4 | Ã°ÂÂÂ Gut |
| `AIza` | Google Gemini | Gemini 2.0 Flash | Ã°ÂÂÂ Gut |
| `fw-` | Fireworks AI | Llama 3.1 70B | Ã°ÂÂÂ Gut |
| `sk-` | OpenAI / Mistral | GPT-4o | Ã°ÂÂÂ Gut |
| *(leer)* | Lokal (Gemma 4 E2B) | gemma-4-e2b-q4_k_m.gguf | 🐢 Offline-Fallback |

```bash
piclaw llm list                          # Alle Backends anzeigen
piclaw llm add --name groq-primary ...   # Backend hinzufÃÂ¼gen
piclaw llm update groq-primary --priority 9  # PrioritÃÂ¤t setzen
piclaw llm test groq-primary             # Backend testen
```

---

## Ã°ÂÂÂ¦ ClawHub Skills

Skills von [clawhub.ai](https://clawhub.ai) erweitern Dameons FÃÂ¤higkeiten ohne Code:

```bash
piclaw skill search calendar          # Skill suchen
piclaw skill info caldav-calendar     # Details anzeigen
piclaw skill install caldav-calendar  # Installieren
piclaw skill list                     # Alle installierten Skills
piclaw skill remove caldav-calendar   # Entfernen
```

Nach der Installation wird der SKILL.md-Inhalt automatisch in jeden Chat injiziert Ã¢ÂÂ Dameon kennt den Skill sofort.

**Via Telegram:**
```
> Installiere den CalDAV-Kalender Skill von ClawHub
```

Skills liegen in `/etc/piclaw/skills/<slug>/SKILL.md`.

---

## Ã°ÂÂÂ Marketplace-Suche

```
> Suche auf Kleinanzeigen nach einem Raspberry Pi 5 in Hamburg unter 80Ã¢ÂÂ¬
> Suche auf willhaben.at nach einem Roller in Graz
> ÃÂberwache Kleinanzeigen auf neue Sonnenschirm-Anzeigen in 21224 Umkreis 20km, prÃÂ¼fe stÃÂ¼ndlich
```

UnterstÃÂ¼tzte Plattformen: **Kleinanzeigen.de ÃÂ· eBay.de ÃÂ· willhaben.at ÃÂ· Web**  
Standort-Erkennung: PLZ, Stadtname (40+ StÃÂ¤dte DE/AT), Umkreis in km

---

## Ã°ÂÂÂÃ¯Â¸Â Sub-Agenten System

```
> Erstelle einen Agenten der tÃÂ¤glich um 08:00 die CPU-Temperatur meldet
> ÃÂberwache mein Netzwerk auf neue GerÃÂ¤te
```

**Schedule-Formate:**
```
once              Ã¢ÂÂ einmalig
interval:3600     Ã¢ÂÂ alle 60 Minuten
cron:0 8 * * *    Ã¢ÂÂ tÃÂ¤glich um 08:00
continuous        Ã¢ÂÂ Endlosschleife
```

**Ã¢ÂÂ¡ Direct Tool Mode** Ã¢ÂÂ fÃÂ¼r reine Monitoring-Tasks ohne LLM:

```
Monitor_Netzwerk: 288 Runs/Tag ÃÂ 0 LLM-Calls = 0 Token-Verbrauch
```

**Verwaltung:**
```
> Zeig mir alle laufenden Agenten
> FÃÂ¼hre den CronJob_0800 jetzt aus
> Stopp den Monitor_Netzwerk
```

---

## Ã°ÂÂÂ  Home Assistant

```
> Schalte das Wohnzimmerlicht aus
> Stelle den Thermostat auf 22ÃÂ°C
> Welche GerÃÂ¤te sind gerade eingeschaltet?
```

Push-Events (Bewegung, TÃÂ¼ren, Rauchmelder) werden automatisch per Telegram gesendet.

---

## Ã°ÂÂÂ» CLI-Referenz

```bash
piclaw                       # Chat starten
piclaw setup                 # Einrichtungsassistent
piclaw update                # Update via git pull + Neustart
piclaw doctor                # VollstÃÂ¤ndiger Systemcheck
piclaw briefing              # Aktuelles Briefing anzeigen
piclaw briefing send         # Briefing via Telegram senden
piclaw llm list              # LLM-Backends anzeigen
piclaw llm test <n>          # Backend direkt testen
piclaw soul show/edit        # PersÃÂ¶nlichkeit anzeigen/bearbeiten
piclaw skill install <slug>  # ClawHub-Skill installieren
piclaw skill list            # Installierte Skills anzeigen
piclaw skill search <query>  # Skills auf ClawHub suchen
piclaw skill remove <slug>   # Skill entfernen
piclaw messaging test        # Alle Adapter testen
piclaw backup/restore        # Konfiguration sichern/wiederherstellen
piclaw camera snapshot       # Foto + KI-Beschreibung
piclaw debug                 # Interaktives Diagnose-MenÃÂ¼
```

---

## Ã°ÂÂÂÃ¯Â¸Â Architektur

```
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
Ã¢ÂÂ                    piclaw-api (Port 7842)                Ã¢ÂÂ
Ã¢ÂÂ          FastAPI ÃÂ· REST ÃÂ· WebSocket ÃÂ· Dashboard          Ã¢ÂÂ
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ¬Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
                           Ã¢ÂÂ IPC (/etc/piclaw/ipc/)
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ¼Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
Ã¢ÂÂ                   piclaw-agent (Daemon)                  Ã¢ÂÂ
Ã¢ÂÂ    Agent ÃÂ· Multi-LLM-Router ÃÂ· Memory ÃÂ· Sub-Runner       Ã¢ÂÂ
Ã¢ÂÂ                                                          Ã¢ÂÂ
Ã¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂ
Ã¢ÂÂ  Ã¢ÂÂ Groq    Ã¢ÂÂ  Ã¢ÂÂ NIM     Ã¢ÂÂ  Ã¢ÂÂ Ollama  Ã¢ÂÂ  Ã¢ÂÂ Lokal    Ã¢ÂÂ  Ã¢ÂÂ
Ã¢ÂÂ  Ã¢ÂÂ (prio9) Ã¢ÂÂ  Ã¢ÂÂ (prio7) Ã¢ÂÂ  Ã¢ÂÂ (prio5) Ã¢ÂÂ  Ã¢ÂÂ Gemma2B  Ã¢ÂÂ  Ã¢ÂÂ
Ã¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ  Ã¢ÂÂ
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂÃ¢ÂÂ
           Ã¢ÂÂ                              Ã¢ÂÂ
    Telegram/Discord               Home Assistant
```

```
piclaw-os/
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ piclaw/
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ agent.py          # Haupt-Agent (Dameon)
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ api.py            # FastAPI REST + WebSocket
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ cli.py            # Kommandozeile
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ daemon.py         # Service-Einstiegspunkt
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ ipc.py            # IPC zwischen API und Daemon
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ soul.py           # PersÃÂ¶nlichkeit + ClawHub Skill-Injection
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ llm/              # Multi-LLM-Router + Registry
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ agents/           # Sub-Agenten Runner + Registry
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ memory/           # QMD Hybrid-Memory
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ tools/
Ã¢ÂÂ   Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ clawhub.py    # ClawHub Skill-Manager
Ã¢ÂÂ   Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ marketplace.py
Ã¢ÂÂ   Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ network_monitor.py
Ã¢ÂÂ   Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ network_security.py
Ã¢ÂÂ   Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ ...
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ messaging/        # Telegram, Discord, MQTT...
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ hardware/         # Thermal, GPIO, Sensoren, Kamera
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ systemd/              # Service-Definitionen
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ docs/                 # HandbÃÂ¼cher DE + EN
```

**Verzeichnisse auf dem Pi:**
```
/etc/piclaw/
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ config.toml           # Hauptkonfiguration
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ SOUL.md               # PersÃÂ¶nlichkeit von Dameon
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ subagents.json        # Sub-Agenten Registry
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ skills/               # Installierte ClawHub-Skills
Ã¢ÂÂ   Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ caldav-calendar/
Ã¢ÂÂ       Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ SKILL.md
Ã¢ÂÂ       Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ clawhub.json
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ models/               # Lokale GGUF-Modelle
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ memory/               # QMD Vektordatenbank
Ã¢ÂÂÃ¢ÂÂÃ¢ÂÂ ipc/                  # IPC-Trigger
```

---

## Ã°ÂÂÂ¡Ã¯Â¸Â Netzwerk-Sicherheit

```
> Scan das Netzwerk auf alle verbundenen GerÃÂ¤te
> Whois-Lookup fÃÂ¼r 185.220.101.5
> Blockiere die IP 185.220.101.5
> Deploye eine Labyrinth-Falle auf Port 2222
> Erstelle einen Abuse-Report fÃÂ¼r 185.220.101.5
```

**Honey Traps:**

| Typ | Beschreibung |
|---|---|
| `labyrinth` | Simuliert SSH-Session Ã¢ÂÂ hÃÂ¤lt Angreifer beschÃÂ¤ftigt |
| `rickroll` | HTTP-Redirect zu YouTube Ã¢ÂÂ fÃÂ¼r Web-Scanner |
| `sinkhole` | GefÃÂ¤lschte gzip-Daten Ã¢ÂÂ verwirrt automatisierte Tools |

> Ã¢ÂÂ Ã¯Â¸Â iptables-Befehle erfordern sudo. Lokale IPs (192.168.x.x) sind automatisch geschÃÂ¼tzt.

---

## Ã°ÂÂÂ Ã¯Â¸Â Troubleshooting

```bash
piclaw doctor                              # VollstÃÂ¤ndiger Check
journalctl -u piclaw-agent -n 50           # Service-Logs
strings /var/log/piclaw/agent.log | tail   # Agent-Logs
piclaw llm test <n>                        # LLM-Backend testen
```

| Problem | LÃÂ¶sung |
|---|---|
| Agent antwortet nicht | `piclaw doctor` Ã¢ÂÂ LLM-Status prÃÂ¼fen |
| Telegram sendet nicht | `piclaw messaging test` |
| `piclaw update` fehlgeschlagen | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Sub-Agent startet nicht | `strings /var/log/piclaw/agent.log \| grep <n>` |
| `piclaw skill install` Permission denied | `sudo chown -R piclaw:piclaw /etc/piclaw/skills` |
| Willhaben zeigt falsche Orte | Stadtname oder PLZ angeben |

---

## Ã°ÂÂÂºÃ¯Â¸Â Roadmap

| Version | Feature |
|---|---|
| v0.16 | Emergency Shutdown via schaltbare Steckdose |
| v0.17 | fail2ban Integration |
| v0.18 | Queue System (parallele CLI + Telegram Anfragen) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Kamera-Tools vollstÃÂ¤ndig integriert |
| **v1.0** | **Release** |
| v1.1 | Mehrsprachigkeit (DE / EN / ES) |

---

## Ã°ÂÂÂ Lizenz

MIT Ã¢ÂÂ Rainbow Labs Inc.

---

## Ã°ÂÂÂ Gebaut mit

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) ÃÂ· [Ollama](https://ollama.com) ÃÂ· [FastAPI](https://fastapi.tiangolo.com) ÃÂ· [QMD](https://github.com/tobilu/qmd) ÃÂ· [python-telegram-bot](https://python-telegram-bot.org) ÃÂ· [Scrapling](https://github.com/D4Vinci/Scrapling) ÃÂ· [croniter](https://github.com/pallets/croniter) ÃÂ· [ClawHub](https://clawhub.ai)
