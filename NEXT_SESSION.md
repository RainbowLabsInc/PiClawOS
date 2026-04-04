# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-04-04 (Session 8B)
# Version: 0.15.5 (in Vorbereitung)

---

## ⚠️ SOFORT ERLEDIGEN

### 1. piclaw-agent neustarten (neue Monitore aktivieren)
Die 3 neuen Monitor-Agenten wurden nach dem letzten Daemon-Start angelegt und
werden erst beim nächsten Neustart vom Daemon erkannt.
```bash
sudo systemctl restart piclaw-agent
```
Danach laufen alle 5 Agenten korrekt:
- Monitor_Netzwerk (check_new_devices, tokenlos)
- Monitor_Gartentisch (marketplace_monitor, Kleinanzeigen 21224, 20km)
- Monitor_Sonnenschirm (marketplace_monitor, Kleinanzeigen 21224, 20km)
- Monitor_Sauer505 (marketplace_monitor, eGun)
- CronJob_0715 (LLM, täglicher Bericht, gewollt)

### 2. piclaw-api neustarten (neuer Code für Chat-Erstellung)
```bash
sudo systemctl restart piclaw-api
```
Danach erstellt Dameon neue Monitore korrekt im marketplace_monitor Format.

### 3. API-Token + GitHub PAT rotieren (vor Release)
- API-Token: L1gFu490BMv_50TFYek6Yveh3FwFfEoW3ycDaCCFsLA
- GitHub PAT: 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

---

## 🔧 Bekannte Issues / Offene Features

### 4. Query-Extraktion verbessern
Dameon extrahiert Ortsnamen in die Query: "Gartentischen Rosengarten" statt "Gartentisch"
Fix: _detect_marketplace_intent() in agent.py – Ortsnamen aus Query entfernen
Datei: piclaw-os/piclaw/agent.py, Funktion _detect_marketplace_intent()

### 5. Neuer Agent → Daemon-Neustart nötig (INV_037)
Bis v0.18 (Queue System + IPC-Reload): nach Anlegen neuer Agenten manuell neustarten.

### 6. /api/shell Endpoint entfernen (vor Release)

### 7. Troostwijk testen
Monitor noch nicht getestet. Syntax: "Überwache Troostwijk nach [Artikel]"

---

## ✅ Session 8B – komplett erledigt (2026-04-04)

### marketplace_monitor Refactor (b1fe021)

**Problem:** Marketplace-Monitor Handler gingen bei jedem Daemon-Neustart verloren
wegen Closure-basiertem Ansatz → [ERROR] Direct tool nicht gefunden nach Neustart.

**Lösung:** Parameter als JSON direkt in SubAgentDef.mission gespeichert.
- direct_tool = "marketplace_monitor" (generisch für alle Plattformen)
- mission = JSON mit query, platforms, location, radius_km, max_price, max_results
- Neustart-sicher: alles in subagents.json, kein externes File nötig
- Entfernt: marketplace_monitors.json, alle Closure-Funktionen, mp-restore Endpoint

**Plattformen:** kleinanzeigen, ebay, willhaben, egun, troostwijk, web

**Syntax (für Dameon-Chat):**
- Einmalig:   "Suche Gartentisch auf Kleinanzeigen in 21224"
- Dauerhaft:  "Überwache Kleinanzeigen nach Gartentischen in 21224 Umkreis 20km"

**Aktive Monitore:**
- Monitor_Gartentisch: Kleinanzeigen, "Gartentisch", 21224, 20km
- Monitor_Sonnenschirm: Kleinanzeigen, "Sonnenschirm", 21224, 20km
- Monitor_Sauer505: eGun, "Sauer 505"

---

## 📋 Roadmap

| Version | Feature |
|---|---|
| v0.15.5 | Stabilisierung marketplace_monitor + Troostwijk Test |
| v0.16 | LLM Autonomie + Qwen3-1.7B als Offline-Fallback |
| v0.17 | Emergency Shutdown via schaltbare Steckdose |
| **v0.18** | **Queue System + IPC-Reload (löst INV_037)** |
| v0.19 | Willhaben Kategorie-Filter |
| v1.0 | Release |

---

## 🤖 Sub-Agents (aktuell, nach Daemon-Neustart)

```
Monitor_Netzwerk    interval:300    direct_tool=check_new_devices    PROTECTED, TOKENLOS
Monitor_Gartentisch interval:3600   direct_tool=marketplace_monitor  JSON: {query, location, radius}
Monitor_Sonnenschirm interval:3600  direct_tool=marketplace_monitor  JSON: {query, location, radius}
Monitor_Sauer505    interval:3600   direct_tool=marketplace_monitor  JSON: {query, platforms=[egun]}
CronJob_0715        cron:15 7 * * * LLM (täglicher Bericht, gewollt)
```

## 🏠 HA-Entities (aktuell)
```
light.licht_fernsehzimmer_switch_0, light.licht_schlafzimmer_switch_0
light.licht_esszimmer_switch_0, light.shellyplus1_08b61fd0b64c_switch_0
switch.licht_kuche_switch_0, switch.fernseher, switch.aquarium_licht
cover.shellyplus2pm_d48afc41a22c (Rolladen Büro)
cover.shellyplus2pm_c82e180c7a1c (Rolladen Schlafzimmer)
cover.rolladen_kuche, cover.rollladen_kinderzimmer
```
