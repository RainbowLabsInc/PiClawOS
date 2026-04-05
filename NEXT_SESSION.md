# PiClaw OS – Offene Punkte für nächste Session
# Letzte Aktualisierung: 2026-04-05 (Session 9)
# Version: v0.15.5

---

## ⚠️ SOFORT ERLEDIGEN

### 1. Credentials rotieren (nach jeder Dev-Session!)
- API-Token: `piclaw config token` → neues Token generieren
- GitHub PAT: https://github.com/settings/tokens → rotieren
- Alte Werte aus dieser Session sind kompromittiert.

### 2. Home Assistant prüfen
Falls piclaw doctor ⬜ zeigt:
```bash
curl -s http://homeassistant:8123/api/ -H "Authorization: Bearer $(grep token /etc/piclaw/config.toml | tail -1 | cut -d'"' -f2)"
```
Falls 200 → nur Timing-Problem, alles ok.

### 3. gpt-oss-120b Status prüfen
Falls noch nicht registriert (Telegram-Bestätigung abwarten):
```
llm_list → prüfen ob groq-gptoss mit Prio 8 da ist
llm_test name="groq-gptoss"
```

---

## 🔧 Bekannte Issues / Nächste Features

### Query-Extraktion verbessern
Dameon nimmt Ortsnamen in die Query auf: "Gartentisch Rosengarten" statt "Gartentisch"
Datei: piclaw-os/piclaw/agent.py → _detect_marketplace_intent()
Fix: Stadtname/PLZ nach Extraktion aus clean_text entfernen

### Troostwijk Auktions-Monitor – Update deployen
Nach `piclaw update` läuft `Monitor_TW_Deutschland` mit neuem Code.
Danach via Dameon weitere Monitore anlegen:
- `"Überwache Troostwijk auf neue Auktionen in Hamburg"`
- `"Überwache Troostwijk auf neue Auktionen in den Niederlanden"`

### Home Assistant doctor fix
Doctor macht HTTP-Request mit 5s Timeout kurz nach Neustart.
Fix: Retry-Logik oder längerer Timeout in cli.py

---

## ✅ Session 9 Zusammenfassung

### Troostwijk Auktions-Monitor (Commit a4d222f)
- `_search_troostwijk_auctions()`: neuer API-Endpoint `/de/auctions.json?countries=de`
  überwacht Auktions-Events (nicht einzelne Lose), Länderfilter per ISO-Code
- Stadtfilter: Substring-Matching im Auktionsnamen (kein API-seitiger Stadtfilter)
- `marketplace_search()`: neues `country`-Parameter, `troostwijk_auctions` Platform
  ohne Pflicht-Query (kein LLM, tokenlos)
- `agent.py`: `_detect_tw_auction_monitor_intent()` erkennt Stadt + Land,
  `_create_tw_auction_monitor()` erstellt Sub-Agenten direkt
  Länder-Mapping: 20+ Länder (DE/NL/BE/FR/AT/IT/ES/SE/DK/PL/...)
- `runner.py`: `country` aus mission-JSON weitergeleitet
- `Monitor_TW_Deutschland` manuell via API erstellt (ID: 5d2fbf85)
  → wartet auf `piclaw update` für neuen Code

### GitHub Token
- Classic Token `FullAccesToken Github` (ghp_...) rotiert – altes Token entsorgen
- Neuer Token in `/etc/piclaw/config.toml` eintragen falls nötig

---

## ✅ Session 8B Zusammenfassung

### marketplace_monitor Refactor (b1fe021)
- direct_tool = "marketplace_monitor" (generisch für alle Plattformen)
- Parameter als JSON in mission-Feld → neustart-sicher
- Entfernt: Closures, marketplace_monitors.json, mp-restore

### Neue Monitore
- Monitor_Gartentisch: Kleinanzeigen, "Gartentisch", 21224, 20km
- Monitor_Sonnenschirm: Kleinanzeigen, "Sonnenschirm", 21224, 20km
- Monitor_Sauer505: eGun, "Sauer 505"

### LLM Backends (aktuell)
- [10] groq-actions: llama-3.3-70b-versatile
- [ 9] groq-fallback: kimi-k2-instruct
- [ 8] groq-gptoss: openai/gpt-oss-120b ← NEU
- [ 6] nemotron-nvidia: llama-4-maverick
- [ 5] openai-default: llama-3.3-70b@nvidia
- lokal: qwen3-1.7b-q4_k_m ← NEU (Offline-Fallback)

### Dokumentation
- AGENTS.md: Agent-Architektur, Syntax, Kaskadierung
- ROADMAP.md: bereinigt, aktuell
- CLAUDE_REBUILD.md: INV_035–037, CHANGES_SESSION_8B

---

## 🤖 Sub-Agents (aktuell)

| Name | Plattform | Query | Intervall |
|---|---|---|---|
| Monitor_Netzwerk | intern | Neue Geräte | 5 Min (PROTECTED) |
| Monitor_Gartentisch | Kleinanzeigen | Gartentisch, 21224, 20km | 1h |
| Monitor_Sonnenschirm | Kleinanzeigen | Sonnenschirm, 21224, 20km | 1h |
| Monitor_Sauer505 | eGun | Sauer 505 | 1h |
| Monitor_TW_Deutschland | Troostwijk Auktionen | Land=DE, Stadt=alle | 1h |
| CronJob_0715 | – | Tagesbericht | täglich 07:15 |

## 🏠 HA-Entities
```
light.licht_fernsehzimmer_switch_0, light.licht_schlafzimmer_switch_0
light.licht_esszimmer_switch_0, light.shellyplus1_08b61fd0b64c_switch_0
switch.licht_kuche_switch_0, switch.fernseher, switch.aquarium_licht
cover.shellyplus2pm_d48afc41a22c (Rolladen Büro)
cover.shellyplus2pm_c82e180c7a1c (Rolladen Schlafzimmer)
cover.rolladen_kuche, cover.rollladen_kinderzimmer
```
