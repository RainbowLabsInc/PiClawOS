# PiClaw OS – API Authentication

> Stand: v0.18.0 (Multi-User). Für das ältere Single-Token-Modell siehe
> Abschnitt „Legacy-Fallback".

## Konzept

Seit v0.18.0 authentifiziert sich jeder Nutzer mit einem **eigenen
Bearer-Token** (`web_token`). Die Nutzer sind in `/etc/piclaw/users.json`
registriert (Rollen: `pending` → `user` → `admin`).

**Eigenschaften:**
- Kryptografisch zufällig (`secrets.token_urlsafe(32)`)
- Konstanter Zeitvergleich (`secrets.compare_digest`) – kein Timing-Angriff möglich
- Pro Nutzer – Sichtbarkeit von Daten (Pakete, Routinen, Sub-Agents) folgt dem Token
- Rate-Limiting: 10 Fehlversuche pro IP → 15 Minuten Lockout
- **Kein Token im HTML**: Das Web-UI fragt den Token einmalig ab und speichert
  ihn nur im Browser (`localStorage.piclaw_token`); Logout via
  `window.PICLAW_LOGOUT()` in der Browser-Konsole

## Eigenen Token bekommen

```bash
# Per Telegram (als freigeschalteter Nutzer):
/web_token

# Per CLI (Admin):
piclaw user token <Name>
```

## API-Zugriff

### HTTP (REST)
```bash
TOKEN="<dein web_token>"

# Eigene Nutzer-Info
curl -H "Authorization: Bearer $TOKEN" http://piclaw.local:7842/api/whoami

# Statistiken abrufen
curl -H "Authorization: Bearer $TOKEN" http://piclaw.local:7842/api/stats

# Sub-Agent erstellen (owner_id = aufrufender Nutzer)
curl -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"TempCheck","description":"Prüft CPU-Temperatur","mission":"Lies die CPU-Temperatur und melde sie.","schedule":"interval:3600"}' \
     http://piclaw.local:7842/api/subagents
```

### WebSocket
```
ws://piclaw.local:7842/ws/chat?token=<TOKEN>
```

```javascript
const ws = new WebSocket(`ws://piclaw.local:7842/ws/chat?token=${token}`);
ws.send(JSON.stringify({ text: "Wie warm ist die CPU?" }));
```

## Admin-Endpoints

Systemändernde Endpoints erfordern die **Admin-Rolle** (nicht nur ein gültiges Token):

| Endpoint | Wirkung |
|---|---|
| `GET /api/users`, `GET /api/users/pending` | Nutzer auflisten |
| `POST /api/users/{id\|name}/approve` / `revoke` | Nutzer freischalten / entfernen |
| `POST /api/soul`, `/api/backup/*`, `/api/wizard/*`, `POST /api/sensors` | System-Konfiguration |

Details: [multi-user.md](multi-user.md)

## Ausnahmen (keine Bearer-Auth)

| Pfad | Grund |
|------|-------|
| `GET /` | Web-UI-Shell (enthält **keinen** Token; Login erfolgt clientseitig) |
| `GET /health` | Monitoring-Scripts – nur Status-OK, keine Daten |
| `GET /webhook/whatsapp` | Meta-Webhook-Verifikation |
| `POST /webhook/whatsapp` | HMAC-Signatur-Verifikation (eigenes Schema) |
| `POST /webhook/threema` | Threema eigenes Auth-Schema |

## Legacy-Fallback (Installationen vor v0.18)

Solange `users.json` keinen aktiven Nutzer enthält, wird übergangsweise der
Alt-Token aus `config.toml` (`[api] secret_key`) akzeptiert. Die Migration
(`scripts/migrate_to_multiuser.py`) überführt diesen Token in den
Admin-Account – bestehende Bookmarks und Scripts funktionieren danach
unverändert weiter. Siehe [multi-user.md](multi-user.md#migration-vom-single-user-stand).

## Sicherheitshinweise

- **Lokales Netzwerk:** Das Token schützt primär gegen unautorisierten Zugriff
  im LAN. Für Internet-Exponierung zusätzlich einen Reverse-Proxy mit TLS
  verwenden (siehe [SECURITY.md](../../SECURITY.md)).
- **Token nie in Logs:** Die API gibt Tokens nicht in Logs aus; API-Keys werden maskiert.
- **`/api/config`:** Gibt `secret_key` und API-Keys bewusst nicht zurück.
- **Token geheim halten:** Wer den Token hat, agiert als dieser Nutzer.
