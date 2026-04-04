# PiClaw OS — Agent-Architektur & Kaskadierung
# Version: v0.15.5 | Stand: 2026-04-04
# Zweck: Referenz für KI-Assistenten in zukünftigen Dev-Sessions

---

## 1. Zwei-Prozess-Architektur

```
┌─────────────────────────────────┐   ┌────────────────────────────────────┐
│        piclaw-api               │   │         piclaw-agent (Daemon)      │
│  Port 7842                      │   │                                    │
│  - REST API + WebSocket         │   │  - Sub-Agent Scheduler             │
│  - Telegram Empfang/Antwort     │   │  - Proaktive Routinen              │
│  - Web-Dashboard                │   │  - LLM Health Monitor              │
│  - start_sub_agents=False       │   │  - Heartbeat                       │
│                                 │   │  - IPC trigger polling (1s)        │
│  _agent (API-Instanz)           │   │  _agent (Daemon-Instanz)           │
└────────────┬────────────────────┘   └──────────────┬─────────────────────┘
             │                                        │
             └──────────── subagents.json ────────────┘
                          /etc/piclaw/subagents.json
                          (shared auf Disk, nicht im RAM)
```

**WICHTIG:** API und Daemon sind separate Prozesse. RAM-Objekte werden NICHT geteilt.
Kommunikation nur via: subagents.json (Registry), ipc/*.trigger (Run-Now), JSON-Dateien.

---

## 2. Sub-Agent Typen

### 2a. direct_tool Agenten (tokenlos, empfohlen)

Führt ein einzelnes Tool direkt aus – ohne LLM-Aufruf. Neustart-sicher.

```
Runner._execute(agent)
  → agent.direct_tool ist gesetzt
  → _direct_tool_call(agent)
     ├─ "marketplace_monitor" → _run_marketplace_monitor(agent)
     │   → json.loads(agent.mission) → marketplace_search() direkt
     ├─ "check_new_devices"   → handler() direkt
     └─ "direct_check"        → _run_direct_check(agent)
         → cpu_temp / disk / ram / new_devices / ha_state
```

**Vorteile:** 0 LLM-Calls, schnell, stabil, neustart-sicher
**Verwendung:** Monitoring-Agenten, periodische Checks

### 2b. LLM Agentic Loop (für komplexe Aufgaben)

Führt einen vollständigen LLM-Dialog mit Tool-Calls durch.

```
Runner._execute(agent)
  → agent.direct_tool ist None
  → _agentic_loop(agent)
     → System-Prompt aus agent.mission
     → LLM.chat(messages) mit Tool-Definitionen
     → Tool-Calls ausführen bis max_steps oder done
     → Ergebnis via Telegram
```

**Verwendung:** CronJob_0715 (täglicher Bericht), komplexe Einmal-Tasks

---

## 3. marketplace_monitor (neustart-sicher)

Das wichtigste direkte Tool. Parameter stehen als JSON in `agent.mission`.

### Format

```json
{
  "query": "Gartentisch",
  "platforms": ["kleinanzeigen"],
  "location": "21224",
  "radius_km": 20,
  "max_price": null,
  "max_results": 10
}
```

### Unterstützte Plattformen

| Platform-String | Seite | Besonderheit |
|---|---|---|
| `kleinanzeigen` | kleinanzeigen.de | Radius via Location-ID URL |
| `ebay` | ebay.de | `_stpos=PLZ&_sadis=km` |
| `willhaben` | willhaben.at | areaId aus statischer Map |
| `egun` | egun.de | Deutschlandweit, kein Radius |
| `troostwijk` | troostwijkauctions.com | Auktionen |
| `web` | Allgemeine Websuche | Fallback |

### Kleinanzeigen Radius (INV_030)

```
FALSCH: /s-{PLZ}/{query}/k0?radius=20     ← wird ignoriert!
RICHTIG: /s-{PLZ}/{query}/k0l{LOC_ID}r{RADIUS_KM}

Location-ID via:
GET https://www.kleinanzeigen.de/s-ort-empfehlungen.json?query={PLZ}
→ {"_0":"Deutschland","_2811":"21224 Rosengarten"}
→ LOC_ID = 2811 (Key ohne "_" Prefix)
```

### Seen-Filter

Neue Inserate werden gegen `/etc/piclaw/marketplace_seen.json` geprüft.
Erster Lauf = alle aktuellen Angebote (normal!). Ab dem 2. Lauf nur Neuzugänge.
`__NO_NEW_RESULTS__` = stilles Token → kein Telegram-Spam.

---

## 4. Syntax für Dameon-Chat

### Einmalige Suche
```
"Suche Gartentisch auf Kleinanzeigen in 21224 Umkreis 20km"
"Suche Sauer 505 auf eGun"
→ schedule=once, kein Agent in Registry
```

### Dauerhafter Monitor
```
"Überwache Kleinanzeigen nach Gartentischen in 21224 Umkreis 20km"
"Beobachte eGun nach Sauer 505"
"Richte eine Suche ein für Sonnenschirme auf Kleinanzeigen"
→ schedule=interval:3600, direct_tool=marketplace_monitor
→ mission=JSON mit Suchparametern
→ Telegram bei neuen Inseraten
```

**WICHTIG (INV_036):** Ortsnamen gehören in `location`, NICHT in `query`!
- FALSCH: query="Gartentisch Rosengarten"
- RICHTIG: query="Gartentisch", location="21224"

### Monitor löschen
```
"Lösch den Monitor_Gartentisch"
"Stopp den Monitor_Sauer505"
```

---

## 5. LLM Routing & Kaskadierung

```
User-Nachricht
     │
     ▼
Stage 0: Regex-Classifier (<1ms)
  HA-Befehle → groq-actions direkt (kein Token für Routing)
     │
     ▼
Stage 1: Pattern-Classifier (~0ms)
  25 Muster → tags zuweisen (action, general, reasoning, fast)
     │
     ▼
Stage 2: LLM-Classifier (nur wenn confidence < 0.65)
     │
     ▼
find_by_tags() → Priority-Reihenfolge:
  [10] groq-actions    llama-3.3-70b-versatile  (action, home_automation)
  [ 9] groq-fallback   kimi-k2-instruct          (general, reasoning)
  [ 8] groq-gptoss     openai/gpt-oss-120b        (general, reasoning, fast)
  [ 6] nemotron-nvidia llama-4-maverick            (general, fast)
  [ 5] openai-default  llama-3.3-70b@nvidia       (general, Fallback)
       lokal           qwen3-1.7b-q4_k_m          (letzter Fallback, offline)
```

### Thermal-Routing (bei CPU-Temperatur)

```
COOL  (<55°C) → alle Backends verfügbar
WARM  (<65°C) → bevorzugt kleinere Modelle
HOT   (<75°C) → nur fast-tagged Backends
CRITICAL (<85°C) → nur lokal
EMERGENCY (>85°C) → lokal + Telegram-Alert
```

---

## 6. Freie Websuche / Externe Informationen

Dameon kann aktiv Informationen aus dem Web holen via:

### http_fetch Tool
```python
# Einfacher HTTP-GET
http_fetch(url="https://example.com")
→ gibt HTML/JSON zurück
```

### marketplace_search mit platform="web"
```python
marketplace_search(query="...", platforms=["web"])
→ generische Websuche
```

### Für komplexere Webrecherche (zukünftig v0.16)
- Headless Browser via Tandem (Port 8765 lokal)
- browser_open → browser_snapshot → browser_click

### Websuche für Self-Healing
Dameon kann selbst neue LLM-Anbieter finden:
```
1. http_fetch("https://openrouter.ai/api/v1/models") → JSON mit Modellen
2. Bewertet Latenz, TPM, Tool-Support
3. llm_add() → neues Backend registrieren
4. llm_test() → validieren
```

---

## 7. IPC – Wie API und Daemon kommunizieren

```
API → Daemon: write_run_now(agent_id)
  → schreibt /etc/piclaw/ipc/run_now_{agent_id}.trigger

Daemon pollt: poll_triggers() alle 1 Sekunde
  → liest trigger-Dateien
  → sa_runner.start_agent(agent_id)

PROBLEM: Daemon kennt nur Agenten die beim Start geladen wurden.
Nach API-basierten Neuanlagen → sudo systemctl restart piclaw-agent
→ Dauerlösung: v0.18 IPC-Reload
```

---

## 8. Kritische Invarianten (Kurzform)

| INV | Was | Warum |
|---|---|---|
| 030 | Kleinanzeigen: k0l{LOC_ID}r{RADIUS} | ?radius= wird ignoriert |
| 031 | marketplace_monitors.json: NICHT löschen | Restore bricht sonst |
| 035 | marketplace_monitor: mission als JSON | Neustart-sicher, kein Closure |
| 036 | Ortsnamen in location, nicht query | Sonst falsche Suchergebnisse |
| 037 | Neuer Agent → Daemon-Neustart nötig | IPC-Reload fehlt bis v0.18 |

Vollständige Invarianten: CLAUDE_REBUILD.md (INV_001 – INV_037)

---

## 9. Aktive Sub-Agenten (Stand 2026-04-04)

| Agent | ID | direct_tool | Schedule | Plattform |
|---|---|---|---|---|
| Monitor_Netzwerk | 59dcf571 | check_new_devices | 5 Min | intern (PROTECTED) |
| Monitor_Gartentisch | c782e62e | marketplace_monitor | 1h | Kleinanzeigen |
| Monitor_Sonnenschirm | 4b62c29e | marketplace_monitor | 1h | Kleinanzeigen |
| Monitor_Sauer505 | 6d9eca05 | marketplace_monitor | 1h | eGun |
| CronJob_0715 | cbe61af9 | (LLM) | 07:15 tägl. | – |

---

## 10. Debugging-Quickstart

```bash
# Live-Logs (Fehler + wichtige Events)
tail -f /var/log/piclaw/agent.log | grep -E "ERROR|WARNING|Monitor|direct_tool|marketplace"

# Sub-Agent manuell triggern
curl -s -X POST http://localhost:7842/api/subagents/Monitor_Gartentisch/run \
  -H "Authorization: Bearer $(cat /etc/piclaw/api_token)"

# marketplace_monitors.json prüfen (sollte leer/weg sein nach Refactor)
cat /etc/piclaw/marketplace_monitors.json 2>/dev/null || echo "nicht vorhanden (ok)"

# Qwen3 Modell prüfen
ls -lh /etc/piclaw/models/

# LLM Health
curl -s http://localhost:7842/api/llm/health -H "Authorization: Bearer $(cat /etc/piclaw/api_token)" | python3 -m json.tool
```
