<div align="center">

# Ã°ÂÂÂ¾ PiClaw OS

**Dein autonomer KI-Assistent fÃÂ¼r den Raspberry Pi**

[![Version](https://img.shields.io/badge/version-0.17.0-blue?style=flat-square)](https://github.com/RainbowLabsInc/PiClawOS/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205-red?style=flat-square)](https://www.raspberrypi.com)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20PiClaw-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white)](https://ko-fi.com/rainbowlabsinc)

*LÃÂ¤uft 24/7 ÃÂ· Kein Abo ÃÂ· VollstÃÂ¤ndig offline-fÃÂ¤hig ÃÂ· Kostenlose LLM-APIs*

</div>

---

PiClaw OS verwandelt einen Raspberry Pi in einen intelligenten Assistenten, der rund um die Uhr fÃÂ¼r dich arbeitet: MarktplÃÂ¤tze ÃÂ¼berwachen, Smart Home steuern, Netzwerk im Blick behalten Ã¢ÂÂ alles per Telegram, Discord, Browser-Dashboard oder weiteren Schnittstellen.

---

## Ã¢ÂÂ¨ Was kann PiClaw OS?

| | Feature | Beschreibung |
|---|---|---|
| Ã°ÂÂ§Â  | **Multi-LLM-Routing** | Groq, NVIDIA NIM, Cerebras, OpenRouter, lokales Gemma 4 E2B Ã¢ÂÂ mit automatischer Fallback-Kette |
| Ã°ÂÂÂ | **LLM Autonomie** | Dameon findet und registriert **selbstÃÂ¤ndig** neue kostenlose LLM-Backends (`llm_discover`) |
| Ã°ÂÂÂ | **Marktplatz-Monitor** | Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion Ã¢ÂÂ meldet **nur neue** Inserate per Telegram |
| Ã°ÂÂÂÃ¯Â¸Â | **Auktions-Monitor** | Troostwijk + Zoll-Auktion: Events nach Land, Stadt oder **PLZ + Umkreis** ÃÂ¼berwachen |
| Ã°ÂÂ¤Â | **NatÃÂ¼rliche Sprache** | *Ã¢ÂÂÃÂberwache eGun auf Sauer 505"* Ã¢ÂÂ erstellt automatisch einen stÃÂ¼ndlichen Monitor |
| Ã°ÂÂÂ¬ | **Messaging Hub** | Telegram, WhatsApp, Threema, MQTT |
| Ã°ÂÂÂ  | **Home Assistant** | REST + WebSocket, 11 Tools, Echtzeit-Push bei Bewegung/Alarm |
| Ã°ÂÂÂ | **Web-Dashboard** | Agents ÃÂ· Memory ÃÂ· Soul ÃÂ· Hardware ÃÂ· Metriken ÃÂ· Kamera ÃÂ· Chat |
| Ã°ÂÂÂ | **Tokenlos** | Marktplatz-Monitore laufen **ohne LLM-Aufrufe** Ã¢ÂÂ null API-Kosten im Betrieb |
| Ã°ÂÂÂ§ | **Self-Update** | `piclaw update` Ã¢ÂÂ Git-Pull + Neustart in einem Befehl |
| Ã°ÂÂÂ´ | **Offline-Fallback** | Gemma 4 E2B lÃÂ¤uft lokal auf dem Pi Ã¢ÂÂ kein Internet nÃÂ¶tig |

---

## Ã°ÂÂÂ Kostenlos betreiben

PiClaw OS funktioniert vollstÃÂ¤ndig mit kostenlosen API-Tiers:

| Anbieter | Free Tier | URL | Format |
|---|---|---|---|
| **Groq** Ã¢Â­Â | Unbegrenzt (rate-limited) | [console.groq.com](https://console.groq.com) | `gsk_...` |
| **Cerebras** Ã¢Â­Â | 8.000 Req/Tag, ultraschnell | [cloud.cerebras.ai](https://cloud.cerebras.ai) | `csk-...` |
| **NVIDIA NIM** | 1.000 Calls/Monat | [build.nvidia.com](https://build.nvidia.com) | `nvapi-...` |
| **OpenRouter** | Viele Modelle gratis | [openrouter.ai](https://openrouter.ai) | `sk-or-...` |
| **Lokal (Gemma 4 E2B)** | Kein Key nÃÂ¶tig | Im Paket enthalten | Ã¢ÂÂ |

> **Empfehlung:** Groq als Haupt-Backend + Cerebras als Fallback + lokales Gemma 4 E2B offline. `llm_discover` findet neue Backends automatisch.

---

## Ã°ÂÂÂ Installation

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte Ã¢ÂÂ¥ 16 GB

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
Der Wizard fÃÂ¼hrt durch: Agent-Name Ã¢ÂÂ LLM-Backend Ã¢ÂÂ Telegram Ã¢ÂÂ Home Assistant Ã¢ÂÂ Standort (fÃÂ¼r Zeitzone + Wetter)

**3. Dashboard ÃÂ¶ffnen**
```
http://piclaw.local:7842
```

---

## Ã°ÂÂÂ Marktplatz-Monitor

### UnterstÃÂ¼tzte Plattformen

| Plattform | Typ | Land | Filter |
|---|---|---|---|
| Ã°ÂÂÂ Kleinanzeigen.de | Kleinanzeigen | Ã°ÂÂÂ©Ã°ÂÂÂª | PLZ + Umkreis + Preis |
| Ã°ÂÂÂÃ¯Â¸Â eBay.de | Marktplatz | Ã°ÂÂÂ©Ã°ÂÂÂª | PLZ + Preis |
| Ã°ÂÂÂ¯ eGun.de | Jagd / Outdoor | Ã°ÂÂÂ©Ã°ÂÂÂª | Preis |
| Ã°ÂÂÂ¦Ã°ÂÂÂ¹ willhaben.at | Kleinanzeigen | Ã°ÂÂÂ¦Ã°ÂÂÂ¹ | Bundesland / Stadt |
| Ã°ÂÂÂ¨ Troostwijk (Lose) | Industrie-Auktionen | Ã°ÂÂÂ EU | Textsuche + Land |
| Ã°ÂÂÂÃ¯Â¸Â Troostwijk (Events) | Auktions-Events | Ã°ÂÂÂ EU | Land + Stadt + **PLZ + Radius** |
| Ã¢ÂÂÃ¯Â¸Â Zoll-Auktion.de | BehÃÂ¶rden-Versteigerungen | Ã°ÂÂÂ©Ã°ÂÂÂª | **PLZ + Umkreis** + Preis |
| Ã°ÂÂÂ Websuche | DuckDuckGo-Fallback | Global | Ã¢ÂÂ |

### Beispiele

```
# Einmalige Suche
> Suche auf Kleinanzeigen nach Gartentisch in 21224, 20km
> Suche Land Rover auf der Zoll-Auktion

# Automatischer Monitor (stÃÂ¼ndlich, tokenlos)
> ÃÂberwache eGun auf Sauer 505
> ÃÂberwache Kleinanzeigen auf Sonnenschirm in 21224, 20km Umkreis
> ÃÂberwache Troostwijk auf neue Auktionen in Deutschland
> ÃÂberwache Troostwijk Auktionen im Umkreis von 100km um 21224
```

---

## Ã°ÂÂ¤Â Sub-Agenten

Alle Marktplatz-Monitore laufen als **tokenlose Sub-Agenten** Ã¢ÂÂ kein LLM, keine API-Kosten:

| Agent | Plattform | Intervall | Token-Kosten |
|---|---|---|---|
| Monitor_Netzwerk | LAN-Scan | alle 5 Min | 0 (geschÃÂ¼tzt) |
| Monitor_Gartentisch | Kleinanzeigen | stÃÂ¼ndlich | 0 |
| Monitor_Sonnenschirm | Kleinanzeigen | stÃÂ¼ndlich | 0 |
| Monitor_Sauer505 | eGun | stÃÂ¼ndlich | 0 |
| Monitor_TW_Deutschland | Troostwijk Events | stÃÂ¼ndlich | 0 |
| Monitor_TW_PLZ21224_100km | Troostwijk Umkreis | stÃÂ¼ndlich | 0 |
| CronJob_0715 | Tagesbriefing | tÃÂ¤gl. 07:15 | ~500 |

---

## Ã°ÂÂÂ  Home Assistant

```
> Schalte das Licht im Fernsehzimmer an
> Wie warm ist es im Schlafzimmer?
> Was lÃÂ¤uft gerade im Wohnzimmer?
```

Push-Benachrichtigungen bei Bewegung, geÃÂ¶ffneten TÃÂ¼ren, Rauchmeldern und mehr.

---

## Ã°ÂÂ¤Â LLM-Backends

PiClaw OS unterstÃÂ¼tzt **Multi-LLM-Routing** mit automatischer Fallback-Kette:

| Anbieter | Format | Kostenlos | Empfehlung |
|---|---|---|---|
| **Groq** | `gsk_...` | Ã¢ÂÂ | Haupt-Backend, schnellste Antworten |
| **Cerebras** | `csk-...` | Ã¢ÂÂ | Ultraschnell (>2000 Tok/s), Llama 3.3 70B |
| NVIDIA NIM | `nvapi-...` | Ã¢ÂÂ 1k/Monat | Fallback |
| OpenRouter | `sk-or-...` | Ã¢ÂÂ Viele | Aggregator |
| Anthropic | `sk-ant-...` | Ã¢ÂÂ | Premium-Alternative |
| **Gemma 4 E2B Q4** | kein Key | Ã¢ÂÂ | Offline-Fallback |

### Ã°ÂÂÂ LLM Autonomie (NEU in v0.17)

Dameon findet und registriert selbstÃÂ¤ndig neue kostenlose LLM-Backends:

```
> Finde neue LLM Backends
Ã°ÂÂÂ LLM Auto-Discovery gestartetÃ¢ÂÂ¦
Ã°ÂÂÂ¡ Groq (Key vorhanden)
   Ã¢ÂÂ Alle freien Modelle bereits registriert
Ã°ÂÂÂ¡ NVIDIA NIM (Key vorhanden)
   Ã¢ÂÂ mixtral-8x7b-instruct Ã¢ÂÂ registriert als auto-nvidia-mixtral (561ms)
Ã°ÂÂÂ Cerebras Ã¢ÂÂ kein API-Key vorhanden
   Ã¢ÂÂ Anmeldung: https://cloud.cerebras.ai
Ã°ÂÂÂ Ergebnis: 1 neu registriert, 2 Provider verfÃÂ¼gbar
```

**Wie es funktioniert:**
- `llm_discover` scannt alle bekannten Free-Tier-Provider (Groq, NVIDIA, Cerebras, OpenRouter)
- Testet automatisch ungenutzte Modelle und registriert funktionierende
- LÃÂ¤uft auch **tÃÂ¤glich im Hintergrund** via Health Monitor (proaktive Discovery)
- Funktioniert **ohne LLM** (Regex-Shortcut) Ã¢ÂÂ genau dann wenn alle Cloud-Backends down sind
- 24 kostenlose Modelle in der Whitelist auf 4 Providern

---

## Ã°ÂÂÂ» CLI-Referenz

```bash
piclaw              # Chat starten
piclaw setup        # Einrichtungs-Wizard
piclaw update       # Aktualisieren (git pull + Neustart)
piclaw doctor       # System-Status prÃÂ¼fen
piclaw agent list   # Sub-Agenten anzeigen
piclaw llm list     # LLM-Backends anzeigen
piclaw soul edit    # PersÃÂ¶nlichkeit bearbeiten
piclaw backup       # Backup erstellen
```

---

## Ã°ÂÂÂ¡Ã¯Â¸Â Sicherheit

PiClaw OS wurde vor dem Release einem vollstÃÂ¤ndigen Security-Audit unterzogen. Alle kritischen Schwachstellen wurden behoben:

- Ã¢ÂÂ WhatsApp Webhook Auth-Bypass geschlossen
- Ã¢ÂÂ Firewall auf LAN-IPs eingeschrÃÂ¤nkt (nicht internet-weit)
- Ã¢ÂÂ GitHub-Token aus Prozessliste entfernt
- Ã¢ÂÂ CORS auf lokales Netzwerk beschrÃÂ¤nkt
- Ã¢ÂÂ Shell Command-Injection geblockt
- Ã¢ÂÂ Security-Header (X-Frame-Options, CSRF-Schutz)
- Ã¢ÂÂ Path-Traversal in `write_workspace_file` gefixt (v0.17)
- Ã¢ÂÂ IP-Validierung in Network-Security-Tools (v0.17)
- Ã¢ÂÂ Command-Injection in Updater via `shlex.quote` (v0.17)
- Ã¢ÂÂ Network-Tool komplett auf `subprocess_exec` umgestellt (v0.17)

Mehr Details: [SECURITY.md](SECURITY.md)

---

## Ã°ÂÂÂºÃ¯Â¸Â Roadmap

- **v0.17** Ã¢ÂÂ *Aktuell* Ã¢ÂÂ LLM Autonomie, Troostwijk Umkreis, Zoll-Auktion, Security-PRs
- **v0.18** Ã¢ÂÂ IPC-Reload (kein Neustart bei neuem Sub-Agent)
- **v0.19** Ã¢ÂÂ Marketplace: Query-Extraktion verbessern, Willhaben Kategorie-Filter
- **v1.0** Ã¢ÂÂ Frische Installation < 10 Minuten, alle Tests grÃÂ¼n

---

## Ã°ÂÂÂ Ã¯Â¸Â Troubleshooting

| Problem | LÃÂ¶sung |
|---|---|
| `piclaw update` hÃÂ¤ngt | `github_token` in `/etc/piclaw/config.toml` eintragen |
| `git pull: insufficient permission` | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Zeitzone falsch | `sudo timedatectl set-timezone Europe/Berlin` |
| Troostwijk 404 | BuildId veraltet Ã¢ÂÂ erneuert sich automatisch |
| Sub-Agent startet nicht | `piclaw agent list` + mission-JSON prÃÂ¼fen |
| Dameon antwortet nicht | `piclaw doctor` ausfÃÂ¼hren |

---

## Ã¢ÂÂ UnterstÃÂ¼tze PiClaw OS

<a href="https://ko-fi.com/rainbowlabsinc" target="_blank">
  <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi" height="36">
</a>

PiClaw OS ist ein Open-Source-Hobbyprojekt. Alle Spenden flieÃÂen direkt in die Weiterentwicklung Ã¢ÂÂ z.B. fÃÂ¼r neue Hardware wie einen **AI HAT+ 2**, SSDs, Sensoren oder TestgerÃÂ¤te. Jeder Beitrag hilft, das Projekt am Leben zu halten.

---

## Ã°ÂÂÂ Lizenz

MIT License Ã¢ÂÂ frei nutzbar, modifizierbar und verteilbar.

---

## Ã°ÂÂÂ Gebaut mit

[FastAPI](https://fastapi.tiangolo.com) ÃÂ· [aiohttp](https://docs.aiohttp.org) ÃÂ· [QMD](https://github.com/tobilu/qmd) ÃÂ· [python-telegram-bot](https://python-telegram-bot.org) ÃÂ· [Scrapling](https://github.com/D4Vinci/Scrapling) ÃÂ· [timezonefinder](https://github.com/jannikmi/timezonefinder) ÃÂ· [croniter](https://github.com/kiorky/croniter) ÃÂ· [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)

---

<div align="center">

**Made with Ã¢ÂÂ¤Ã¯Â¸Â for the Raspberry Pi community**

[Dokumentation](piclaw-os/README.md) ÃÂ· [Sicherheit](SECURITY.md) ÃÂ· [Changelog](piclaw-os/CHANGELOG.md) ÃÂ· [Roadmap](piclaw-os/ROADMAP.md) ÃÂ· [Ã¢ÂÂ Spenden](https://ko-fi.com/rainbowlabsinc)

</div>
