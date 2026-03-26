# PiClaw OS — Roadmap

## Status: v0.15.1 (March 2026)

Aktuelle Produktion: Dameon läuft stabil auf Raspberry Pi 5.
Marketplace-Suche funktioniert (Kleinanzeigen + eBay via Scrapling).
Multi-LLM Router aktiv: NVIDIA NIM (Nemotron 70B + Kimi K2.5), lokal Gemma 2B.
Auto-Detect für 6 LLM-Provider. `piclaw update` und `piclaw debug` operativ.

---

## ✅ Abgeschlossen

### v0.15.1 — Stabilisierung & Bugfixes (März 2026)
- [x] Marketplace-Suche vollständig funktionsfähig (PLZ + Radius auf Kleinanzeigen.de)
- [x] eBay via Scrapling → aiohttp → Tandem Kaskade
- [x] Multi-Provider Auto-Detect: Anthropic / NVIDIA NIM / Gemini / Fireworks / OpenAI / Mistral
- [x] `piclaw update` — Self-Update via git pull + Neustart
- [x] `piclaw debug` — Diagnose-Scripts (tests/debug/)
- [x] WebSocket Keepalive — kein Timeout bei langen Operationen
- [x] NVIDIA NIM tool_choice Fix (Error 400 behoben)
- [x] Gemini Endpoint Fix (/v1beta/openai/chat/completions)
- [x] Editable Install via Symlink — git pull reicht
- [x] Sudoers-Regel für piclaw-User
- [x] Installer: piclaw.conf optional, GITHUB_TOKEN Support
- [x] Security: Command Injection fixes (api.py, network.py, services.py, updater.py)
- [x] Performance: Regex precompile in agent.py, marketplace.py, network_monitor.py
- [x] Modern Python: Optional[x] → x | None, collections.abc überall
- [x] Blocking I/O in asyncio.to_thread() ausgelagert

### v0.19 — Tandem Browser + Scrapling
- [x] Tandem Browser Bridge (Port 8765)
- [x] Scrapling — stealth HTTP, Cloudflare-Bypass
- [x] eBay nutzt Scrapling als primären Fetcher

### v0.16 — AgentMail
- [x] AgentMail Integration (agentmail.to)
- [x] Tools: email_send, email_list, email_read, email_reply
- [x] Wizard-Integration

### v0.15a — Installer Sub-Agent
- [x] InstallerAgent mit Whitelist und Audit-Log
- [x] @installer Prefix-Routing

### v0.15 — Netzwerk-Monitoring
- [x] network_monitor.py: network_scan, port_scan, check_new_devices
- [x] Neue Geräte → Telegram-Alert

### v0.18 — Network Security Tools
- [x] network_security.py: tarpit, emergency shutdown, whois

### v0.14 — Parallelverarbeitung
- [x] Queue-System: Telegram + CLI parallel

### Multi-LLM & Allgemein
- [x] Kimi K2 + Nemotron 70B via NVIDIA NIM
- [x] SOUL.md aus QMD Memory-Index ausgeschlossen
- [x] piclaw llm CLI für Registry-Verwaltung
- [x] Doctor-Debug (piclaw debug) mit pytest-Integration

---

## 🚧 Nächste Schritte (Release-Vorbereitung)

### v0.15.2 — Release Candidate
- [ ] CLAUDE_REBUILD.md auf v0.15.1 Stand bringen
- [ ] Neuinstallations-Test sauber durchlaufen
- [ ] eBay Live-Test mit Scrapling verifizieren
- [ ] Gemini Live-Test (Quota-Problem lösen)
- [ ] piclaw doctor — alle Checks grün auf frischer Installation
- [ ] Doctor-Debug: Testscripte für häufige Fehlerquellen
- [ ] Dashboard Version-Anzeige auf v0.15.1 aktualisieren
- [ ] piclaw update — GitHub Token-Problem lösen (SSH Key oder Token in Config)

### v0.16.1 — AgentMail Live-Test
- [ ] AgentMail API-Key konfigurieren
- [ ] Eingehende Mails → Telegram-Weiterleitung testen

---

## 📋 Geplant

### v0.17 — Emergency Shutdown
- [ ] Schaltbare Steckdose am Modem (Shelly / TP-Link Tapo)
- [ ] Tool: emergency_network_off() mit Telegram-Bestätigung
- [ ] HA-Integration bereits vorhanden

### v0.20 — Self-Improving Memory
- [ ] Dameon lernt aus Korrekturen
- [ ] Tiered Memory: HOT / WARM / COLD
- [ ] Pattern-Promotion nach 3 Korrekturen
- [ ] Inspiration: https://clawhub.ai

### v0.21 — LLM Verbesserungen
- [ ] Ollama (llama3.2:3b lokal)
- [ ] n_threads Pi 5 optimieren

### v0.22 — Token Effizienz
- [ ] Tool Routing (Classifier, ~3000 Token gespart)
- [ ] Lazy Memory Injection
- [ ] Single Model Instance (~2 GB RAM gespart)
- [ ] Ziel: 60% weniger Token bei einfachen Nachrichten

### v0.23 — Marketplace Erweiterungen
- [ ] Willhaben.at, Ricardo.ch
- [ ] Plattform-übergreifender Preisvergleich
- [ ] Preis-History / Benachrichtigung

---

## 🔧 Technical Debt

| # | Problem | Priorität |
|---|---------|-----------|
| T1 | llama.cpp verbose Output | Medium |
| T2 | piclaw update braucht GitHub Token | Medium |
| T3 | Dashboard zeigt noch v0.9 | Low |
| T4 | boot/ pyproject.toml nicht sync | Low |

---

## 🎯 Release-Kriterien v1.0

- [ ] Frische Installation in unter 10 Minuten
- [ ] piclaw doctor zeigt alles grün
- [ ] Marketplace (Kleinanzeigen + eBay) zuverlässig
- [ ] Mind. 1 Cloud-LLM ohne Probleme konfigurierbar
- [ ] Telegram-Benachrichtigungen funktionieren
- [ ] piclaw update ohne manuelle Schritte
- [ ] Alle kritischen Tests grün
