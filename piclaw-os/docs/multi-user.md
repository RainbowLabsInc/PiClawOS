# PiClaw OS – Multi-User

Mehrere Personen teilen sich einen Pi. Jeder hat eigene Pakete, eigenen
Telegram-Chat, eigenes Memory, eigene Sub-Agents – ohne dass System-Ressourcen
wie Watchdog, Hardware-Monitoring oder LLM-Registry pro Nutzer vervielfacht
werden.

## Konzept

Eine Person hat **zwei Türen** in PiClaw und **einen** User-Record:

| Tür | Anker | Wozu |
|---|---|---|
| Telegram | `telegram_chat_id` | Chatten mit dem Agent, `/whoami`, Pakete tracken, Briefings empfangen |
| Web-UI / REST | `web_token` (Bearer) | Browser-Dashboard, `/api/*`-Calls |

Beide referenzieren denselben Eintrag in `/etc/piclaw/users.json`. Telegram-Routing
erkennt Nutzer automatisch über die `chat_id`; HTTP-Routing über den Token.

## Rollen

```
pending  → /start gemacht, wartet auf Admin-Approval
user     → vollwertig, eigene Daten, kann den Bot benutzen
admin    → user + verwaltet User, Backups, System-Config
```

Der erste registrierte User wird automatisch Admin.

## Was ist pro User, was ist geteilt?

| Bereich | Modus |
|---|---|
| Paket-Tracking (`parcels.json` mit `owner_id`) | pro User |
| Routinen (außer System-Routinen wie `temp_check`) | pro User |
| Sub-Agents (mit `owner_id`) | pro User |
| Memory (`users/<id>/memory/`) | pro User |
| HomeAssistant-Token, AgentMail-Inbox, Discord/Threema/WhatsApp-Recipient | pro User via Override |
| Watchdog, Hardware, GPIO, Sensoren | geteilt |
| LLM-Registry, SOUL.md | geteilt |
| Crawler-Jobs (`ipc/jobs.db` mit `owner_user_id`) | pro User |

## User hinzufügen

### Selbst-Service via Telegram

1. Neuer User schreibt deinem Bot: `/start <Name>`
2. Admin bekommt automatisch eine DM:
   ```
   🔔 Neue Registrierung: Anna
   chat_id: 1234567890
   Aktivieren mit: /approve Anna
   ```
3. Admin antwortet im eigenen Chat: `/approve Anna`
4. Anna bekommt eine Willkommens-DM mit `/web_token`-Hinweis
5. Falls Web-UI benutzt werden soll: Anna schickt `/web_token`, bekommt
   ihren Bearer-Token, trägt ihn beim ersten Besuch ein

### Per SSH/CLI

```bash
# Wartende User sehen
piclaw user pending

# Direkt anlegen (Admin muss chat_id von Anna kennen – via @userinfobot)
piclaw user add Anna --telegram 1234567890 --role user

# Pending freischalten
piclaw user approve Anna

# Token ausgeben (an Anna weiterleiten)
piclaw user token Anna

# Interaktives Menü
piclaw user setup
```

### Per Setup-Wizard

```bash
piclaw setup
# Block "Benutzer" auswählen
# Menü: Freischalten / Anlegen / Token / Entfernen / Settings
```

## Per-User-Settings (Overrides)

Jeder User kann eigene HomeAssistant-, AgentMail-, Discord-, Threema- oder
WhatsApp-Einstellungen haben. Sind sie nicht gesetzt, gilt der globale Wert
aus `config.toml`.

```bash
# HomeAssistant-Token nur für Anna
piclaw user set Anna homeassistant.token HA-secret-anna
piclaw user set Anna homeassistant.url http://192.168.10.20:8123

# AgentMail-Inbox pro User
piclaw user set Anna agentmail.email_address anna@agentmail.to
piclaw user set Anna agentmail.inbox_id inbox-xyz

# Anzeigen (Tokens werden maskiert)
piclaw user settings Anna

# Override entfernen
piclaw user clear Anna homeassistant.token      # einzelner Key
piclaw user clear Anna agentmail                # ganze Sektion
```

Folgende Sektionen sind override-fähig: `homeassistant`, `agentmail` (außer
`api_key` – eine Plattform-Lizenz für alle), `discord`, `threema`, `whatsapp`.

## Telegram-Bot-Commands

| Command | Wer | Wirkung |
|---|---|---|
| `/start [Name]` | alle | Registrierung; erster User wird Admin, Rest pending |
| `/whoami` | alle | eigene User-Info |
| `/web_token` | aktive User | eigener Bearer-Token (für Web-UI) |
| `/help` | alle | Befehlsliste (Admin sieht mehr) |
| `/users` | Admin | aktive User auflisten |
| `/pending` | Admin | wartende User |
| `/approve <Name>` | Admin | pending → user; betroffener User bekommt DM |
| `/revoke <Name>` | Admin | User entfernen (letzter Admin geschützt) |

## API-Endpoints

Authentifizierung: `Authorization: Bearer <web_token>`

| Endpoint | Wer | Verhalten |
|---|---|---|
| `GET /api/whoami` | alle | eigene User-Info |
| `GET /api/users` | Admin | alle aktiven User (ohne Tokens) |
| `GET /api/users/pending` | Admin | wartende User |
| `POST /api/users/{id\|name}/approve` | Admin | pending → user |
| `POST /api/users/{id\|name}/revoke` | Admin | User entfernen (409 wenn letzter Admin) |
| `GET /api/subagents` | alle | Admin sieht alle, andere nur eigene + System |
| `POST /api/subagents` | alle | erstellt Sub-Agent mit `owner_id = caller` |
| `POST /api/soul`, `/api/backup/*`, `/api/wizard/*`, `POST /api/sensors` | Admin | system-modifizierend |

