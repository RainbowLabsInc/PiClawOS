# PiClaw OS – Roadmap

## Status: v0.13.3 (März 2026)
Aktueller Stand: Grundsystem läuft, lokales LLM (Gemma 2B) antwortet, Telegram funktioniert.

---

## 🔧 Offene Bugs / technische Schulden

| # | Problem | Priorität |
|---|---------|-----------|
| T1 | llama.cpp gibt verbose Output ins Terminal (llama_context, llama_kv_cache) | Mittel |
| T2 | Agent verarbeitet Anfragen sequenziell (CLI + Telegram blockieren sich gegenseitig) | Hoch |
| T3 | CLI nutzt noch keinen WebSocket-API-Chat auf aktuellem Pi (nur im neuen Build) | Hoch |

---

## 🚀 Geplante Features

### v0.14 – Stabilität & Parallelität
- [ ] **Queue-System**: Agent verarbeitet Telegram + CLI parallel (asyncio.Queue)
- [ ] **llama.cpp stdout unterdrücken**: stderr nach /dev/null im LocalBackend
- [ ] **CLI via WebSocket** testen und finalisieren (bereits im Build)

### v0.15 – Netzwerk-Monitoring
- [ ] `tools/network_monitor.py` mit 4 Funktionen:
  - `scan_devices()` – alle Geräte im LAN per nmap
  - `check_new_devices()` – unbekannte Geräte → Telegram-Alert
  - `port_scan(ip)` – offene Ports eines Geräts
  - `ping_watchdog()` – wichtige Hosts überwachen
- [ ] Proaktive Routine `network_check` alle 15 Minuten
- [ ] Schwellwert: zu viele Verbindungsversuche → Telegram-Rückfrage

### v0.16 – Notfall-Shutdown
- [ ] Schaltbare Steckdose am Modem (Shelly Plug S oder TP-Link Tapo P110)
- [ ] HA-Integration bereits vorhanden (ha_turn_off)
- [ ] Neues Tool `emergency_network_off()` mit Telegram-Bestätigung
- [ ] Flow: Angriff erkannt → "Netzwerk trennen? [Ja/Nein]" → Steckdose aus

### v0.17 – Security Tools
- [ ] `tools/network_security.py`:
  - `nmap_scan()` – Netzwerk-Scanner
  - `whois_lookup()` – Domain/IP-Info
  - `check_open_ports()` – eigene offene Ports
- [ ] Automatisches IP-Blocking via nftables
- [ ] Fail2ban-Integration + Status-Abfrage
- [ ] Abuse-Report Generator

### v0.18 – Tandem Browser (Autonomes Browsing)
- [ ] **Tandem** als autonomes Browser-Tool einbinden: https://github.com/hydro13/tandem-browser
- [ ] Neues Tool `browser_open(url)`, `browser_click(selector)`, `browser_read()`, `browser_screenshot()`
- [ ] Agent kann damit selbstständig Webseiten aufrufen, ausfüllen und auslesen
- [ ] Einsatzbeispiele: Preisvergleiche, Login-Flows, Formulare, Web-Scraping ohne API
- [ ] Integration in bestehenden Tool-Dispatcher (`agent.py._build_tools()`)

### v0.19 – LLM-Verbesserungen
- [ ] Ollama-Integration testen (llama3.2:3b als bessere lokale Option)
- [ ] Thermisches Routing verfeinern
- [ ] Antwortzeit-Optimierung (n_threads auf Pi 5 optimieren)

---

## ✅ Abgeschlossen (v0.13.x)

- Grundinstallation SD-Card Workflow
- Lokales LLM (Gemma 2B, Phi-3, TinyLlama wählbar)
- Telegram, Discord, MQTT, WhatsApp Adapter
- Home Assistant REST + WebSocket
- Proaktiver Agent (Routinen, Schwellwerte)
- Web-UI (8 Tabs)
- Memory-System (QMD)
- SSH-Wizard (11 Schritte)
- CLI über WebSocket-API (im Build, noch nicht getestet)
- 15+ Bugfixes durch Installationstests

