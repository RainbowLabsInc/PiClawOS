# PiClaw OS – API Authentication

## Konzept

PiClaw OS verwendet ein einzelnes statisches Bearer-Token pro Installation.
Das Token wird beim ersten Systemstart automatisch generiert und in `/etc/piclaw/config.toml`
unter `[api] secret_key` gespeichert.

**Eigenschaften:**
- Kryptografisch zufällig (`secrets.token_urlsafe(32)`, 43 Zeichen)
- Konstanter Zeitvergleich (`secrets.compare_digest`) – kein Timing-Angriff möglich
- Automatisch in das Web-UI injiziert (`window.PICLAW_TOKEN` via HTML)
- Einmalig generiert, bleibt bis zur manuellen Rotation erhalten

## Token anzeigen

```bash
piclaw config token
# → zeigt Token + curl-Beispiel
```

## API-Zugriff

### HTTP (REST)
```bash
export TOKEN=$(sudo cat /etc/piclaw/config.toml | grep secret_key | cut -d'"' -f2)

# Statistiken abrufen
curl -H "Authorization: Bearer $TOKEN" http://piclaw.local:7842/api/stats

# Soul lesen
curl -H "Authorization: Bearer $TOKEN" http://piclaw.local:7842/api/soul

# Sub-Agent erstellen
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

## Ausnahmen (keine Auth erforderlich)

| Pfad | Grund |
|------|-------|
| `GET /` | Web-UI (liefert Token bereits im HTML) |
| `GET /health` | Monitoring-Scripts |
| `GET /webhook/whatsapp` | Meta-Webhook-Verifikation |
| `POST /webhook/whatsapp` | HMAC-Signatur-Verifikation |
| `POST /webhook/threema` | Threema eigenes Auth-Schema |

## Token rotieren

```bash
# 1. Neues Token generieren
piclaw config set api.secret_key ""
sudo systemctl restart piclaw-api.service
piclaw config token   # → zeigt neues Token

# 2. Web-UI automatisch mit neuem Token (Browser neu laden)
```

## Sicherheitshinweise

- **Lokales Netzwerk:** Das Token schützt primär gegen unautorisierten Zugriff im LAN.
  Für Internet-Exponierung zusätzlich einen Reverse-Proxy mit TLS verwenden.
- **Token nie in Logs:** FastAPI-Middleware gibt den Token nicht in Logs aus.
- **`/api/config`:** Gibt `secret_key` und API-Keys bewusst nicht zurück.
