# PiClaw OS — Roadmap

## Status: v0.15 (March 2026)
Current state: Kimi K2 + Nemotron via NVIDIA NIM, parallel queue system, network monitor, multi-LLM registry, installer sub-agent and Tandem browser merged.

---

## Completed

### v0.14 — Stability & Parallelism
- [x] Queue system: agent processes Telegram + CLI requests in parallel (asyncio.Queue)
- [x] llama.cpp verbose output suppressed
- [x] Router fallback warning fixed (no spurious `⚠️` after successful responses)

### v0.15 — Network Monitoring
- [x] `tools/network_monitor.py`: `network_scan`, `port_scan`, `check_new_devices` via nmap
- [x] Proactive routines for network checks
- [x] New devices on LAN → Telegram alert

### v0.15a — Installer Sub-Agent
- [x] `tools/installer.py` — autonomous installation with trusted source whitelist
- [x] `@installer` prefix routes requests to a dedicated InstallerAgent sub-agent
- [x] User confirmation required before any installation step
- [x] Full audit log via Watchdog

### Multi-LLM & General
- [x] Kimi K2 + Nemotron via NVIDIA NIM
- [x] Tool-calling fix for NVIDIA NIM (explicit `tool_choice: auto`)
- [x] SOUL.md excluded from QMD memory index
- [x] Multi-LLM wizard with purpose-based backend selection
- [x] `piclaw llm` CLI command for registry management
- [x] LLM fallback order: API 1 → API 2 → local model with notice

---

## Planned

### v0.16 — AgentMail (Email Inbox for Dameon)
- [ ] AgentMail integration: https://www.agentmail.to
- [ ] Dameon gets its own email address (e.g. dameon@agentmail.to)
- [ ] Tools: `email_send()`, `email_list()`, `email_read()`, `email_reply()`
- [ ] Configurable via installer wizard (API key + inbox name)
- [ ] Incoming emails → proactive Telegram notification
- [ ] Use cases: order confirmations, form submissions, alert forwarding

### v0.17 — Emergency Shutdown
- [ ] Switchable smart plug on modem (Shelly Plug S or TP-Link Tapo P110)
- [ ] HA integration already in place (`ha_turn_off`)
- [ ] New tool `emergency_network_off()` with Telegram confirmation
- [ ] Flow: threat detected → "Disconnect network? [Yes/No]" → smart plug off

### v0.18 — Security Tools
- [ ] `tools/network_security.py`: `nmap_scan()`, `whois_lookup()`, `check_open_ports()`
- [ ] Automatic IP blocking via nftables
- [ ] fail2ban integration + status query
- [ ] Abuse report generator

### v0.19 — Tandem Browser + Scrapling (Autonomous Browsing & Scraping)
- [~] **Tandem IN PROGRESS** — browser automation: https://github.com/hydro13/tandem-browser
- [ ] Tools: `browser_open(url)`, `browser_click(selector)`, `browser_read()`, `browser_screenshot()`
- [ ] Agent can autonomously navigate websites, fill forms, and extract content
- [ ] **Scrapling** — adaptive web scraping framework: https://github.com/D4Vinci/Scrapling
  - Cloudflare bypass out of the box (StealthyFetcher)
  - Adaptive element tracking — finds elements even after site redesigns
  - Built-in MCP server (direct Claude integration possible)
  - Tools: `scrape_url()`, `scrape_css()`, `stealth_fetch()`
- [ ] Add `scrapling[fetchers]` to `install.sh` dependencies

### v0.20 — Self-Improving Memory (ClawHub Skill)
- [ ] Dameon learns from explicit corrections ("no, that was wrong")
- [ ] Tiered memory: HOT (≤100 lines, always loaded) / WARM / COLD
- [ ] Pattern promotion: after 3 identical corrections → permanent rule in HOT
- [ ] Self-reflection: evaluate own work after complex tasks and log lessons
- [ ] Conflict resolution: more specific pattern wins (project > domain > global)
- [ ] Inspired by: https://clawhub.ai (Self-Improving Memory skill)

### v0.21 — LLM Improvements
- [ ] Ollama integration (llama3.2:3b as a better local option)
- [ ] Refined thermal routing
- [ ] Optimise `n_threads` for Pi 5

---

## Technical Debt

| # | Issue | Priority |
|---|-------|----------|
| T1 | llama.cpp verbose output (partially fixed) | Medium |
| T2 | Installer tool: allow Dameon to pass custom post-install steps | Low |
