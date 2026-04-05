# 🐾 PiClaw OS

**An AI Operating System for Raspberry Pi 5**  
*v0.15.5 · April 2026*

PiClaw OS turns a Raspberry Pi into an always-on autonomous AI assistant. The agent runs 24/7, handles messages across multiple channels, monitors marketplaces and auction platforms for new listings, controls smart home devices, and manages hardware — all from a small, low-power device that can run entirely offline if needed.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧠 **Multi-LLM Routing** | Groq (Llama 3.3, Kimi K2), NVIDIA NIM, Anthropic Claude, OpenAI, OpenRouter, Ollama, local Qwen3 — with automatic fallback chain |
| 🛒 **Marketplace Monitor** | Kleinanzeigen.de, eBay.de, eGun.de, willhaben.at, Troostwijk — monitors continuously, reports **only new listings** via Telegram |
| 🏛️ **Auction Event Monitor** | **NEW:** Troostwijk — monitor for new auction *events* by country or city, not just individual lots |
| 🤖 **Natural Language Monitoring** | *"Watch eGun for a Sauer 505"* or *"Monitor Troostwijk for new auctions in Germany"* → creates a scheduled agent automatically |
| 💬 **Messaging Hub** | Telegram, WhatsApp, Threema, MQTT |
| 🏠 **Home Assistant** | REST + WebSocket, 11 tools, real-time push events |
| 🧠 **Hybrid Memory** | BM25 + vector search (QMD), persistent facts across conversations |
| 👁️ **Sub-Agent System** | Tokenless scheduled agents (marketplace monitors run **without any LLM calls**) |
| 🔒 **Watchdog** | Service monitoring, heartbeat check, hardware alerts |
| 🌐 **Web Dashboard** | 8 tabs: Dashboard · Memory · Agents · Soul · Hardware · Metrics · Camera · Chat |
| 📷 **Camera** | Pi Camera v2/v3 + USB webcams, AI-powered image description |
| 🌡️ **Thermal Routing** | Switches to cloud API backends when Pi runs hot |
| 🔧 **Self-Update** | `piclaw update` — git pull + service restart |

---

## 🚀 Quick Start

### Requirements
- Raspberry Pi 5 (recommended) or Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD card ≥ 16 GB
- An LLM API key (optional — local models work offline)

### Installation

**1.** Clone the repo onto your Pi:
```bash
git clone https://github.com/RainbowLabsInc/PiClawOS.git
cd PiClawOS/piclaw-os
sudo bash install.sh
piclaw setup
```

**2.** Open the web dashboard: **http://piclaw.local:7842**

---

## 🆓 Free API Keys — Where to Get Them

PiClaw OS runs entirely on free API tiers. No credit card required for the recommended setup.

