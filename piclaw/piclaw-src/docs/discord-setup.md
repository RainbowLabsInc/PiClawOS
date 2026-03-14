# Discord Setup für PiClaw OS

## Übersicht

PiClaw kommuniziert über einen Discord-Bot in einem konfigurierten Kanal.
Der Bot antwortet auf Nachrichten im Kanal – du kannst den Pi also steuern
wie jeden anderen Discord-Chat.

---

## Schritt 1 – Discord Application anlegen

1. Öffne https://discord.com/developers/applications
2. Klicke **New Application** → vergib einen Namen (z.B. `PiClaw`)
3. Linkes Menü: **Bot** → **Add Bot** → bestätige

### Wichtige Einstellungen unter **Bot**:
- **Public Bot**: ❌ ausschalten (nur du soll den Bot einladen können)
- **Privileged Gateway Intents**:
  - ✅ **Message Content Intent** — **muss aktiviert sein**, sonst empfängt der Bot keine Texte

### Bot-Token kopieren:
Klicke **Reset Token** → kopiere den Token (du siehst ihn nur einmal!)

---

## Schritt 2 – Bot zum Server einladen

1. Linkes Menü: **OAuth2** → **URL Generator**
2. Scopes: ✅ `bot`
3. Bot Permissions:
   - ✅ Read Messages / View Channels
   - ✅ Send Messages
   - ✅ Read Message History
   - ✅ (optional) Embed Links — für Watchdog-Alerts als Embeds
4. Generierte URL im Browser öffnen → Bot zu deinem Server hinzufügen

---

## Schritt 3 – Channel ID ermitteln

1. Discord-Einstellungen → **Erweitert** → **Entwicklermodus** aktivieren
2. Rechtsklick auf deinen gewünschten Kanal → **Kanal-ID kopieren**

*Empfehlung: Lege einen eigenen Kanal `#piclaw` an, damit Bot-Nachrichten
nicht andere Gespräche stören.*

---

## Schritt 4 – (Optional) Deine User ID ermitteln

Falls du den Bot auf deinen Account beschränken willst:
- Rechtsklick auf deinen Namen in Discord → **User-ID kopieren**

---

## Schritt 5 – PiClaw konfigurieren

### Option A – Setup-Wizard (empfohlen):
```bash
ssh piclaw@piclaw.local
piclaw messaging setup
```

### Option B – Manuell in `/etc/piclaw/config.toml`:
```toml
[discord]
token         = "Dein-Bot-Token-hier"
channel_id    = 1234567890123456789
allowed_users = [9876543210987654321]  # optional: deine User-ID
```

Dann Dienst neu starten:
```bash
sudo systemctl restart piclaw-api
```

---

## Schritt 6 – Verbindung testen

```bash
piclaw messaging test
```

Oder direkt im Discord-Kanal schreiben – der Bot sollte antworten.

---

## Funktionsweise

| Aktion | Ergebnis |
|--------|----------|
| Nachricht im konfigurierten Kanal | Agent verarbeitet und antwortet |
| Watchdog-Alert | Erscheint als rotes Embed im Kanal |
| Crawler-Ergebnis | Wird als Nachricht gepostet |
| Andere Kanäle | Werden ignoriert |
| Andere User (wenn allowed_users gesetzt) | Werden ignoriert |

---

## Bekannte Einschränkungen

- **2000 Zeichen Limit**: Längere Antworten werden automatisch aufgeteilt
- **Rate Limiting**: Discord erlaubt ca. 5 Nachrichten/Sekunde; bei vielen
  Watchdog-Alerts kann es zu kurzen Verzögerungen kommen
- **Kein Inline-Code in Embeds**: Watchdog-Alerts nutzen Discord Embeds,
  normale Antworten plain text

---

## Troubleshooting

**Bot antwortet nicht:**
```bash
journalctl -u piclaw-api -n 50 | grep discord
```

**"Message Content Intent missing":**
→ Discord Developer Portal → Bot → Privileged Gateway Intents → Message Content Intent aktivieren

**Bot online aber kein Response:**
→ Prüfe ob `channel_id` korrekt ist
→ Prüfe ob `allowed_users` deine ID enthält (oder leer lassen für alle)
