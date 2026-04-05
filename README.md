<div align="center">

# 🐾 PiClaw OS

**Dein autonomer KI-Assistent für den Raspberry Pi**

[![Version](https://img.shields.io/badge/version-0.16.0-blue?style=flat-square)](https://github.com/RainbowLabsInc/PiClawOS/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205-red?style=flat-square)](https://www.raspberrypi.com)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Security](https://img.shields.io/badge/security-audited-brightgreen?style=flat-square)](SECURITY.md)

*Läuft 24/7 · Kein Abo · Vollständig offline-fähig · Kostenlose LLM-APIs*

</div>

---

PiClaw OS verwandelt einen Raspberry Pi in einen intelligenten Assistenten, der rund um die Uhr für dich arbeitet: Marktplätze überwachen, Smart Home steuern, Netzwerk im Blick behalten – alles per Telegram oder Browser-Dashboard.

---

## ✨ Was kann PiClaw OS?

| | Feature | Beschreibung |
|---|---|---|
| 🧠 | **Multi-LLM-Routing** | Groq, NVIDIA NIM, OpenRouter, Anthropic, Ollama, lokales Qwen3 – mit automatischer Fallback-Kette |
| 🛒 | **Marktplatz-Monitor** | Kleinanzeigen, eBay, eGun, willhaben, Troostwijk – meldet **nur neue** Inserate per Telegram |
| 🏛️ | **Auktions-Monitor** | Troostwijk: neue Auktions-Events nach Land oder Stadt überwachen |
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
| **NVIDIA NIM** | 1.000 Calls/Monat | [build.nvidia.com](https://build.nvidia.com) | `nvapi-...` |
| **OpenRouter** | Viele Modelle gratis | [openrouter.ai](https://openrouter.ai) | `sk-or-...` |
| **Telegram Bot** | Komplett kostenlos | [@BotFather](https://t.me/BotFather) | `123:ABC...` |
| **Lokal (Qwen3)** | Kein Key nötig | Im Paket enthalten | — |

> **Empfehlung:** Groq als Haupt-Backend + lokales Qwen3 als Offline-Fallback. Fertig.

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
| 🏛️ Troostwijk (Events) | Auktions-Events | 🌍 EU | Land + Stadt |
| 🌐 Websuche | DuckDuckGo-Fallback | Global | — |

### Beispiele

```
# Einmalige Suche
> Suche auf Kleinanzeigen nach Gartentisch in 21224, 20km

# Automatischer Monitor (stündlich, tokenlos)
> Überwache eGun auf Sauer 505
> Überwache Kleinanzeigen auf Sonnenschirm in 21224, 20km Umkreis
> Überwache Troostwijk auf neue Auktionen in Deutschland
> Überwache Troostwijk auf neue Auktionen in Hamburg
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

| Anbieter | Format | Kostenlos | Empfehlung |
|---|---|---|---|
| **Groq** | `gsk_...` | ✅ | Haupt-Backend, schnellste Antworten |
| NVIDIA NIM | `nvapi-...` | ✅ 1k/Monat | Fallback |
| OpenRouter | `sk-or-...` | ✅ Viele | Aggregator |
| Anthropic | `sk-ant-...` | ❌ | Premium-Alternative |
| OpenAI | `sk-...` | ❌ | Pay-per-Token |
| Ollama | kein Key | ✅ | Lokaler Server |
| **Qwen3 Q4** | kein Key | ✅ | Offline-Fallback |

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

Mehr Details: [SECURITY.md](SECURITY.md)

---

## 🗺️ Roadmap

- **v0.16** ← *Aktuell* — Security-Audit, Troostwijk Auktionen, Zeitzone-Autosetup
- **v0.17** — Emergency Shutdown via Smart Plug
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

## 📄 Lizenz

MIT License – frei nutzbar, modifizierbar und verteilbar.

---

## 🙏 Gebaut mit

[FastAPI](https://fastapi.tiangolo.com) · [aiohttp](https://docs.aiohttp.org) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org) · [Scrapling](https://github.com/D4Vinci/Scrapling) · [timezonefinder](https://github.com/jannikmi/timezonefinder) · [croniter](https://github.com/kiorky/croniter) · [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)

---

<div align="center">

**Made with ❤️ for the Raspberry Pi community**

[Dokumentation](piclaw-os/README.md) · [Sicherheit](SECURITY.md) · [Changelog](piclaw-os/CHANGELOG.md) · [Roadmap](piclaw-os/ROADMAP.md)

</div>