| Provider | Free Tier | URL | Key Format |
|----------|-----------|-----|------------|
| **Groq** ⭐ | Unlimited (rate-limited) | [console.groq.com](https://console.groq.com) | `gsk_...` |
| **NVIDIA NIM** | 1,000 API calls/month | [build.nvidia.com](https://build.nvidia.com) | `nvapi-...` |
| **OpenRouter** | Many free models | [openrouter.ai](https://openrouter.ai) | `sk-or-...` |
| **Telegram Bot** | Completely free | [@BotFather](https://t.me/BotFather) | `1234:ABC...` |
| **Local (Qwen3)** | No key needed | bundled | — |

**Recommended free setup (priority order):**
```
[10] Groq  – llama-3.3-70b-versatile   → main backend, fast
[ 9] Groq  – kimi-k2-instruct          → fallback, tool-calling
[ 6] NVIDIA NIM – llama-4-maverick     → cloud fallback
[local] Qwen3-1.7B Q4_K_M             → offline, no internet needed
```

---

## 🛒 Marketplace Search & Monitoring

### Supported Platforms

| Platform | Type | Country | Filter |
|----------|------|---------|--------|
| 📌 Kleinanzeigen.de | Classifieds | 🇩🇪 | PLZ + radius + price |
| 🛍️ eBay.de | Marketplace | 🇩🇪 | PLZ + price |
| 🎯 eGun.de | Weapons/Outdoor | 🇩🇪 | Price |
| 🇦🇹 Willhaben.at | Classifieds | 🇦🇹 | Province/city |
| 🔨 Troostwijk (lots) | Industrial auctions | 🌍 EU | Text search + country |
| 🏛️ Troostwijk (events) | Auction events | 🌍 EU | **Country + city** |
| 🌐 Web | DuckDuckGo fallback | Global | — |

### One-time search
```
> Search Kleinanzeigen for a Raspberry Pi 5 under €80 in Hamburg
> Search eGun for Sauer 505
> Search Troostwijk for forklifts in Germany
```

### Automatic monitoring
Speak naturally — PiClaw creates a tokenless scheduled agent automatically:
```
> Watch Kleinanzeigen for Gartentisch in 21224, 20km radius
> Monitor eGun for Sauer 505
> Monitor Troostwijk for new auctions in Germany
> Monitor Troostwijk for new auctions in Hamburg
> Monitor Troostwijk for new auctions in the Netherlands
```

All marketplace monitors run **100% tokenless** — no LLM calls, no API costs, every hour.

### Troostwijk Auction Event Monitor (new in v0.15.5)

Unlike the standard lot search, the **auction event monitor** watches for entire new auction events being published on Troostwijk.

```
> Monitor Troostwijk for new auctions in Germany     → country-level
> Monitor Troostwijk for new auctions in Hamburg     → city-level (name filter)
> Monitor Troostwijk for new auctions in Belgium
> Monitor Troostwijk for new auctions in Netherlands
```

**Supported countries:** Germany, Netherlands, Belgium, France, Austria, Italy, Spain, Sweden, Denmark, Poland, Czech Republic, Hungary, Croatia, Portugal, Finland, Estonia, Greece, Romania and more.

> **Note on city filter:** Troostwijk's API does not provide a city-level filter. City matching is done by searching the auction name for the city keyword (e.g. `"D | Machines Hamburg"` matches "Hamburg"). Country-level filtering is exact.

---

## 🤖 Sub-Agent System

PiClaw creates autonomous sub-agents that run on a schedule. Marketplace monitors use `direct_tool` mode — **no LLM involved**, pure Python:

| Agent | Platform | Schedule | Tokens |
|-------|----------|----------|--------|
| Monitor_Netzwerk | LAN scan | every 5 min | 0 (protected) |
| Monitor_Gartentisch | Kleinanzeigen | hourly | 0 |
| Monitor_Sonnenschirm | Kleinanzeigen | hourly | 0 |
| Monitor_Sauer505 | eGun | hourly | 0 |
| Monitor_TW_Deutschland | Troostwijk (events) | hourly | 0 |
| CronJob_0715 | — | daily 07:15 | ~500 |

**Mission JSON format for custom agents:**
```json
// Article monitor
{"query":"Sauer 505","platforms":["egun"],"location":null,"radius_km":null,"max_price":null}

// Troostwijk auction event monitor
{"query":"","platforms":["troostwijk_auctions"],"location":null,"country":"de","max_results":24}
```

---

## 🏠 Home Assistant Integration

```
> Turn off the living room lights
> Set the bedroom thermostat to 20°C
> What devices are currently on?
```

Push events (motion, doors, alarms, smoke, flood) are sent automatically via Telegram.

---

## 🤖 Supported LLM Backends

| Provider | Key Format | Free | Notes |
|----------|-----------|------|-------|
| **Groq** | `gsk_...` | ✅ | Recommended, fastest free backend |
| NVIDIA NIM | `nvapi-...` | ✅ | 1,000 calls/month free |
| OpenRouter | `sk-or-...` | ✅ | Many free models |
| Anthropic Claude | `sk-ant-...` | ❌ | Pay-per-token, high quality |
| OpenAI | `sk-...` | ❌ | Pay-per-token |
| **Ollama** | no key | ✅ | Local server |
| **Qwen3 Q4 (local)** | no key | ✅ | Offline fallback, bundled |

---

## 🖥️ System Services

| Service | Function |
|---------|----------|
| `piclaw-api` | REST API + Web Dashboard (port 7842) |
| `piclaw-agent` | Main AI agent daemon |
| `piclaw-watchdog` | Hardware & service monitoring |

```bash
piclaw start / stop / status    # Control all services
piclaw doctor                   # Full health check
piclaw update                   # Pull latest code + restart
```

---

## 💻 CLI Reference

```bash
piclaw                          # Start chat with Dameon
piclaw setup                    # Interactive setup wizard
piclaw update                   # Self-update via git pull
piclaw doctor                   # System health check
piclaw soul show / edit / reset # Agent personality
piclaw model download [id]      # Download local LLM
piclaw llm list                 # Show LLM registry
piclaw llm add --name ...       # Register new backend
piclaw agent list               # Show sub-agents
piclaw briefing send morning    # Send morning briefing
piclaw backup / restore         # Backup & restore
piclaw camera snapshot          # Take a photo + AI description
```

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|---------|
| `LLM health: UNREACHABLE` | Check API key in `/etc/piclaw/config.toml` |
| `piclaw update` hangs | Add `github_token` to `/etc/piclaw/config.toml` |
| Troostwijk returns 404 | BuildId expired, auto-renews on next run |
| `piclaw.local` not found | Use IP: `ssh -t pi@192.168.X.X` |
| High CPU after restart | QMD runs once on first boot — normal, resolves in ~2 min |
| Sub-agent not starting | Check `piclaw agent list`, inspect mission JSON |

---

## 🗺️ Roadmap

- **v0.16** — Troostwijk: Stadtfilter via API sobald verfügbar
- **v0.17** — Security tools (fail2ban, IP blocking)
- **v0.18** — HA doctor fix (retry logic on startup)
- **v0.20** — Willhaben: Preishistorie

---

## 📄 License

MIT License

---

## 🙏 Built With

[FastAPI](https://fastapi.tiangolo.com) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org) · [Scrapling](https://github.com/D4Vinci/Scrapling) · [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [aiohttp](https://docs.aiohttp.org)
