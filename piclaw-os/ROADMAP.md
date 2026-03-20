# PiClaw OS – Roadmap

## Status: v0.15 (März 2026)
Aktueller Stand: Kimi K2 + Nemotron via NVIDIA NIM, Queue-System, Netzwerk-Monitor, Multi-LLM Registry.

---

## ✅ Abgeschlossen

### v0.14 – Stabilität & Parallelität
- [x] Queue-System: Agent verarbeitet Telegram + CLI parallel (asyncio.Queue)
- [x] llama.cpp stdout unterdrücken
- [x] Router-Fallback-Bug behoben (kein ⚠️ mehr nach erfolgreicher Antwort)

### v0.15 – Netzwerk-Monitoring
- [x] `tools/network_monitor.py`: network_scan, port_scan, check_new_devices
- [x] Proaktive Routinen für Netzwerk-Checks
- [x] Neue Geräte im LAN → Telegram-Alert

### Multi-LLM / Sonstiges
- [x] Kimi K2 + Nemotron via NVIDIA NIM
- [x] Tool-Calling Fix für NVIDIA NIM
- [x] SOUL.md aus QMD Memory-Index ausgeschlossen
- [x] Multi-LLM Wizard mit Zweck-Auswahl
- [x] `piclaw llm` CLI-Kommando
- [x] Repo-Struktur bereinigt

---

## 🚀 Geplante Features

### v0.15a – Installer-Tool (Dameon installiert Software autonom)
- [ ] Neues Tool `install_package(source, name)` mit Whitelist vertrauenswürdiger Quellen
- [ ] Unterstützte Quellen: GitHub-Repos (Whitelist), pip, apt
- [ ] Jeder Schritt wird geloggt und dem User angezeigt
- [ ] Immer Bestätigung vom User bevor ausgeführt wird
- [ ] Watchdog überwacht den Installationsprozess
- [ ] Beispiel: "Installiere Tandem aus github.com/hydro13/tandem-browser"

### v0.16 – AgentMail – E-Mail Inbox für Dameon
- [ ] **AgentMail** Integration: https://www.agentmail.to
- [ ] Dameon bekommt eigene E-Mail-Adresse (z.B. dameon@agentmail.to)
- [ ] Tools: `email_send()`, `email_list()`, `email_read()`, `email_reply()`
- [ ] Einrichtbar im Installer (Wizard-Schritt: API-Key + Inbox-Name)
- [ ] Proaktiv: eingehende E-Mails → Benachrichtigung via Telegram
- [ ] Einsatz: Bestellbestätigungen empfangen, Formulare ausfüllen, Alerts weiterleiten

### v0.17 – Notfall-Shutdown
- [ ] Schaltbare Steckdose am Modem (Shelly Plug S oder TP-Link Tapo P110)
- [ ] HA-Integration bereits vorhanden (ha_turn_off)
- [ ] Neues Tool `emergency_network_off()` mit Telegram-Bestätigung
- [ ] Flow: Angriff erkannt → "Netzwerk trennen? [Ja/Nein]" → Steckdose aus

### v0.18 – Security Tools
- [ ] `tools/network_security.py`:
  - `nmap_scan()` – Netzwerk-Scanner
  - `whois_lookup()` – Domain/IP-Info
  - `check_open_ports()` – eigene offene Ports
- [ ] Automatisches IP-Blocking via nftables
- [ ] Fail2ban-Integration + Status-Abfrage
- [ ] Abuse-Report Generator

### v0.19 – Tandem Browser + Scrapling (Autonomes Browsing & Scraping)
- [~] **Tandem IN ARBEIT** – Browser Automation: https://github.com/hydro13/tandem-browser
- [ ] Tools: `browser_open(url)`, `browser_click(selector)`, `browser_read()`, `browser_screenshot()`
- [ ] Agent kann selbstständig Webseiten aufrufen, ausfüllen und auslesen
- [ ] **Scrapling** – Adaptives Web Scraping: https://github.com/D4Vinci/Scrapling
  - Cloudflare Bypass out of the box (StealthyFetcher)
  - Adaptives Element-Tracking – findet Elemente auch nach Website-Redesign
  - MCP-Server eingebaut (direkte Claude-Integration möglich)
  - Tools: `scrape_url()`, `scrape_css()`, `stealth_fetch()`
- [ ] Scrapling als Dependency in install.sh (`pip install "scrapling[fetchers]"`)

### v0.20 – Self-Improving Memory (ClawHub Skill)
- [ ] Dameon lernt aus expliziten Korrekturen ("nein, das war falsch")
- [ ] Tiered Memory: HOT (≤100 Zeilen, immer geladen) / WARM / COLD
- [ ] Pattern Promotion: nach 3x gleicher Korrektur → feste Regel in HOT
- [ ] Self-Reflection: nach komplexen Aufgaben selbst evaluieren und Lesson loggen
- [ ] Conflict Resolution: spezifischeres Pattern gewinnt (Projekt > Domäne > Global)
- [ ] Inspiration: https://clawhub.ai (Self-Improving Memory Skill)

### v0.21 – LLM-Verbesserungen
- [ ] Ollama-Integration (llama3.2:3b als bessere lokale Option)
- [ ] Thermisches Routing verfeinern
- [ ] n_threads auf Pi 5 optimieren

---

## 📋 Technische Schulden
| # | Problem | Priorität |
|---|---------|-----------|
| T1 | llama.cpp verbose Output (teilweise behoben) | Mittel |
| T2 | Installer-Tool damit Dameon Software autonom installieren kann | Hoch |
