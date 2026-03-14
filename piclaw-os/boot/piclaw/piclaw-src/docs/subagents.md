# PiClaw OS – Sub-Agenten

## Was sind Sub-Agenten?

Sub-Agenten sind eigenständige KI-Tasks die auf dem Pi laufen.
Jeder hat eine Aufgabe (Mission), einen Zeitplan und einen eigenen Tool-Scope.
Der Haupt-Agent erstellt und verwaltet sie – du kannst es aber auch über die Web-UI oder API tun.

## Erstellen (Chat)

Der einfachste Weg:
```
"Erstelle einen Agenten der täglich um 7 Uhr die CPU-Temperatur prüft
 und mich per Telegram benachrichtigt wenn sie über 70°C liegt."
```

Der Haupt-Agent erstellt automatisch eine `SubAgentDef` und startet den Agenten.

## Erstellen (API)

```bash
curl -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "TempMonitor",
       "description": "Überwacht CPU-Temperatur stündlich",
       "mission": "Lies die CPU-Temperatur. Wenn > 70°C, sende eine Warnung.",
       "schedule": "interval:3600",
       "tools": ["get_temp", "memory_write"],
       "notify": true
     }' \
     http://piclaw.local:7842/api/subagents
```

## Zeitpläne

| Format | Bedeutung |
|--------|-----------|
| `once` | Einmalig direkt ausführen |
| `interval:3600` | Alle 3600 Sekunden (1 Stunde) |
| `cron:0 7 * * *` | Täglich um 07:00 Uhr |
| `continuous` | Dauerhaft, mit 10s Pause zwischen Zyklen |

## Felder

| Feld | Standard | Beschreibung |
|------|----------|--------------|
| `name` | – | Eindeutiger Name (Pflicht) |
| `description` | – | Kurzbeschreibung (Pflicht) |
| `mission` | – | System-Prompt / Aufgabe (Pflicht) |
| `schedule` | `once` | Zeitplan |
| `tools` | `[]` | Erlaubte Tools (`[]` = alle sicheren) |
| `trusted` | `false` | Tier-2 Tools freischalten (Hardware/Services) |
| `llm_tags` | `[]` | Bevorzugtes LLM-Backend |
| `max_steps` | `10` | Max. Schritte pro Lauf |
| `timeout` | `300` | Timeout in Sekunden |
| `notify` | `true` | Ergebnis per Messaging-Hub senden |

## Sandboxing

Sub-Agenten haben eingeschränkten Tool-Zugriff:

**Tier 1 – Immer gesperrt** (kein Override):
`shell_exec`, `system_reboot`, `system_poweroff`, `watchdog_stop`, `watchdog_disable`,
`updater_apply`, `config_write_raw`

**Tier 2 – Standard gesperrt** (freischaltbar mit `trusted=true` + expliziter Listenangabe):
`service_stop`, `service_restart`, `gpio_write`, `network_set`, `scheduler_remove`

**Alle anderen Tools:** Standard verfügbar.

### Trusted Agent einrichten

```json
{
  "name": "ServiceManager",
  "mission": "Starte piclaw-crawler.service neu wenn er abstürzt.",
  "tools": ["service_restart", "service_status"],
  "trusted": true
}
```

## CLI

```bash
piclaw agent list                    # alle Sub-Agenten anzeigen
piclaw agent start TempMonitor       # starten
piclaw agent stop TempMonitor        # stoppen
piclaw agent run TempMonitor         # sofort einmal ausführen
piclaw agent remove TempMonitor      # löschen
```

## Web-UI

Tab **Agenten** zeigt alle Sub-Agenten mit:
- Status-Icon (✅ ok, ❌ error, ⏱️ timeout, ⚙️ running)
- Letzten Lautzeitpunkt
- ▶ Start / ■ Stop / ⚡ Jetzt ausführen / ✕ Löschen

## Memory-Integration

Nach jedem Lauf schreibt der Sub-Agent sein Ergebnis in den QMD-Speicher:
```
[2026-03-10 07:00] Sub-Agent 'TempMonitor' (ok): CPU-Temperatur: 52.3°C. Alles normal.
```

Der Haupt-Agent kann das abrufen:
```
"Was hat TempMonitor heute Morgen gemessen?"
```
