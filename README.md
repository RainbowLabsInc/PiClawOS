# 🐾 PiClaw OS

**An Autonomous AI Operating System for Raspberry Pi 5**

PiClaw OS turns a Raspberry Pi into an always-on, proactive AI assistant named Dameon. The agent runs 24/7, handles messages across multiple channels, controls smart home devices, searches marketplaces for new listings, and monitors hardware — all from a small, low-power device on your local network.

It supports native **German** and **English** interfaces and interactions, making it highly accessible and customizable for different regions.

---

## ✨ Highlights & Capabilities

| Capability | Description |
|------------|-------------|
| 🧠 **Multi-LLM Routing** | Anthropic Claude, OpenAI, NVIDIA NIM (Kimi K2, Nemotron), Google Gemini, Ollama, and fully offline local models (Gemma 2B, Phi-3, TinyLlama) with automatic thermal and availability fallback. |
| 🌍 **Native Multi-Language** | Fully supports **German** and **English** for both the CLI, Web UI, and conversational interfaces. |
| 💬 **Messaging Hub** | Connect with Dameon via Telegram, Discord, Threema, WhatsApp, and MQTT. Seamless parallel queue system so multiple requests don't block each other. |
| 🏠 **Home Assistant** | REST + WebSocket integration with 11 native tools. Real-time push events to your messaging channels (e.g., motion, doors, alarms, smoke, flood). |
| 🛒 **Marketplace Crawler** | Background monitoring of Kleinanzeigen.de, eBay.de, and web search. Dameon only reports **new listings** since the last check directly to your chat. |
| 🤖 **Proactive Agent** | Receives morning briefings, evening check-ins, and hardware threshold alerts (CPU temp, disk, RAM). |
| 🧠 **Hybrid Memory** | Persistent facts across conversations using BM25 and vector search via QMD. Dameon remembers past events and context seamlessly. |
| 🛠️ **Installer Sub-Agent** | Dameon can autonomously install software from trusted sources (GitHub whitelist, pip, apt) with mandatory user confirmation via Telegram or CLI. |
| 🌐 **Tandem Browser** | Automated web browsing capabilities. Dameon can navigate websites, click selectors, read content, and take screenshots. |
| 📡 **Network Monitor** | LAN device scanning via `nmap` with new device detection and instant alerts via Telegram. |
| 👁️ **Watchdog & Hardware** | Isolated hardware and service monitoring. Pi Camera v2/v3 + USB webcam support with AI-powered image descriptions. |
| 💻 **Web Dashboard** | Comprehensive 8-tab interface: Dashboard · Memory · Agents · Soul (Personality Editor) · Hardware · Metrics · Camera · Chat. |

---

## 🚀 Quick Start

### Requirements
- **Hardware:** Raspberry Pi 5 (recommended) or Pi 4
- **OS:** Raspberry Pi OS Lite 64-bit (Bookworm or Trixie)
- **Storage:** SD card ≥ 16 GB (32 GB recommended for local models)
- **Optional:** An LLM API key (local models work completely offline)

### Installation

**Option A — Clone from GitHub (recommended):**
```bash
git clone https://github.com/RainbowLabsInc/PiClawOS.git
cd PiClawOS/piclaw-os
sudo bash install.sh
```

**Option B — SD card (offline):**
1. Download `piclaw-sdcard.zip` from [Releases](../../releases) and extract it. You will get a folder called `piclaw/`.
2. Edit `piclaw/piclaw.conf` and add your API key (optional).
   ```ini
   PICLAW_LLM_KEY = "sk-ant-..."   # Anthropic
   # PICLAW_LLM_KEY = "nvapi-..."  # NVIDIA NIM (free tier available)
   # PICLAW_LLM_KEY = "sk-..."     # OpenAI
   # Leave empty to use local Gemma 2B (offline, no key needed)
   ```
3. Copy the `piclaw/` folder to the `bootfs` partition of the SD card.
4. Insert the SD card, boot the Pi, and wait 60 seconds.
5. Connect via SSH (the `-t` flag is **required**):
   ```bash
   ssh -t pi@piclaw.local
   # or: ssh -t pi@<your-pi-ip>
   ```
6. Run the installer:
   ```bash
   # Raspberry Pi 5:
   sudo bash /boot/firmware/piclaw/install.sh

   # Raspberry Pi 4:
   sudo bash /boot/piclaw/install.sh
   ```

### First-time Setup
Once installed, run the setup wizard and start chatting:
```bash
piclaw setup   # Interactive configuration wizard (Multi-LLM selection, Network setup)
piclaw doctor  # Verify system health
piclaw         # Start chatting with Dameon in the CLI
```

**Web Dashboard:** Accessible at **http://piclaw.local:7842** or your Pi's IP address.

---

## 🤖 Supported LLM Providers & Local Models

| Provider | Key Format | Notes |
|----------|------------|-------|
| Anthropic Claude | `sk-ant-...` | Recommended cloud (Best quality) |
| OpenAI GPT | `sk-...` | Alternative cloud (GPT-4o, etc.) |
| NVIDIA NIM | `nvapi-...` | High-quality, free tier (Kimi K2, Nemotron) |
| Google Gemini | `AIza...` | Alternative cloud |
| Ollama | no key | Self-hosted, local server |
| **Gemma 2B Q4** ★ | no key | Fully offline, on-device (Default local model) |
| Phi-3 Mini Q4 | no key | Fully offline, better reasoning |
| TinyLlama Q4 | no key | Fully offline, fastest (~5s) |

Manage your local models easily:
```bash
piclaw model download               # Gemma 2B Q4 (~1.6 GB)
piclaw model download phi3-mini-q4  # Phi-3 Mini (~2.2 GB)
piclaw model download tinyllama-q4  # TinyLlama (~0.7 GB)
piclaw model status                 # Show installed models
```

---

## 💻 CLI Reference

```bash
piclaw                      # Chat with the agent
piclaw setup                # Configuration wizard
piclaw doctor               # System health check
piclaw start / stop         # Control services
piclaw llm list             # Show registered LLM backends
piclaw llm add --name ...   # Register a new backend
piclaw soul show / edit     # Agent personality management
piclaw briefing send morning# Send morning briefing via Telegram
piclaw agent list           # List active sub-agents
```

---

## 🖥️ System Services

| Service | Purpose |
|---------|---------|
| `piclaw-api` | REST API + Web Dashboard (port 7842) |
| `piclaw-agent` | Main AI agent daemon (Dameon) |
| `piclaw-watchdog` | Hardware and service monitoring |
| `piclaw-crawler` | Background web crawler sub-agent |
| `piclaw-tandem` | Tandem Browser background process |

---

## 🛒 Marketplace Search in Action

Ask the agent in natural language via Telegram, Discord, or CLI:

> *"Search Kleinanzeigen for a Raspberry Pi 5 under €80 in Hamburg"*
> *"Search eBay and Kleinanzeigen for a camera under €200"*

The agent filters the noise and reports **only new listings** directly back to you.

---

## 🏠 Home Assistant Integration

> *"Turn off the living room lights"*
> *"Set the bedroom thermostat to 20°C"*
> *"What devices are currently on?"*

All seamlessly integrated without complex configurations.

---

## 📄 License

MIT License

---

## 🙏 Built With

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [FastAPI](https://fastapi.tiangolo.com) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org)
