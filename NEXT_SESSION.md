# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-03-28 (Session 6)
# Version: 0.15.4

---

## ⚠️ VOR RELEASE (Pflicht)

### 1. /api/shell Endpoint entfernen
**Datei:** `piclaw-os/piclaw/api.py`
**Suche:** `@app.post("/api/shell")` → gesamten Block löschen
**Test:** `curl -X POST http://localhost:7842/api/shell` → 404

### 2. Groq API Key aus Git-History tilgen
Key `gsk_ZVWVs...` wurde im Chat verwendet

### 3. API-Token rotieren
`L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA` → vor Release erneuern

---

## 🔧 Bekannte Issues / Offene Features

### 4. Sub-Agent via API → Daemon-Neustart nötig
Registry-Reload via IPC fehlt → Roadmap v0.18

### 5. Marketplace-Links fehlen in Telegram
LLM reformuliert marketplace_search Output und lässt URLs weg.
Fix: Monitor_Gartentisch als `direct_tool` implementieren (format_results_telegram direkt)

### 6. LLM Health Monitor: Registry-Attribut prüfen
daemon.py bindet Monitor via `agent.llm.registry` – nach Neustart prüfen ob
"LLM Health Monitor gestartet" im agent.log erscheint

---

## ✅ Session 6 – komplett erledigt

### Home Assistant
- Token in config.toml `[homeassistant]` eingetragen ✅
- ha_mod.start() VOR Agent(_cfg) in api.py → 11 HA-Tools registriert ✅
- HA-Shortcut: Licht/Schalter ohne LLM (0 Token, <100ms) ✅
- Fuzzy Entity-Suche: "Fernsehzimmer" → light.licht_fernsehzimmer_switch_0 ✅
- turn_off Typo behoben (turn_of → turn_off) ✅
- piclaw doctor zeigt: Home Assist ✅ ✅

### Smart LLM Routing
- groq-actions Backend: llama-3.3-70b-versatile, Priority 10, 30k TPM ✅
- Regex-Classifier Stage 0: HA-Befehle <1ms klassifiziert ✅
- Tags: action, home_automation, query ✅

### LLM Health Monitor
- health_monitor.py: automatische Selbstheilung ✅
- 404 → Provider /models API → Preferred-Liste → auto-update ✅
- 429 → Priorität senken, nach 1h wiederherstellen ✅
- 500/3× → deaktivieren + Telegram ✅
- In daemon.py als Background-Task eingebunden ✅

### NVIDIA NIM
- nemotron-nvidia: nvidia/llama-3.1-nemotron-70b-instruct (404) ✅
- Ersetzt durch: meta/llama-4-maverick-17b-128e-instruct ✅
- Test: OK 500ms ✅

### Bugfixes
- Doppel-Telegram: start_sub_agents=False in api.py ✅
- Monitor_Gartentisch Netzwerk-Heartbeat → Heartbeat-Guard auf direct_tool ✅
- _intentionally_silent Flag statt result="" ✅
- Direct-Tool leeres Ergebnis → __NO_NEW_DEVICES__ ✅
- CalDAV-Skill entfernt (Context-Größe) ✅
- nemotron-nvidia deaktiviert (vorübergehend, jetzt gefixt) ✅

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.16 | **LLM Autonomie** – Dameon sucht neue Backends selbst 🧠 |
| v0.17 | Emergency Shutdown via schaltbare Steckdose |
| v0.18 | Queue System + Registry-Reload via IPC |
| v0.19 | Willhaben Kategorie-Filter + Marketplace-Links Fix |
| v0.20 | Kamera-Tools vollständig |
| **v1.0** | **Release** |
| v1.1 | Mehrsprachigkeit (DE/EN/ES) |

---

## 🛠️ DEV-Tool (vor Release entfernen!)

```javascript
window.pi = async (cmd, timeout=30) => {
    const r = await fetch('/api/shell', {
        method: 'POST',
        headers: new Headers({'Authorization': 'Bearer L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA', 'Content-Type': 'application/json'}),
        body: JSON.stringify({cmd, timeout})
    });
    const d = await r.json();
    return d.stdout || d.stderr || d.error;
};
```

## 🏠 HA-Entities (aktuell bekannt)

```
light.licht_fernsehzimmer_switch_0   (Licht Fernsehzimmer)
light.licht_schlafzimmer_switch_0    (Licht Schlafzimmer)
light.licht_esszimmer_switch_0       (Licht Esszimmer) – aktuell: on
light.shellyplus1_08b61fd0b64c_switch_0 (Licht Gäste WC)
switch.licht_kuche_switch_0          (Licht Küche)
switch.fernseher                     (Fernseher) – aktuell: on
switch.aquarium_licht                (Aquarium Licht)
cover.shellyplus2pm_d48afc41a22c     (Rolladen Büro)
cover.shellyplus2pm_c82e180c7a1c     (Rolladen Schlafzimmer)
cover.rolladen_kuche                 (Rolladen Küche)
cover.rollladen_kinderzimmer         (Rollladen Kinderzimmer)
```

## 🤖 LLM Backends (aktuell)

```
[10] groq-actions     llama-3.3-70b-versatile    Groq       action, home_automation
[ 9] groq-fallback    kimi-k2-instruct            Groq       general, reasoning
[ 8] nemotron-nvidia  llama-4-maverick-17b        NVIDIA NIM general, fast
[ 7] openai-default   llama-3.3-70b-instruct      NVIDIA NIM general (Fallback)
     lokal            gemma-2b-q4                 llama.cpp  letzter Fallback
```
