<div align="center">

# ð¾ PiClaw OS

**Dein autonomer KI-Assistent fÃ¼r den Raspberry Pi**

[![Version](https://img.shields.io/badge/version-0.17.0-blue?style=flat-square)](https://github.com/RainbowLabsInc/PiClawOS/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205-red?style=flat-square)](https://www.raspberrypi.com)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20PiClaw-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white)](https://ko-fi.com/rainbowlabsinc)

*LÃ¤uft 24/7 Â· Kein Abo Â· VollstÃ¤ndig offline-fÃ¤hig Â· Kostenlose LLM-APIs*

</div>

---

PiClaw OS verwandelt einen Raspberry Pi in einen intelligenten Assistenten, der rund um die Uhr fÃ¼r dich arbeitet: MarktplÃ¤tze Ã¼berwachen, Smart Home steuern, Netzwerk im Blick behalten â alles per Telegram, Discord, Browser-Dashboard oder weiteren Schnittstellen.

---

## â¨ Was kann PiClaw OS?

| | Feature | Beschreibung |
|---|---|---|
| ð§  | **Multi-LLM-Routing** | Groq, NVIDIA NIM, Cerebras, OpenRouter, Ollama, lokales Gemma 4 E2B â mit automatischer Fallback-Kette |
| ð | **LLM Autonomie** | Dameon findet und registriert **selbstÃ¤ndig** neue kostenlose LLM-Backends (`llm_discover`) |
| ð | **Marktplatz-Monitor** | Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion â meldet **nur neue** Inserate per Telegram |
| ðï¸ | **Auktions-Monitor** | Troostwijk + Zoll-Auktion: Events nach Land, Stadt oder **PLZ + Umkreis** Ã¼berwachen |
| ð¤ | **NatÃ¼rliche Sprache** | *âÃberwache eGun auf Sauer 505"* â erstellt automatisch einen stÃ¼ndlichen Monitor |
| ð¬ | **Messaging Hub** | Telegram, WhatsApp, Threema, MQTT |
| ð  | **Home Assistant** | REST + WebSocket, 11 Tools, Echtzeit-Push bei Bewegung/Alarm |
| ð | **Web-Dashboard** | Agents Â· Memory Â· Soul Â· Hardware Â· Metriken Â· Kamera Â· Chat |
| ð | **Tokenlos** | Marktplatz-Monitore laufen **ohne LLM-Aufrufe** â null API-Kosten im Betrieb |
| ð§ | **Self-Update** | `piclaw update` â Git-Pull + Neustart in einem Befehl |
| ð´ | **Offline-Fallback** | Gemma 4 E2B lÃ¤uft lokal auf dem Pi â kein Internet nÃ¶tig |

---

## ð Kostenlos betreiben

PiClaw OS funktioniert vollstÃ¤ndig mit kostenlosen API-Tiers:

| Anbieter | Free Tier | URL | Format |
|---|---|---|---|
| **Groq** â­ | Unbegrenzt (rate-limited) | [console.groq.com](https://console.groq.com) | `gsk_...` |
| **Cerebras** â­ | 8.000 Req/Tag, ultraschnell | [cloud.cerebras.ai](https://cloud.cerebras.ai) | `csk-...` |
| **NVIDIA NIM** | 1.000 Calls/Monat | [build.nvidia.com](https://build.nvidia.com) | `nvapi-...` |
| **OpenRouter** | Viele Modelle gratis | [openrouter.ai](https://openrouter.ai) | `sk-or-...` |
| **Lokal (Gemma 4 E2B)** | Kein Key nÃ¶tig | Im Paket enthalten | â |

> **Empfehlung:** Groq als Haupt-Backend + Cerebras als Fallback + lokales Gemma 4 E2B offline. `llm_discover` findet neue Backends automatisch.

---

## ð Installation

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte â¥ 16 GB

### In 3 Schritten

**1. Repository klonen**
```bash
git clone https://github.com/RainbowLabsInc/PiClawOS.git
cd PiClawOS/piclaw-os
sudo bash install.sh
```

**2. Einrichten**
```bash
piclaw setup
```
Der Wizard fÃ¼hrt durch: Agent-Name â LLM-Backend â Telegram â Home Assistant â Standort (fÃ¼r Zeitzone + Wetter)

**3. Dashboard Ã¶ffnen**
```
http://piclaw.local:7842
```

---

## ð Marktplatz-Monitor

### UnterstÃ¼tzte Plattformen

| Plattform | Typ | Land | Filter |
|---|---|---|---|
| ð Kleinanzeigen.de | Kleinanzeigen | ð©ðª | PLZ + Umkreis + Preis |
| ðï¸ eBay.de | Marktplatz | ð©ðª | PLZ + Preis |
| ð¯ eGun.de | Jagd / Outdoor | ð©ðª | Preis |
| ð¦ð¹ willhaben.at | Kleinanzeigen | ð¦ð¹ | Bundesland / Stadt |
| ð¨ Troostwijk (Lose) | Industrie-Auktionen | ð EU | Textsuche + Land |
| ðï¸ Troostwijk (Events) | Auktions-Events | ð EU | Land + Stadt + **PLZ + Radius** |
| âï¸ Zoll-Auktion.de | BehÃ¶rden-Versteigerungen | ð©ðª | **PLZ + Umkreis** + Preis |
| ð Websuche | DuckDuckGo-Fallback | Global | â |

### Beispiele

```
# Einmalige Suche
> Suche auf Kleinanzeigen nach Gartentisch in 21224, 20km
> Suche Land Rover auf der Zoll-Auktion

# Automatischer Monitor (stÃ¼ndlich, tokenlos)
> Ãberwache eGun auf Sauer 505
> Ãberwache Kleinanzeigen auf Sonnenschirm in 21224, 20km Umkreis
> Ãberwache Troostwijk auf neue Auktionen in Deutschland
> Ãberwache Troostwijk Auktionen im Umkreis von 100km um 21224
```

---

## ð¤ Sub-Agenten

Alle Marktplatz-Monitore laufen als **tokenlose Sub-Agenten** â kein LLM, keine API-Kosten:

| Agent | Plattform | Intervall | Token-Kosten |
|---|---|---|---|
| Monitor_Netzwerk | LAN-Scan | alle 5 Min | 0 (geschÃ¼tzt) |
| Monitor_Gartentisch | Kleinanzeigen | stÃ¼ndlich | 0 |
| Monitor_Sonnenschirm | Kleinanzeigen | stÃ¼ndlich | 0 |
| Monitor_Sauer505 | eGun | stÃ¼ndlich | 0 |
| Monitor_TW_Deutschland | Troostwijk Events | stÃ¼ndlich | 0 |
| Monitor_TW_PLZ21224_100km | Troostwijk Umkreis | stÃ¼ndlich | 0 |
| CronJob_0715 | Tagesbriefing | tÃ¤gl. 07:15 | ~500 |

---

## ð  Home Assistant

```
> Schalte das Licht im Fernsehzimmer an
> Wie warm ist es im Schlafzimmer?
> Was lÃ¤uft gerade im Wohnzimmer?
```

Push-Benachrichtigungen bei Bewegung, geÃ¶ffneten TÃ¼ren, Rauchmeldern und mehr.

---

## ð¤ LLM-Backends

PiClaw OS unterstÃ¼tzt **Multi-LLM-Routing** mit automatischer Fallback-Kette:

| Anbieter | Format | Kostenlos | Empfehlung |
|---|---|---|---|
| **Groq** | `gsk_...` | â | Haupt-Backend, schnellste Antworten |
| **Cerebras** | `csk-...` | â | Ultraschnell (>2000 Tok/s), Llama 3.3 70B |
| NVIDIA NIM | `nvapi-...` | â 1k/Monat | Fallback |
| OpenRouter | `sk-or-...` | â Viele | Aggregator |
| Anthropic | `sk-ant-...` | â | Premium-Alternative |
| Ollama | kein Key | â | Lokaler Server |
| **Gemma 4 E2B Q4** | kein Key | â | Offline-Fallback |

### ð LLM Autonomie (NEU in v0.17)

Dameon findet und registriert selbstÃ¤ndig neue kostenlose LLM-Backends:

```
> Finde neue LLM Backends
ð LLM Auto-Discovery gestartetâ¦
ð¡ Groq (Key vorhanden)
   â Alle freien Modelle bereits registriert
ð¡ NVIDIA NIM (Key vorhanden)
   â mixtral-8x7b-instruct â registriert als auto-nvidia-mixtral (561ms)
ð Cerebras â kein API-Key vorhanden
   â Anmeldung: https://cloud.cerebras.ai
ð Ergebnis: 1 neu registriert, 2 Provider verfÃ¼gbar
```

**Wie es funktioniert:**
- `llm_discover` scannt alle bekannten Free-Tier-Provider (Groq, NVIDIA, Cerebras, OpenRouter)
- Testet automatisch ungenutzte Modelle und registriert funktionierende
- LÃ¤uft auch **tÃ¤glich im Hintergrund** via Health Monitor (proaktive Discovery)
- Funktioniert **ohne LLM** (Regex-Shortcut) â genau dann wenn alle Cloud-Backends down sind
- 24 kostenlose Modelle in der Whitelist auf 4 Providern

---

## ð» CLI-Referenz

```bash
piclaw              # Chat starten
piclaw setup        # Einrichtungs-Wizard
piclaw update       # Aktualisieren (git pull + Neustart)
piclaw doctor       # System-Status prÃ¼fen
piclaw agent list   # Sub-Agenten anzeigen
piclaw llm list     # LLM-Backends anzeigen
piclaw soul edit    # PersÃ¶nlichkeit bearbeiten
piclaw backup       # Backup erstellen
```

---

## ð¡ï¸ Sicherheit

PiClaw OS wurde vor dem Release einem vollstÃ¤ndigen Security-Audit unterzogen. Alle kritischen Schwachstellen wurden behoben:

- â WhatsApp Webhook Auth-Bypass geschlossen
- â Firewall auf LAN-IPs eingeschrÃ¤nkt (nicht internet-weit)
- â GitHub-Token aus Prozessliste entfernt
- â CORS auf lokales Netzwerk beschrÃ¤nkt
- â Shell Command-Injection geblockt
- â Security-Header (X-Frame-Options, CSRF-Schutz)
- â Path-Traversal in `write_workspace_file` gefixt (v0.17)
- â IP-Validierung in Network-Security-Tools (v0.17)
- â Command-Injection in Updater via `shlex.quote` (v0.17)
- â Network-Tool komplett auf `subprocess_exec` umgestellt (v0.17)

Mehr Details: [SECURITY.md](SECURITY.md)

---

## ðºï¸ Roadmap

- **v0.17** â *Aktuell* â LLM Autonomie, Troostwijk Umkreis, Zoll-Auktion, Security-PRs
- **v0.18** â IPC-Reload (kein Neustart bei neuem Sub-Agent)
- **v0.19** â Marketplace: Query-Extraktion verbessern, Willhaben Kategorie-Filter
- **v1.0** â Frische Installation < 10 Minuten, alle Tests grÃ¼n

---

## ð ï¸ Troubleshooting

| Problem | LÃ¶sung |
|---|---|
| `piclaw update` hÃ¤ngt | `github_token` in `/etc/piclaw/config.toml` eintragen |
| `git pull: insufficient permission` | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Zeitzone falsch | `sudo timedatectl set-timezone Europe/Berlin` |
| Troostwijk 404 | BuildId veraltet â erneuert sich automatisch |
| Sub-Agent startet nicht | `piclaw agent list` + mission-JSON prÃ¼fen |
| Dameon antwortet nicht | `piclaw doctor` ausfÃ¼hren |

---

## â UnterstÃ¼tze PiClaw OS

<a href="https://ko-fi.com/rainbowlabsinc" target="_blank">
  <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi" height="36">
</a>

PiClaw OS ist ein Open-Source-Hobbyprojekt. Alle Spenden flieÃen direkt in die Weiterentwicklung â z.B. fÃ¼r neue Hardware wie einen **AI HAT+ 2**, SSDs, Sensoren oder TestgerÃ¤te. Jeder Beitrag hilft, das Projekt am Leben zu halten.

---

## ð Lizenz

MIT License â frei nutzbar, modifizierbar und verteilbar.

---

## ð Gebaut mit

[FastAPI](https://fastapi.tiangolo.com) Â· [aiohttp](https://docs.aiohttp.org) Â· [QMD](https://github.com/tobilu/qmd) Â· [python-telegram-bot](https://python-telegram-bot.org) Â· [Scrapling](https://github.com/D4Vinci/Scrapling) Â· [timezonefinder](https://github.com/jannikmi/timezonefinder) Â· [croniter](https://github.com/kiorky/croniter) Â· [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)

---

<div align="center">

**Made with â¤ï¸ for the Raspberry Pi community**

[Dokumentation](piclaw-os/README.md) Â· [Sicherheit](SECURITY.md) Â· [Changelog](piclaw-os/CHANGELOG.md) Â· [Roadmap](piclaw-os/ROADMAP.md) Â· [â Spenden](https://ko-fi.com/rainbowlabsinc)

</div>
