# PiClaw OS – Lückenanalyse & Empfehlungen
**Stand v0.8 · Priorisiert nach Wichtigkeit**

---

## 🔴 Kritisch – Fehlt für Grundfunktionalität

### 1. `croniter` fehlt in pyproject.toml
Sub-Agenten mit `schedule: "cron:..."` schweigen ohne Fehler wenn `croniter`
nicht installiert ist (runner.py fängt ImportError ab und fällt auf `once` zurück).
```toml
# pyproject.toml → dependencies:
"croniter>=1.4",
```

### 2. CLI hat keine Sub-Agenten- und Soul-Befehle
`piclaw soul show` / `piclaw soul edit` und `piclaw agent list/create/start/stop`
fehlen komplett. Nutzer sind auf das Chat-Interface angewiesen.
```bash
# Was fehlt:
piclaw soul show              # SOUL.md ausgeben
piclaw soul edit              # in $EDITOR öffnen
piclaw agent list             # alle Sub-Agenten
piclaw agent start <name>
piclaw agent stop <name>
piclaw agent remove <name>
```

### 3. API-Endpoints für Sub-Agenten und Soul fehlen
api.py hat keine Routen dafür. Web-UI und externe Tools können Sub-Agenten
nicht steuern, Soul nicht lesen/schreiben.
```
GET  /api/subagents           → SubAgentRunner.status_dict()
POST /api/subagents           → agent_create via JSON body
DELETE /api/subagents/{id}    → agent_remove
POST /api/subagents/{id}/run  → agent_run_now
GET  /api/soul                → soul.load()
PUT  /api/soul                → soul.save(body)
```

### 4. Doppeltes build.sh
Es existiert sowohl `/build.sh` (Root) als auch `/build/build.sh`.
Das Root-File ist offensichtlich ein Artefakt – löschen oder auf `/build/build.sh` verweisen.

---

## 🟡 Wichtig – Qualität & Benutzbarkeit

### 5. Web-UI hat keine Sub-Agenten- und Soul-Tabs
`index.html` hat nur 3 Tabs: Dashboard, Memory, Chat.
Es fehlen:
- **Agents-Tab:** Liste der Sub-Agenten, Status-Badges, Start/Stop-Buttons, Erstellen-Formular
- **Soul-Tab:** Textarea mit aktuellem SOUL.md-Inhalt, Speichern-Button

### 6. Keine Tests
`pyproject.toml` listet `pytest` als Dev-Dependency, aber es gibt kein `tests/`-Verzeichnis.
Zumindest Smoke-Tests für die kritischsten Pfade wären sinnvoll:
```
tests/
  test_soul.py          ← load/save/build_system_prompt
  test_sa_registry.py   ← CRUD, Persistenz
  test_classifier.py    ← die 25 Regex-Patterns
  test_multirouter.py   ← Tag-Matching, Fallback
  conftest.py           ← tmp-Verzeichnis als CONFIG_DIR
```

### 7. agent.py: `create_backend(cfg)` vs. `create_backend(cfg.llm)`
In v0.7 wurde `create_backend` auf `cfg` (PiClawConfig) umgestellt um die
Multi-LLM-Registry zu initialisieren. Es muss geprüft werden, ob
`llm/__init__.py:create_backend()` tatsächlich `PiClawConfig` erwartet –
oder ob der Aufruf korrigiert werden muss.

### 8. agent.py: `_telegram_send` Wiring unvollständig
`_build_tools()` übergibt `self._telegram_send` an `build_agent_handlers()`,
aber die Methode ist zu diesem Zeitpunkt noch ein No-Op Lambda.
Nach dem Messaging-Hub-Start in `api.py` wird das Lambda ersetzt – aber
das passiert asynchron nach `boot()`. Sub-Agenten die im `boot()` gestartet
werden und sofort `notify` senden, könnten den No-Op treffen.
**Fix:** `_wire_sa_runner()` sollte auch `build_agent_handlers()` mit dem
aktualisierten Sender neu registrieren, oder `notify` lazy auflösen.

### 9. Kein Graceful-Shutdown für Sub-Agenten
`daemon.py` hat vermutlich einen SIGTERM-Handler, aber `SubAgentRunner.stop_all()`
wird nicht aufgerufen. Laufende Sub-Agenten werden hart abgebrochen.
```python
# daemon.py / api.py lifespan:
async def shutdown():
    for aid in list(runner.running_agents()):
        await runner.stop_agent(aid)
```

---

## 🟢 Nice-to-have – Komfort & Erweiterbarkeit

### 10. Beispiel-Sub-Agenten-Templates
Eine `docs/subagent-templates.md` mit Copy-Paste-Beispielen für typische Pi-Anwendungen:
- TempMonitor – CPU/GPU-Temperatur per Cron prüfen und warnen
- DailyBriefing – Morgens Systemzustand zusammenfassen und via Telegram senden
- GitPuller – Stündlich ein Repository pullen und deployen
- SensorLogger – GPIO-Sensordaten minütlich ins Memory schreiben
- HomeAssistantBridge – HA-API pollen und auf Schwellwerte reagieren