Webhooks (`/webhook/*`) und `/health` bleiben exempt – sie nutzen eigene
Auth-Schemes.

## Web-UI Login

`/etc/piclaw/index.html` injiziert keinen Token mehr als JavaScript-Variable.
Stattdessen liest ein Bootstrap-Script `localStorage.piclaw_token`; ist
nichts gespeichert, fragt es einmalig per `prompt()` nach. Logout via
`window.PICLAW_LOGOUT()` in der Browser-Konsole löscht den Token.

## Sub-Agent-Notifications

Wenn ein Sub-Agent einen `owner_id` hat, gehen seine Telegram-Benachrichtigungen
direkt an die `chat_id` des Owners – nicht an die globale Default-`chat_id`.
System-Sub-Agents (`owner_id=None`, z.B. `temp_check`, `network_check`)
bleiben Broadcast.

In `agent.log` sichtbar als:
```
Sub-agent 'Monitor_X': Telegram-Notify OK (142 Zeichen, owner=8a7eb3d0-…)
                                                       ^^^^^^^^^^^^^^^^^^
                                          oder owner=broadcast für System-Agents
```

## Migration vom Single-User-Stand

Bestehende Installationen (Pi mit alter `config.toml`-only-Auth) werden
durch `scripts/migrate_to_multiuser.py` hochgezogen:

```bash
sudo systemctl stop piclaw-api piclaw-agent piclaw-watchdog piclaw-crawler
sudo -u piclaw /opt/piclaw/.venv/bin/python /opt/piclaw/piclaw-os/scripts/migrate_to_multiuser.py
sudo systemctl start piclaw-api piclaw-agent piclaw-watchdog piclaw-crawler
```

Idempotent. Vor jedem Lauf wird ein Tarball aller relevanten Files unter
`/etc/piclaw/backups/pre-multiuser-<timestamp>.tar.gz` abgelegt – zurückspielen
mit `sudo tar xzf <tarball> -C /etc/piclaw/`. Der vorhandene `api.secret_key`
wird `web_token` des frisch angelegten Admin-Users → alte Browser-Bookmarks
und CLI-Scripts mit dem alten Token funktionieren unverändert weiter.

Was passiert konkret:

1. Pre-flight: Abbruch wenn schon migriert
2. Backup-Tarball
3. Bootstrap-Admin (`patrick` per Default; via `--admin-name <Name>` anders)
4. `owner_id` auf existierende Parcels, Routinen, Sub-Agents, jobs.db-Rows
5. `memory/MEMORY.md`, daily logs, sessions/ unter `users/<admin-id>/memory/`

## Architektur

Identitäts-Layer:

- `piclaw/users.py` – `User` dataclass + `UserRegistry` (Persistenz, Token-Lookup, Bootstrap, Override-CRUD)
- `piclaw/agent_context.py` – `current_user` ContextVar, gesetzt vor jedem Agent-Run

Auth:

- `piclaw/auth.py` – `require_auth` / `require_admin` als FastAPI-Dependencies;
  Legacy-Token-Fallback solange `users.json` keinen aktiven User hat
- Rate-Limiting (10 Fails / 15 Min Lockout) bleibt unverändert

Routing:

- `piclaw/messaging/telegram.py` – `_handle_message` löst `chat_id → user_id` auf,
  setzt `IncomingMessage.user_id`; ungekannte Sender bekommen `/start`-Hinweis;
  pending User bekommen Warte-Hinweis
- `piclaw/messaging/bot_commands.py` – Slash-Command-Dispatch
- `piclaw/messaging/hub.py::send_to_user` – zielgerichtetes Senden an Owner-`chat_id`

Daten-Scoping:

- Pro Datensatz ein `owner_id`-Feld (Parcels, Routinen, Sub-Agents, Jobs)
- Memory: per-User-Verzeichnis `users/<id>/memory/`
- Sichtbarkeit: `visible_to(user_id)`-Methode an Datentyp, `None`=System=für alle sichtbar

Per-User-Overrides:

- `User.overrides: dict[section, dict[key, value]]`
- `users.get_setting_for_current(section, key, fallback)` – Override mit Fallback
  auf globale `config.toml`-Werte
- Consumer-Wiring in `tools/homeassistant.py` (`get_client` schnappt sich
  pro Aufruf den User-Token), `tools/parcel_tracking.py` (AgentMail-Inbox)

## Tests

```bash
pytest piclaw/tests/
```

Multi-User-Test-Suite: 222 Tests, davon
- 27 User-Registry / Token-Auth
- 18 Auth-Layer / Admin-Gate / Legacy-Fallback
- 32 Telegram-Routing / Bot-Commands / Promote-Notify
- 26 CLI `piclaw user …`
- 16 Daten-Scoping (parcels, routines, subagents, memory, ipc.jobs)
- 14 API-User-Routes
- 19 Wizard-User-Flows
- 16 Per-User-Overrides (Daten-Layer + CLI)
- 11 Consumer-Wiring (HA, AgentMail)
- 19 Migrations-Skript
- 8 Sub-Agent-Owner-Notify
- 16 Sonstige bestehende
