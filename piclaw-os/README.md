# PiClaw OS

**An AI operating system for Raspberry Pi 5**

PiClaw OS turns a Raspberry Pi into an always-on autonomous AI assistant. The agent runs 24/7, handles messages across multiple channels, controls smart home devices, searches marketplaces for new listings, and monitors hardware — all from a small, low-power device on your local network.

---

## Features

| Feature | Description |
|---------|-------------|
| **Multi-LLM Routing** | Anthropic Claude, OpenAI, NVIDIA NIM (Kimi K2, Nemotron), Ollama, local models (Gemma 2B, Phi-3, TinyLlama) with automatic thermal and availability fallback |
| **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| **Home Assistant** | REST + WebSocket, 11 tools, real-time push events |
| **Marketplace Crawler** | Kleinanzeigen.de, eBay.de, web search — reports only new listings since last check |
| **Proactive Agent** | Morning briefings, evening check-ins, threshold alerts (CPU temp, disk, RAM) |
| **Hybrid Memory** | BM25 + vector search via QMD, persistent facts across conversations |
| **Watchdog** | Service monitoring, heartbeat check, hardware alerts via Telegram |
| **Web Dashboard** | 8 tabs: Dashboard · Memory · Agents · Soul · Hardware · Metrics · Camera · Chat |
| **Camera** | Pi Camera v2/v3 + USB webcams, AI-powered image description |
| **Network Monitor** | LAN device scanning via nmap, new device detection and alerts |
| **Installer Sub-Agent** | Dameon can autonomously install software from trusted sources with user confirmation |

---

## Quick Start

### Requirements

- Raspberry Pi 5 (recommended) or Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm or Trixie)
- SD card ≥ 16 GB
- Internet connection

### Installation

**Option A — Clone from GitHub (recommended):**

```bash
git clone https://github.com/RainbowLabsInc/PiClawOS.git
cd PiClawOS/piclaw-os
sudo bash install.sh
```

**Option B — SD card (offline):**

1. Copy the `piclaw/` folder to the `bootfs` partition of the SD card
2. Edit `piclaw/piclaw.conf` and add your API key (optional)
3. Insert SD card, boot the Pi, wait 60 seconds
4. Connect via SSH (the `-t` flag is required):
   ```bash
   ssh -t pi@piclaw.local
   ```
5. Run the installer:
   ```bash
   # Raspberry Pi 5:
   sudo bash /boot/firmware/piclaw/install.sh

   # Raspberry Pi 4:
   sudo bash /boot/piclaw/install.sh
   ```

### First-time setup

```bash
piclaw setup   # Interactive configuration wizard
piclaw doctor  # Verify everything is working
piclaw         # Start chatting with Dameon
```

---

## Supported LLM Providers

| Provider | Key Format | Notes |
|----------|------------|-------|
| Anthropic Claude | `sk-ant-...` | Recommended cloud |
| OpenAI GPT | `sk-...` | Alternative cloud |
| NVIDIA NIM (Kimi K2, Nemotron) | `nvapi-...` | High-quality, free tier |
| Google Gemini | `AIza...` | Alternative cloud |
| Ollama | no key | Self-hosted, local server |
| Gemma 2B / Phi-3 / TinyLlama | no key | Fully offline, on-device |

Multiple backends can be registered and the router selects the best one based on task type, availability, and Pi temperature.

---

## Local Models

```bash
piclaw model download               # Gemma 2B Q4 (default, ~1.6 GB)
piclaw model download phi3-mini-q4  # Phi-3 Mini (~2.2 GB)
piclaw model download tinyllama-q4  # TinyLlama (~0.7 GB, fastest)
```

---

## CLI Reference

```bash
piclaw                      # Chat with the agent
piclaw setup                # Configuration wizard
piclaw doctor               # System health check
piclaw start / stop         # Control services
piclaw model download [id]  # Download a local model
piclaw llm list             # Show registered LLM backends
piclaw llm add --name ...   # Register a new backend
piclaw briefing send morning
piclaw agent list
```

---

## System Services

| Service | Purpose |
|---------|---------|
| `piclaw-api` | REST API + Web Dashboard (port 7842) |
| `piclaw-agent` | Main agent daemon |
| `piclaw-watchdog` | Hardware and service monitoring |
| `piclaw-crawler` | Background web crawler sub-agent |

---

## Version

**v0.15** — March 2026

Full changelog: [CHANGELOG.md](CHANGELOG.md)
Roadmap: [ROADMAP.md](ROADMAP.md)

---

## License

MIT License
