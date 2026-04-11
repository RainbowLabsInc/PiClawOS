<div align="center">

# 🐾 PiClaw OS

**Dein autonomer KI-Assistent für den Raspberry Pi**

[![Version](https://img.shields.io/badge/version-0.17.0-blue?style=flat-square)](https://github.com/RainbowLabsInc/PiClawOS/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205-red?style=flat-square)](https://www.raspberrypi.com)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20PiClaw-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white)](https://ko-fi.com/rainbowlabsinc)

*Läuft 24/7 · Kein Abo · Vollständig offline-fähig · Kostenlose LLM-APIs*

</div>

---

PiClaw OS verwandelt einen Raspberry Pi in einen intelligenten Assistenten, der rund um die Uhr für dich arbeitet: Marktplätze überwachen, Smart Home steuern, Netzwerk im Blick behalten – alles per Telegram, Discord, Browser-Dashboard oder weiteren Schnittstellen.

---

## ✨ Was kann PiClaw OS?

| | Feature | Beschreibung |
|---|---|---|
| 🧠 | **Multi-LLM-Routing** | Groq, NVIDIA NIM, Cerebras, OpenRouter, Ollama, lokales Qwen3 – mit automatischer Fallback-Kette |
| 🔍 | **LLM Autonomie** | Dameon findet und registriert **selbständig** neue kostenlose LLM-Backends (`llm_discover`) |
| 🛒 | **Marktplatz-Monitor** | Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion – meldet **nur neue** Inserate per Telegram |
| 🏛️ | **Auktions-Monitor** | Troostwijk + Zoll-Auktion: Events nach Land, Stadt oder **PLZ + Umkreis** überwachen |
| 🤖 | **Natürliche Sprache** | *„Überwache eGun auf Sauer 505"* → erstellt automatisch einen stündlichen Monitor |
| 💬 | **Messaging Hub** | Telegram, WhatsApp, Threema, MQTT |
| 🏠 | **Home Assistant** | REST + WebSocket, 11 Tools, Echtzeit-Push bei Bewegung/Alarm |
| 🌐 | **Web-Dashboard** | Agents · Memory · Soul · Hardware · Metriken · Kamera · Chat |
| 🔒 | **Tokenlos** | Marktplatz-Monitore laufen **ohne LLM-Aufrufe** – null API-Kosten im Betrieb |
| 🔧 | **Self-Update** | `piclaw update` – Git-Pull + Neustart in einem Befehl |
| 📴 | **Offline-Fallback** | Qwen3-1.7B läuft lokal auf dem Pi – kein Internet nötig |

---

## 🆓 Kostenlos betreiben

PiClaw OS funktioniert vollständig mit kostenlosen API-Tiers:

| Anbieter | Free Tier | URL | Format |
|---|---|---|---|
| **Groq** ⭐ | Unbegrenzt (rate-limited) | [console.groq.com](https://console.groq.com) | `gsk_...` |
| **Cerebras** ⭐ | 8.000 Req/Tag, ultraschnell | [cloud.cerebras.ai](https://cloud.cerebras.ai) | `csk-...` |
| **NVIDIA NIM** | 1.000 Calls/Monat | [build.nvidia.com](https://build.nvidia.com) | `nvapi-...` |
| **OpenRouter** | Viele Modelle gratis | [openrouter.ai](https://openrouter.ai) | `sk-or-...` |
| **Telegram Bot** | Komplett kostenlos | [@BotFather](https://t.me/BotFather) | `123:ABC...` |
| **Lokal (Qwen3)** | Kein Key nötig | Im Paket enthalten | — |

> **Empfehlung:** Groq als Haupt-Backend + Cerebras als Fallback + lokales Qwen3 offline. `llm_discover` findet neue Backends automatisch.

---

## 🚀 Installation

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte ≥ 16 GB

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
Der Wizard führt durch: Agent-Name → LLM-Backend → Telegram → Home Assistant → Standort (für Zeitzone + Wetter)

**3. Dashboard öffnen**
```
http://piclaw.local:7842
```

---

## 🛒 Marktplatz-Monitor

### Unterstützte Plattformen

| Plattform | Typ | Land | Filter |
|---|---|---|---|
| 📌 Kleinanzeigen.de | Kleinanzeigen | 🇩🇪 | PLZ + Umkreis + Preis |
| 🛍️ eBay.de | Marktplatz | 🇩🇪 | PLZ + Preis |
| 🎯 eGun.de | Jagd / Outdoor | 🇩🇪 | Preis |
| 🇦🇹 willhaben.at | Kleinanzeigen | 🇦🇹 | Bundesland / Stadt |
| 🔨 Troostwijk (Lose) | Industrie-Auktionen | 🌍 EU | Textsuche + Land |
| 🏛️ Troostwijk (Events) | Auktions-Events | 🌍 EU | Land + Stadt + **PLZ + Radius** |
| ⚖️ Zoll-Auktion.de | Behörden-Versteigerungen | 🇩🇪 | **PLZ + Umkreis** + Preis |
| 🌐 Websuche | DuckDuckGo-Fallback | Global | — |

### Beispiele

```
# Einmalige Suche
> Suche auf Kleinanzeigen nach Gartentisch in 21224, 20km
> Suche Land Rover auf der Zoll-Auktion

# Automatischer Monitor (stündlich, tokenlos)
> Überwache eGun auf Sauer 505
> Überwache Kleinanzeigen auf Sonnenschirm in 21224, 20km Umkreis
> Überwache Troostwijk auf neue Auktionen in Deutschland
> Überwache Troostwijk Auktionen im Umkreis von 100km um 21224
```

---

## 🤖 Sub-Agenten

Alle Marktplatz-Monitore laufen als **tokenlose Sub-Agenten** – kein LLM, keine API-Kosten:

| Agent | Plattform | Intervall | Token-Kosten |
|---|---|---|---|
| Monitor_Netzwerk | LAN-Scan | alle 5 Min | 0 (geschützt) |
| Monitor_Gartentisch | Kleinanzeigen | stündlich | 0 |
| Monitor_Sonnenschirm | Kleinanzeigen | stündlich | 0 |
| Monitor_Sauer505 | eGun | stündlich | 0 |
| Monitor_TW_Deutschland | Troostwijk Events | stündlich | 0 |
| Monitor_TW_PLZ21224_100km | Troostwijk Umkreis | stündlich | 0 |
| CronJob_0715 | Tagesbriefing | tägl. 07:15 | ~500 |

---

## 🏠 Home Assistant

```
> Schalte das Licht im Fernsehzimmer an
> Wie warm ist es im Schlafzimmer?
> Was läuft gerade im Wohnzimmer?
```

Push-Benachrichtigungen bei Bewegung, geöffneten Türen, Rauchmeldern und mehr.

---

## 🤖 LLM-Backends

PiClaw OS unterstützt **Multi-LLM-Routing** mit automatischer Fallback-Kette:

| Anbieter | Format | Kostenlos | Empfehlung |
|---|---|---|---|
| **Groq** | `gsk_...` | ✅ | Haupt-Backend, schnellste Antworten |
| **Cerebras** | `csk-...` | ✅ | Ultraschnell (>2000 Tok/s), Llama 3.3 70B |
| NVIDIA NIM | `nvapi-...` | ✅ 1k/Monat | Fallback |
| OpenRouter | `sk-or-...` | ✅ Viele | Aggregator |
| Anthropic | `sk-ant-...` | ❌ | Premium-Alternative |
| Ollama | kein Key | ✅ | Lokaler Server |
| **Qwen3 Q4** | kein Key | ✅ | Offline-Fallback |

### 🔍 LLM Autonomie (NEU in v0.17)

Dameon findet und registriert selbständig neue kostenlose LLM-Backends:

```
> Finde neue LLM Backends
🔍 LLM Auto-Discovery gestartet…
📡 Groq (Key vorhanden)
   ✅ Alle freien Modelle bereits registriert
📡 NVIDIA NIM (Key vorhanden)
   ✅ mixtral-8x7b-instruct → registriert als auto-nvidia-mixtral (561ms)
🆓 Cerebras – kein API-Key vorhanden
   → Anmeldung: https://cloud.cerebras.ai
📊 Ergebnis: 1 neu registriert, 2 Provider verfügbar
```

**Wie es funktioniert:**
- `llm_discover` scannt alle bekannten Free-Tier-Provider (Groq, NVIDIA, Cerebras, OpenRouter)
- Testet automatisch ungenutzte Modelle und registriert funktionierende
- Läuft auch **täglich im Hintergrund** via Health Monitor (proaktive Discovery)
- Funktioniert **ohne LLM** (Regex-Shortcut) – genau dann wenn alle Cloud-Backends down sind
- 24 kostenlose Modelle in der Whitelist auf 4 Providern

---

## 💻 CLI-Referenz

```bash
piclaw              # Chat starten
piclaw setup        # Einrichtungs-Wizard
piclaw update       # Aktualisieren (git pull + Neustart)
piclaw doctor       # System-Status prüfen
piclaw agent list   # Sub-Agenten anzeigen
piclaw llm list     # LLM-Backends anzeigen
piclaw soul edit    # Persönlichkeit bearbeiten
piclaw backup       # Backup erstellen
```

---

## 🛡️ Sicherheit

PiClaw OS wurde vor dem Release einem vollständigen Security-Audit unterzogen. Alle kritischen Schwachstellen wurden behoben:

- ✅ WhatsApp Webhook Auth-Bypass geschlossen
- ✅ Firewall auf LAN-IPs eingeschränkt (nicht internet-weit)
- ✅ GitHub-Token aus Prozessliste entfernt
- ✅ CORS auf lokales Netzwerk beschränkt
- ✅ Shell Command-Injection geblockt
- ✅ Security-Header (X-Frame-Options, CSRF-Schutz)
- ✅ Path-Traversal in `write_workspace_file` gefixt (v0.17)
- ✅ IP-Validierung in Network-Security-Tools (v0.17)
- ✅ Command-Injection in Updater via `shlex.quote` (v0.17)
- ✅ Network-Tool komplett auf `subprocess_exec` umgestellt (v0.17)

Mehr Details: [SECURITY.md](SECURITY.md)

---

## 🗺️ Roadmap

- **v0.17** ← *Aktuell* — LLM Autonomie, Troostwijk Umkreis, Zoll-Auktion, Security-PRs
- **v0.18** — IPC-Reload (kein Neustart bei neuem Sub-Agent)
- **v0.19** — Marketplace: Query-Extraktion verbessern, Willhaben Kategorie-Filter
- **v1.0** — Frische Installation < 10 Minuten, alle Tests grün

---

## 🛠️ Troubleshooting

| Problem | Lösung |
|---|---|
| `piclaw update` hängt | `github_token` in `/etc/piclaw/config.toml` eintragen |
| `git pull: insufficient permission` | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Zeitzone falsch | `sudo timedatectl set-timezone Europe/Berlin` |
| Troostwijk 404 | BuildId veraltet – erneuert sich automatisch |
| Sub-Agent startet nicht | `piclaw agent list` + mission-JSON prüfen |
| Dameon antwortet nicht | `piclaw doctor` ausführen |

---

## ☕ Unterstütze PiClaw OS

<a href="https://ko-fi.com/rainbowlabsinc" target="_blank">
  <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi" height="36">
</a>

PiClaw OS ist ein Open-Source-Hobbyprojekt. Alle Spenden fließen direkt in die Weiterentwicklung – z.B. für neue Hardware wie einen **AI HAT+ 2**, SSDs, Sensoren oder Testgeräte. Jeder Beitrag hilft, das Projekt am Leben zu halten.

---

## 📄 Lizenz

MIT License – frei nutzbar, modifizierbar und verteilbar.

---

## 🙏 Gebaut mit

[FastAPI](https://fastapi.tiangolo.com) · [aiohttp](https://docs.aiohttp.org) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org) · [Scrapling](https://github.com/D4Vinci/Scrapling) · [timezonefinder](https://github.com/jannikmi/timezonefinder) · [croniter](https://github.com/kiorky/croniter) · [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)

---

<div align="center">

**Made with ❤️ for the Raspberry Pi community**

[Dokumentation](piclaw-os/README.md) · [Sicherheit](SECURITY.md) · [Changelog](piclaw-os/CHANGELOG.md) · [Roadmap](piclaw-os/ROADMAP.md) · [☕ Spenden](https://ko-fi.com/rainbowlabsinc)

</div>
