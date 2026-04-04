# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-04-04 (Session 8)
# Version: 0.15.4

---

## ⚠️ SOFORT ERLEDIGEN (vor nächster Nutzung)

### 1. `sudo git pull + restart` auf der Pi durchführen
Die Commits 830e297..5da8724 sind auf GitHub aber noch nicht vollständig aktiv.
```bash
cd /opt/piclaw && sudo git pull
sudo systemctl restart piclaw-agent piclaw-api
```
Danach: `POST /api/subagents/mp-restore` aufrufen (oder via Browser-Console):
```javascript
fetch('http://192.168.178.120:7842/api/subagents/mp-restore', {
  method: 'POST',
  headers: {'Authorization': 'Bearer REDACTED_PICLAW_TOKEN'}
}).then(r=>r.json()).then(console.log)
```

### 2. marketplace_monitors.json prüfen
Nach dem Neustart sicherstellen dass Handler registriert sind:
```bash
cat /etc/piclaw/marketplace_monitors.json
# Sollte _mp_monitor_gartentisch enthalten
```
Falls leer → manuell schreiben:
```bash
sudo python3 -c "
import json
from pathlib import Path
p = Path('/etc/piclaw/marketplace_monitors.json')
p.write_text(json.dumps({'_mp_monitor_gartentisch': {
  'query': 'Gartentisch', 'platforms': ['kleinanzeigen'],
  'location': None, 'radius_km': None, 'max_price': None
}}, indent=2))
print('OK')
"
```

### 3. API-Token rotieren (vor Release)
`REDACTED_PICLAW_TOKEN` → in mehreren Sessions verwendet

### 4. GitHub PAT rotieren (vor Release)
`REDACTED_GITHUB_PAT` → wurde im Chat verwendet

---

## 🔧 Bekannte Issues / Offene Features

### 5. /api/shell Endpoint entfernen (vor Release)
**Datei:** `piclaw-os/piclaw/api.py`
**Suche:** `@app.post("/api/shell")` → gesamten Block löschen
**Test:** `curl -X POST http://localhost:7842/api/shell` → 404

### 6. Sub-Agent via API → Daemon-Registry-Reload fehlt
Registry-Reload via IPC fehlt → Roadmap v0.18
**Workaround:** piclaw-agent neustarten nach API-basierten Agent-Änderungen

### 7. Monitor_Gartentisch Handler nach Neustart prüfen
Nach git pull + restart läuft `_restore_marketplace_monitor_handlers()`.
Prüfen ob Handler korrekt registriert wurde:
```bash
curl -s -H "Authorization: Bearer TOKEN" \
  http://localhost:7842/api/subagents/mp-restore -X POST
# Sollte {"restored": true, "handlers": ["_mp_monitor_gartentisch"]} zurückgeben
```

---

## ✅ Session 8 – komplett erledigt (2026-04-04)

### Bug-Fixes (gepusht, noch nicht vollständig deployt)

- **metrics.py AttributeError:** `cfg.config_dir` existiert nicht in PiClawConfig
  → Fix: `CONFIG_DIR` Modul-Konstante direkt importiert ✅
  Commit: `da623de` | Datei: `piclaw-os/piclaw/metrics.py`

- **LLM Health Monitor Cross-Prozess:** `/api/llm/health` zeigte immer
  „Health Monitor nicht aktiv" weil daemon und api separate Prozesse sind.
  → Fix: Monitor schreibt Status in `/etc/piclaw/llm_health_status.json` ✅
  Commit: `da623de` | Datei: `piclaw-os/piclaw/llm/health_monitor.py` + `api.py`

- **status_dict() ohne direct_tool:** GET /api/subagents zeigte direct_tool=null ✅
  Commit: `a669a0a` | Datei: `piclaw-os/piclaw/agents/runner.py`

- **Marketplace Monitor Stale-Cleanup:** `_restore_marketplace_monitor_handlers()`
  löschte marketplace_monitors.json Einträge wenn Daemon nach Delete+Recreate
  eines Agenten neu startete → Handler nie registriert → [ERROR] Direct tool not found ✅
  Commit: `e553135` | Datei: `piclaw-os/piclaw/agent.py`

