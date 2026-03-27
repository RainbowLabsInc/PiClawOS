# 🐾 PiClaw OS

**An AI Operating System for Raspberry Pi 5**  
*v0.15.2 · March 2026*

PiClaw OS turns a Raspberry Pi into an always-on autonomous AI assistant. The agent runs 24/7, handles messages across multiple channels, monitors marketplaces for new listings, controls smart home devices, and manages hardware — all from a small, low-power device that runs entirely offline if needed.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧠 **Multi-LLM Routing** | NVIDIA NIM, Anthropic, OpenAI, Gemini, Groq, Cerebras, Mistral, Fireworks, Ollama, local GGUF — with thermal fallback |
| 🛒 **Marketplace Monitor** | Kleinanzeigen.de, eBay.de, **willhaben.at**, web search — monitors continuously, reports only new listings via Telegram |
| 🤖 **Natural Language Monitoring** | *"Watch eBay for a Pi 5 in my area"* → creates a scheduled agent automatically |
| 💬 **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| 🏠 **Home Assistant** | REST + WebSocket, 11 tools, real-time push events |
| 🧠 **Hybrid Memory** | BM25 + vector search (QMD), persistent facts across conversations |
| 👁️ **Sub-Agent System** | Dynamic agents with interval/cron/continuous schedules, auto-cleanup |
| 👁️ **Watchdog** | Service monitoring, heartbeat check, hardware alerts |
| 🌐 **Web Dashboard** | 8 tabs: Dashboard · Memory · Agents · Soul · Hardware · Metrics · Camera · Chat |
| 📷 **Camera** | Pi Camera v2/v3 + USB webcams, AI-powered image description |
| 🌡️ **Thermal Routing** | Switches to API backends when Pi gets hot |
| 🔧 **Self-Update** | `piclaw update` — git pull + service restart |
| 🔍 **Debug Tools** | `piclaw debug` — built-in diagnostic scripts for all subsystems |

---

## 🚀 Quick Start

### Requirements
- Raspberry Pi 5 (recommended) or Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD card ≥ 16 GB (32 GB recommended for local models)
- An LLM API key (optional — local models work offline)

### Installation

**1.** Download `piclaw-sdcard.zip` from [Releases](../../releases) and extract it.

**2.** Open `piclaw/piclaw.conf` and enter your API key (optional):
```ini
PICLAW_LLM_KEY = "nvapi-..."   # NVIDIA NIM (free tier)
# PICLAW_LLM_KEY = "sk-ant-..." # Anthropic Claude
# PICLAW_LLM_KEY = "gsk_..."    # Groq (free tier, very fast)
# Leave empty → local Gemma 2B (offline, no key needed)
```

**3.** Copy `piclaw/` to the `bootfs` partition of your SD card.

**4.** Insert SD card, power on, wait 60 seconds. Then:
```bash
ssh -t pi@piclaw.local
sudo bash /boot/firmware/piclaw/install.sh   # Pi 5
# sudo bash /boot/piclaw/install.sh          # Pi 4
piclaw setup
```

**5.** Open the web dashboard: **http://piclaw.local:7842**

---

## 🤖 Supported LLM Providers

Auto-detected from API key prefix — no manual configuration needed.

| Provider | Key Format | Notes |
|----------|-----------|-------|
| NVIDIA NIM | `nvapi-...` | Free tier · best available model auto-selected |
| Anthropic Claude | `sk-ant-...` | Claude Sonnet |
| OpenAI | `sk-...` | GPT-4o |
| Google Gemini | `AIza...` | Gemini 2.0 Flash |
| Groq | `gsk_...` | Free tier · very fast inference |
| Cerebras | `csk-...` | Free tier · extremely fast |
| Mistral | (probe) | Mistral Large |
| Fireworks AI | `fw-...` | Llama 3.1 70B |
| **Ollama** | no key | Local server · `qwen2.5:1.5b` recommended for Pi 5 |
| **Gemma 2B Q4** | no key | Offline fallback · default local model |

### Setup Wizard — Smart LLM Configuration
```
piclaw setup → LLM → [1] Auto-Detect
  ✓ Key erkannt → Verbindung testen → speichern
  ✗ Fehler → Trotzdem speichern? / Nochmal versuchen? / Manuell eingeben?
           → Manuell: Provider + Base-URL + Modell + Key selbst eintragen
```

