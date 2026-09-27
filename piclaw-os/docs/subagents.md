# PiClaw OS – Sub-Agenten

## Was sind Sub-Agenten?

Sub-Agenten sind eigenständige KI-Tasks die im Hintergrund auf dem Pi laufen.
Jeder hat eine Aufgabe (Mission), einen Zeitplan und einen eigenen Tool-Scope.

## Erstellen (Chat)

```
"Erstelle einen Agenten der täglich um 7 Uhr die CPU-Temperatur prüft
 und mich per Telegram benachrichtigt wenn sie über 70°C liegt."
```

## Erstellen (API)

```bash
curl -X POST http://localhost:7842/api/subagents \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "TempMonitor",
       "description": "Überwacht CPU-Temperatur stündlich",
       "mission": "Prüfe CPU-Temperatur. Wenn > 70°C → Warnung.",
       "schedule": "interval:3600",
       "tools": ["thermal_status", "memory_log"]
     }'
```

## Schedule-Formate

```
interval:300        → alle 5 Minuten
interval:3600       → stündlich
cron:15 7 * * *     → täglich 07:15 Uhr
cron:0 8 * * 1      → montags 08:00 Uhr
once                → einmalig beim nächsten Start
```

## Direct Tool Mode

Für einfache periodische Checks die keinen LLM brauchen:

```json
{
  "name": "Monitor_Netzwerk",
  "direct_tool": "check_new_devices",
  "schedule": "interval:300"
}
```

→ Tool wird direkt aufgerufen, kein LLM-Call, 0 Token.
→ Nur bei neuem Gerät: Sofort Telegram-Alert.
→ Kein Gerät: Heartbeat max. 1×/Stunde.

## Geschützte Agenten

`Monitor_Netzwerk` ist Teil der Sicherheitsarchitektur und dreifach geschützt:

| Layer | Schutz | Reaktion |
|---|---|---|
| 1 | sa_tools.py `_PROTECTED_AGENTS` | LLM-Tool-Call → ⛔ Fehlermeldung |
| 2 | api.py REST-Endpunkte | DELETE/STOP → HTTP 403 |
| 3 | agent.boot() Auto-Recreate | Fehlt beim Start → wird neu angelegt |

Dameon kann Monitor_Netzwerk nicht löschen, stoppen oder modifizieren.

## Zwei-Prozess-Architektur

```
piclaw-api  (Port 7842)  → Telegram-Empfang, REST-API, Web-UI
piclaw-agent (Daemon)    → Sub-Agenten-Scheduler, Hintergrund-Tasks
```

Wichtig:
- Sub-Agenten laufen NUR im Daemon-Prozess (`start_sub_agents=False` in api.py)
- Neuer Sub-Agent via API/Telegram → kein Neustart nötig: der API-Runner
  (`delegate_to_daemon`) gibt start/stop/run_now per IPC an den Daemon weiter,
  der die Definition frisch von Disk lädt (`SubAgentRegistry.reload_agent`)
- Ausnahme: `once`-Agents (z.B. SearchAssistant) laufen direkt im API-Prozess
- IPC-Trigger in `/etc/piclaw/ipc/`: `start_<id>`, `stop_<id>`, `run_now_<id>`,
  `remove_<id>` (jeweils `.trigger`)

## Aktuelle Sub-Agenten

| Name | Schedule | Typ | Beschreibung |
|---|---|---|---|
| Monitor_Netzwerk | alle 5 Min | direct_tool | Netzwerk-Scan, neue Geräte → Alert |
| CronJob_0715 | 07:15 täglich | LLM | Systembericht, Temperatur |
| Monitor_Gartentisch | stündlich | LLM | Kleinanzeigen-Monitor |

## Silent Tokens

Tools können "kein Output nötig" signalisieren:

| Token | Bedeutung |
|---|---|
| `__NO_NEW_DEVICES__` | Netzwerk-Scan: keine neuen Geräte |
| `__NO_NEW_RESULTS__` | Marketplace: keine neuen Inserate |
| `__SILENT__` | Allgemeines Still-Token |

→ Runner erkennt Token → `_intentionally_silent = True` → kein Telegram, kein Fallback.
