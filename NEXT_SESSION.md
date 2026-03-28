# PiClaw OS – Offene Punkte für nächste Session
# Erstellt: 2026-03-28
# Letztes Update: 2026-03-28 (Session 2 – Groq + Marketplace Fixes)

---

## ✅ Gefixt in dieser Session

### 1. registry.py – TypeError 'str' priority (Bug #3)
- `piclaw llm update <n> --priority 9` speicherte Priority als str statt int
- Fix: BackendConfig.__post_init__() coerct alle Felder, registry.update() castet explizit
- Datei: `piclaw/llm/registry.py`

### 2. uvicorn WS-Ping – 1011 keepalive timeout
- Uvicorn hat eigenen Ping (20s Timeout) der bei langen Operationen killt
- Fix: ws_ping_interval=None, ws_ping_timeout=None in beiden uvicorn.run()-Calls
- App-Keepalive-Interval: 20s → 10s
- Datei: `piclaw/api.py`

### 3. Groq Tool-Calling – Text-JSON statt native tool_calls
- llama-3.3-70b-versatile gibt Tool-Calls manchmal als JSON-Text aus
- Fix: _extract_text_tool_calls() Fallback-Parser (3 Formate erkannt)
- Datei: `piclaw/llm/api.py`

### 4. Willhaben Standortfilter
- location-Parameter wurde nie übergeben → immer österreichweit
- Fix A: areaId als Query-Parameter mit statischem Mapping (30+ Einträge)
- Fix B: _fetch_willhaben_area_id() Scrapling-Fallback für unbekannte Orte
- Fix C: _parse_willhaben_html() HTML-Fallback wenn JSON-API versagt
- Datei: `piclaw/tools/marketplace.py`

### 5. Städtenamen als Location erkennen
- _detect_marketplace_intent() extrahierte nur PLZ, nicht Stadtnamen
- Fix: _KNOWN_CITIES Liste mit 40+ Städten (Österreich + Deutschland)
- Datei: `piclaw/agent.py`

### 6. Einheitliche _fetch_html Kaskade
- Kleinanzeigen hatte nur bare aiohttp, eBay hatte eigene Kaskade
- Fix: _fetch_html(url, label) für alle Plattformen: Scrapling → aiohttp → Tandem
- Datei: `piclaw/tools/marketplace.py`

### 7. CLAUDE_REBUILD.md aktualisiert
- Tool-Inventar vollständig: 74 Tools in 19 Modulen dokumentiert
- Version 0.15.1 → 0.15.2

---

## 🔧 Noch zu testen (auf dem Pi)

### A. Groq als Primary ← PRIORITÄT
```bash
piclaw update
piclaw
> Bist du da?
```
Log prüfen: `tail -f /var/log/piclaw/agent.log`
Erwartete Zeile: `Response from 'groq-fallback' (NNNms)`
Problem bisher: Tool-Calls kamen als Text-JSON → jetzt gefixt

### B. Willhaben Standortfilter
```
> Suche nach Mofas in Graz auf willhaben.at
```
Erwartung: Ergebnisse aus Graz/Steiermark, nicht österreichweit
Log prüfen: `Willhaben Standortfilter: Graz → areaId=601`
ACHTUNG: areaId=601 für Graz ist educated guess – falls falsch, Scrapling-
Fallback greift und ermittelt echte ID dynamisch.

### C. Kleinanzeigen mit Stadtname
```
> Suche auf Kleinanzeigen nach einem Rennrad in Hamburg
```
Erwartung: Ergebnisse aus Hamburg, URL mit /s-hamburg/rennrad/

### D. Tool-Calling generell
```
> Wie warm ist der Pi gerade?
> Zeig mir alle laufenden Services
> Suche auf eBay nach einem Raspberry Pi 5
```

---

## 📋 Roadmap (noch nicht angefangen)

1. **Cron-Job Sub-Agent** testen
   Test: "Erstelle einen Agenten der jeden Tag um 8 Uhr die Temperatur meldet"

2. **Netzwerk-Monitoring** testen
   Voraussetzung: `sudo apt install nmap -y`
   Test: "Überwache mein Netzwerk auf neue Geräte"

3. **fail2ban Integration** (v0.17)

4. **Emergency Shutdown** via schaltbare Steckdose (v0.16)

5. **Queue System v0.14** – parallele CLI + Telegram Anfragen

6. **Willhaben areaId verifizieren** – echte IDs via Chrome Network-Tab prüfen
   URL: https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=Roller
   Filter auf Graz setzen → Network-Tab → webapi Request → areaId ablesen

7. **Camera-Tools registrieren** (piclaw/hardware/camera.py hat TOOL_DEFS
   aber ist nicht in agent.py _build_tools() eingetragen)

---

## 🔑 Wichtige Infos

- Pi IP: 192.168.178.120
- Primäres LLM: Groq / llama-3.3-70b-versatile (Prio 9) ← neu
- Sekundär: NVIDIA NIM / moonshotai/kimi-k2.5 (Prio 7)
- Lokales Fallback: Ollama / qwen2.5:1.5b (wenn explizit konfiguriert)
- Letzter erfolgreicher `piclaw doctor`: alle grün, CPU 49-51°C
- github_token in /etc/piclaw/config.toml eintragen für `piclaw update`!
  ```toml
  [updater]
  repo_url = "https://github.com/RainbowLabsInc/PiClawOS"
  github_token = "ghp_..."
  ```
