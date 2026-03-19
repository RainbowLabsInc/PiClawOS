# 🐾 PiClaw OS

**An AI Operating System for Raspberry Pi 5**

PiClaw OS turns a Raspberry Pi into an always-on autonomous AI assistant. The agent runs 24/7, handles messages across multiple channels, controls smart home devices, searches marketplaces for new listings, and monitors hardware — all from a small, low-power device.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧠 **Multi-LLM Routing** | Anthropic Claude, OpenAI, NVIDIA NIM, Google Gemini, Ollama, local models (Gemma 2B, Phi-3, TinyLlama) with automatic thermal fallback |
| 💬 **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| 🏠 **Home Assistant** | REST + WebSocket, 11 tools, real-time push events |
| 🛒 **Marketplace Crawler** | Kleinanzeigen.de, eBay.de, web search — only new listings since last check |
| 🤖 **Proactive Agent** | Morning briefings, evening check-ins, threshold alerts (CPU, disk, RAM) |
| 🧠 **Hybrid Memory** | BM25 + vector search (QMD), persistent facts across conversations |
| 👁️ **Watchdog** | Service monitoring, heartbeat check, hardware alerts |
| 🌐 **Web Dashboard** | 8 tabs: Dashboard · Memory · Agents · Soul · Hardware · Metrics · Camera · Chat |
| 📷 **Camera** | Pi Camera v2/v3 + USB webcams, AI-powered image description |
| 🌡️ **Thermal Routing** | Automatically switches to API backends when Pi gets hot |

---

## 🚀 Quick Start

### Requirements
- Raspberry Pi 5 (recommended) or Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD card ≥ 16 GB (32 GB recommended for local models)
- An LLM API key (optional — local models work offline)

### Installation

**1.** Download `piclaw-sdcard.zip` from [Releases](../../releases) and extract it.
You get a folder called `piclaw/`.

**2.** Open `piclaw/piclaw.conf` and enter your API key (optional):
```ini
PICLAW_LLM_KEY = "sk-ant-..."   # Anthropic
# PICLAW_LLM_KEY = "nvapi-..."  # NVIDIA NIM (free tier available)
# PICLAW_LLM_KEY = "sk-..."     # OpenAI
# Leave empty to use local Gemma 2B (offline, no key needed)
```

**3.** Copy the entire `piclaw/` folder to the `bootfs` partition of your SD card:
```
bootfs/
├── piclaw/          ← copy here
│   ├── piclaw.conf
│   ├── install.sh
│   └── piclaw-src/
├── config.txt
└── ...
```
> **Pi 5 note:** If `bootfs` has a `firmware/` subdirectory, copy `piclaw/` inside that instead.

**4.** Insert SD card, power on Pi, wait 60 seconds.

**5.** Connect via SSH (the `-t` flag is **required**):
```bash
ssh -t pi@piclaw.local
# or: ssh -t pi@<your-pi-ip>
```

**6.** Run the installer:
```bash
# Raspberry Pi 5:
sudo bash /boot/firmware/piclaw/install.sh

# Raspberry Pi 4:
sudo bash /boot/piclaw/install.sh
```

**7.** Follow the prompts — download Gemma 2B when asked, then run the setup wizard:
```bash
piclaw setup
```

**8.** Open the web dashboard: **http://piclaw.local:7842**

---

## 🤖 Supported LLM Providers

| Provider | Key Format | Notes |
|----------|-----------|-------|
| Anthropic Claude | `sk-ant-...` | Best quality |
| OpenAI GPT | `sk-...` | GPT-4o, GPT-4 Turbo |
| NVIDIA NIM | `nvapi-...` | Free tier at [build.nvidia.com](https://build.nvidia.com) |
| Google Gemini | `AIza...` | Gemini 1.5 Pro / Flash |
| Ollama | no key | Local server |
| **Gemma 2B Q4** ★ | no key | Offline, default local model |
| Phi-3 Mini Q4 | no key | Offline, better reasoning |
| TinyLlama Q4 | no key | Offline, fastest (~5s) |

### Local Model Management
```bash
piclaw model download              # Gemma 2B Q4 — 1.6 GB, ~10-15s response
piclaw model download phi3-mini-q4 # Phi-3 Mini  — 2.2 GB, ~30-90s response
piclaw model download tinyllama-q4 # TinyLlama   — 0.7 GB, ~5s response
piclaw model status                # Show installed models
```

---

## 🖥️ System Services

| Service | Function |
|---------|---------|
| `piclaw-api` | REST API + Web Dashboard (port 7842) |
| `piclaw-agent` | Main AI agent daemon |
| `piclaw-watchdog` | Hardware & service monitoring |
| `piclaw-crawler` | Web crawler sub-agent |

```bash
piclaw start / stop / status    # Control all services
piclaw doctor                   # Full health check
```

---

## 💻 CLI Reference

```bash
piclaw                          # Start chat
piclaw setup                    # Interactive setup wizard
piclaw doctor                   # System health check
piclaw soul show / edit / reset # Agent personality
piclaw model download [id]      # Download local LLM
piclaw briefing send morning    # Send morning briefing via Telegram
piclaw messaging test           # Test all messaging adapters
piclaw backup / restore         # Backup & restore
piclaw camera snapshot          # Take a photo + AI description
```

---

## 🛒 Marketplace Search

Ask the agent in natural language:

> *"Search Kleinanzeigen for a Raspberry Pi 5 under €80 in Hamburg"*
> *"Search eBay and Kleinanzeigen for a camera under €200"*

The agent only reports **new listings** since the last search.

---

## 🏠 Home Assistant Integration

> *"Turn off the living room lights"*
> *"Set the bedroom thermostat to 20°C"*
> *"What devices are currently on?"*

Push events (motion, doors, alarms, smoke, flood) are sent automatically via Telegram.

---

## 📁 Project Structure

```
piclaw-os/
├── boot/piclaw/
│   ├── install.sh          # Installer
│   ├── piclaw.conf         # Configuration template
│   └── piclaw-src/         # Source code
└── piclaw/                 # Python package
    ├── agent.py            # Main AI agent
    ├── api.py              # FastAPI REST + WebSocket
    ├── cli.py              # CLI tool
    ├── wizard.py           # Setup wizard
    ├── agents/             # Watchdog, crawler, sub-agents
    ├── llm/                # LLM backends + router
    ├── memory/             # Hybrid memory (QMD)
    ├── messaging/          # Telegram, Discord, MQTT, etc.
    ├── tools/              # Shell, GPIO, HA, marketplace
    ├── hardware/           # Camera, I2C, thermal, sensors
    └── web/                # Web dashboard
```

---

## 🛠️ Troubleshooting

```bash
piclaw doctor                     # Full health check
journalctl -u piclaw-api -n 50    # API logs
```

| Problem | Solution |
|---------|---------|
| `LLM health: UNREACHABLE` | Check `api_key` in `/etc/piclaw/config.toml` |
| `Permission denied: models/` | `sudo chown -R piclaw:piclaw /etc/piclaw/models/` |
| `watchdog won't start` | `sudo chmod 1777 /etc/piclaw/ipc/` |
| `piclaw.local not found` | Use IP: `ssh -t pi@192.168.X.X` |

---

## 🗺️ Roadmap

- **v0.14** — Parallel request queue (CLI + Telegram simultaneously)
- **v0.15** — Network monitoring (nmap, new device detection)
- **v0.16** — Emergency shutdown via smart plug on modem
- **v0.17** — Security tools (fail2ban, IP blocking)

---

## 📄 License

MIT License

---

## 🙏 Built With

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [FastAPI](https://fastapi.tiangolo.com) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org)