- **Kleinanzeigen Radius ignoriert:** `?radius=N` Query-Parameter wird von
  Kleinanzeigen komplett ignoriert. Echtes Format: `/k0l{LOC_ID}r{RADIUS}`.
  Location-ID über `s-ort-empfehlungen.json?query={PLZ}` aufgelöst.
  Resultat: 1.542 DE-weit → 42 lokale Ergebnisse ✅
  Commit: `5da8724` | Datei: `piclaw-os/piclaw/tools/marketplace.py`

### Neue Features

- **PATCH /api/subagents/{name}:** Live-Update von direct_tool, schedule, etc.
  ohne Delete+Recreate ✅ Commit: `da623de`

- **POST /api/subagents/mp-restore:** Handler ohne Daemon-Neustart neu registrieren ✅
  Commit: `e553135`

- **direct_check Action-Typ:** Tokenloser Routine-Check (cpu_temp, disk, ram,
  new_devices, ha_state) ohne LLM-Aufruf ✅
  Commit: `830e297` | Dateien: `proactive.py`, `routines.py`

### Live auf Pi geändert (via API, kein Git Pull nötig)

- Monitor_Netzwerk: `direct_tool=check_new_devices` gesetzt (tokenlos) ✅
- Monitor_Gartentisch: Neu angelegt mit `direct_tool=_mp_monitor_gartentisch` ✅
- temp_check Routine: auf `direct_check` Action umgestellt ✅

---

## ✅ Session 7 – komplett erledigt

- Netzwerk-Monitor Heartbeat ✅
- Marketplace direct_tool + format_results_telegram mit Links ✅
- daemon.py stop-Event Race Condition ✅
- Crawler Link-Extraktion ✅
- MessagingHub.send_to() ✅
- PLZ-Extraktion aus Query ✅

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.16 | **LLM Autonomie** – Dameon sucht neue Backends selbst 🧠 |
| v0.17 | Emergency Shutdown via schaltbare Steckdose |
| v0.18 | Queue System + Registry-Reload via IPC (löst Sub-Agent API-Problem) |
| v0.19 | Willhaben Kategorie-Filter |
| v0.20 | Kamera-Tools vollständig |
| **v1.0** | **Release** |

---

## 🏠 HA-Entities (aktuell bekannt)

```
light.licht_fernsehzimmer_switch_0       (Licht Fernsehzimmer)
light.licht_schlafzimmer_switch_0        (Licht Schlafzimmer)
light.licht_esszimmer_switch_0           (Licht Esszimmer)
light.shellyplus1_08b61fd0b64c_switch_0  (Licht Gäste WC)
switch.licht_kuche_switch_0              (Licht Küche)
switch.fernseher                         (Fernseher)
switch.aquarium_licht                    (Aquarium Licht)
cover.shellyplus2pm_d48afc41a22c         (Rolladen Büro)
cover.shellyplus2pm_c82e180c7a1c         (Rolladen Schlafzimmer)
cover.rolladen_kuche                     (Rolladen Küche)
cover.rollladen_kinderzimmer             (Rollladen Kinderzimmer)
```

## 🤖 LLM Backends (aktuell)

```
[10] groq-actions     llama-3.3-70b-versatile    Groq       action, home_automation
[ 9] groq-fallback    kimi-k2-instruct            Groq       general, reasoning
[ 8] nemotron-nvidia  llama-4-maverick-17b        NVIDIA NIM general, fast
[ 7] openai-default   llama-3.3-70b-instruct      NVIDIA NIM general (Fallback)
     lokal            gemma-2b-q4                 llama.cpp  letzter Fallback
```

## 🤖 Sub-Agents (aktuell)

```
Monitor_Netzwerk    interval:300    direct_tool=check_new_devices        PROTECTED, TOKENLOS
Monitor_Gartentisch interval:3600   direct_tool=_mp_monitor_gartentisch  TOKENLOS
CronJob_0715        cron:15 7 * * * LLM (täglicher Systembericht, gewollt)
```