### Ollama (recommended for offline use)
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b    # ~1 GB, ~60s/response, tool calling support
# ollama pull qwen2.5:3b    # ~2 GB, better quality (needs 8 GB RAM free)
```

---

## 🛒 Marketplace Search & Monitoring

### One-time search
```
> Search Kleinanzeigen for a Raspberry Pi 5 under €80 in Hamburg
> Search eBay and willhaben for a Raspberry Pi 5
> Search all platforms for a garden table in 21224 Rosengarten, 50km radius
```

### Automatic monitoring (new listings only)
Speak naturally — PiClaw creates a scheduled agent automatically:
```
> Watch eBay for Raspberry Pi 5 near 21224, notify me when something new appears
> Monitor Kleinanzeigen for garden furniture under €150, check every 30 minutes
> Keep an eye out for Sonnenschirme on Kleinanzeigen in my area
```

The agent runs on the configured interval, compares against already-seen listings, and sends **only new results** via Telegram/Discord.

**Supported platforms:** Kleinanzeigen.de · eBay.de · willhaben.at (🇦🇹) · Web (DuckDuckGo)

### Manage monitoring agents
```
> Show all running agents
> Stop the Monitor_RaspberryPi
> Delete the Monitor_Sonnenschirme
```

---

## 🤖 Sub-Agent System

PiClaw can create autonomous sub-agents that run on a schedule:

```
> Create an agent that checks CPU temperature every hour and alerts me if it's above 75°C
> Run a daily briefing agent at 7am
> Monitor my Home Assistant sensors continuously
```

**Schedule formats:** `once` · `interval:3600` · `cron:0 7 * * *` · `continuous`

Sub-agents run independently, write results to memory, and notify via the messaging hub.

---

## 🏠 Home Assistant Integration

```
> Turn off the living room lights
> Set the bedroom thermostat to 20°C
> What devices are currently on?
```

Push events (motion, doors, alarms, smoke, flood) are sent automatically via Telegram.

---

## 🖥️ System Services

| Service | Function |
|---------|---------|
| `piclaw-api` | REST API + Web Dashboard (port 7842) |
| `piclaw-agent` | Main AI agent daemon |
| `piclaw-watchdog` | Hardware & service monitoring |
| `piclaw-crawler` | Web crawler sub-agent |
| `piclaw-qmd-update.timer` | Hourly memory index update (systemd timer) |

```bash
piclaw start / stop / status    # Control all services
piclaw doctor                   # Full health check
```

---

## 💻 CLI Reference

```bash
piclaw                          # Start chat
piclaw setup                    # Interactive setup wizard
piclaw update                   # Self-update via git pull
piclaw doctor                   # System health check
piclaw debug                    # Run diagnostic scripts
piclaw soul show / edit / reset # Agent personality
piclaw model download [id]      # Download local LLM
piclaw briefing send morning    # Send morning briefing
piclaw messaging test           # Test all messaging adapters
piclaw backup / restore         # Backup & restore config + memory
piclaw camera snapshot          # Take a photo + AI description
```

---

## 🛠️ Troubleshooting

```bash
piclaw doctor                     # Full health check
piclaw debug                      # Interactive diagnostic menu
journalctl -u piclaw-api -n 50    # API logs
cat /var/log/piclaw/agent.log | tail -30
```

| Problem | Solution |
|---------|---------|
| `Cloud-APIs nicht erreichbar` | Run `piclaw setup` → re-enter API key |
| `LLM health: UNREACHABLE` | Check key in `/etc/piclaw/config.toml` |
| `Ollama timeout` | Use smaller model: `ollama pull qwen2.5:1.5b` |
| `Permission denied: models/` | `sudo chown -R piclaw:piclaw /etc/piclaw/models/` |
| `watchdog won't start` | `sudo chmod 1777 /etc/piclaw/ipc/` |
| `piclaw.local not found` | Use IP: `ssh -t pi@192.168.X.X` |
| High CPU after restart | QMD runs once on first boot — normal, resolves in ~2 min |

---

## 🗺️ Roadmap

- **v0.16** — Emergency shutdown via smart plug on modem
- **v0.17** — Security tools (fail2ban, IP blocking)
- **v0.18** — Queue system (parallel CLI + Telegram requests)
- **v0.23** — Marketplace: Willhaben.at location filter, Preishistorie

---

## 📄 License

MIT License

---

## 🙏 Built With

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [Ollama](https://ollama.com) · [FastAPI](https://fastapi.tiangolo.com) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org) · [Scrapling](https://github.com/D4Vinci/Scrapling)