### 11. Sub-Agent-Sandboxing
Aktuell teilen Sub-Agenten alle Tools mit dem Mainagent (außer die explizite `tools`-Liste).
Sicherheitsrisiko: Ein Sub-Agent mit manipulierter Mission könnte `shell_exec` aufrufen.
**Optionen:**
a) Tool-Whitelist per Sub-Agent zwingend machen (aktuell optional)
b) `dangerous_tools`-Blocklist in SubAgentDef: sub-agents können nie `shell_exec`, `service_stop` etc. aufrufen
c) Separate LLM-Session ohne Tool-Zugriff für "reporting-only"-Agenten

### 12. Sub-Agent-Ausgaben im Memory speichern
Aktuell werden Sub-Agenten-Ergebnisse nur via Messaging gesendet.
Sie sollten automatisch ins Memory geloggt werden (memory_log), damit
der Mainagent Fragen dazu beantworten kann ("Was hat TempMonitor gestern gemeldet?").

### 13. `piclaw doctor` um Soul + Sub-Agenten erweitern
```bash
piclaw doctor
  ✅ LLM: claude-haiku (API)
  ✅ Memory: QMD ready, 3 collections
  ✅ Soul: /etc/piclaw/SOUL.md (1.2 KB)          ← NEU
  ✅ Sub-Agents: 2 defined, 1 running             ← NEU
  ✅ Messaging: telegram ✓, discord ✓
  ✅ Watchdog: heartbeat 28s ago
```

### 14. CHANGELOG.md fehlt
Für ein Projekt mit 8 Versionen wäre eine CHANGELOG.md sinnvoll.

### 15. `docs/` ist dünn
Nur discord-setup.md vorhanden. Nützliche Ergänzungen:
- `docs/soul.md` – Soul-System erklärt, Beispiele
- `docs/subagents.md` – Sub-Agenten-System, Templates
- `docs/multi-llm.md` – Multi-Backend-Router erklärt
- `docs/api-reference.md` – alle REST-Endpoints

### 16. Keine Health-Endpoint-Authentication
`/api/config` gibt die vollständige Konfiguration zurück (inkl. API-Keys?).
Zumindest ein einfaches Bearer-Token für die REST-API wäre ratsam –
besonders wenn der Pi im Heimnetz ohne VPN läuft.

### 17. Web-UI: Sub-Agenten-Status im Dashboard
Im Dashboard-Tab werden Disk, RAM, Temp, Services angezeigt –
aber nicht die Sub-Agenten. Ein "Agents"-Widget (laufend/total) wäre eine
natürliche Ergänzung.

---

## Prioritäts-Zusammenfassung

| # | Was | Aufwand | Wichtigkeit |
|---|---|---|---|
| 1 | `croniter` in pyproject.toml | 1 Zeile | Kritisch |
| 2 | CLI soul/agent-Befehle | ~50 Zeilen | Kritisch |
| 3 | API /api/subagents + /api/soul | ~60 Zeilen | Kritisch |
| 4 | Doppeltes build.sh entfernen | 1 Datei löschen | Kritisch |
| 5 | Web-UI Agents + Soul Tab | ~150 Zeilen HTML/JS | Wichtig |
| 6 | Tests | ~200 Zeilen | Wichtig |
| 7 | create_backend Signatur prüfen | Review | Wichtig |
| 8 | _telegram_send Lazy-Resolve | ~20 Zeilen | Wichtig |
| 9 | Graceful-Shutdown Runner | ~15 Zeilen | Wichtig |
| 10 | Beispiel-Templates docs | ~80 Zeilen MD | Nice-to-have |
| 11 | Sub-Agent Sandboxing | ~30 Zeilen | Nice-to-have |
| 12 | Sub-Agent → Memory | ~10 Zeilen runner.py | Nice-to-have |
| 13 | piclaw doctor erweitern | ~20 Zeilen | Nice-to-have |
| 14 | CHANGELOG.md | Doku | Nice-to-have |
| 15 | docs/ erweitern | Doku | Nice-to-have |
| 16 | API-Auth | ~40 Zeilen | Nice-to-have |
| 17 | Dashboard Agents-Widget | ~30 Zeilen HTML/JS | Nice-to-have |

---

## Empfehlung für nächste Session

Die vier kritischen Punkte (1–4) lassen sich in ~30 Minuten beheben.
Danach wären die API-Endpoints (3) + Web-UI-Tabs (5) der größte sichtbare Sprung –
man könnte dann Sub-Agenten direkt im Browser erstellen und die Soul-Datei
bearbeiten, ohne SSH.

Wenn echte Hardware vorhanden ist: erst build.sh testen und auf dem Pi deployen,
dann die Lücken live bewerten.
