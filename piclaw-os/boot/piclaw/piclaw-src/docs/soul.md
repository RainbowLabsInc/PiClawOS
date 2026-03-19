# PiClaw OS – Soul System

## Was ist der Soul?

Der Soul ist eine Markdown-Datei unter `/etc/piclaw/SOUL.md`.
Ihr Inhalt wird als **erstes Block** in jeden System-Prompt injiziert – noch vor
den Tool-Beschreibungen und Fähigkeits-Listen. Er definiert damit Persönlichkeit,
Aufgabe und Verhalten des Agenten dauerhaft.

## Priorität

```
Prompt-Aufbau:
  1. Soul         ← nimmt Vorrang, kommt zuerst
  2. Capabilities (Tool-Liste, Speicher-Anweisungen)
  3. Context      (Datum, Hostname, Agenten-Name)
```

Der LLM sieht den Soul bevor er seinen Werkzeugkasten kennt. Das bedeutet:
Verhaltensregeln im Soul überschreiben die eingebauten Defaults.

## Standard-Soul

Beim ersten Boot wird ein Standard-Soul erstellt (auf Deutsch):

```markdown
# PiClaw – Soul

## Wer bin ich?
Ich bin PiClaw, ein KI-Agent der dauerhaft auf diesem Raspberry Pi 5 lebt.
…

## Charakter
- Direkt, technisch präzise, effizient
- Erkläre was ich tue, ohne unnötige Ausschweifungen
- Warne vor disruptiven Aktionen, führe sie aber durch wenn bestätigt
…
```

## Soul bearbeiten

**Via Web-UI** (empfohlen):
- Tab **Soul** → Bearbeiten → Ctrl+S

**Via CLI:**
```bash
piclaw soul show             # aktuellen Inhalt anzeigen
piclaw soul edit             # in $EDITOR öffnen
piclaw soul reset            # auf Standard zurücksetzen
```

**Via API:**
```bash
# Lesen
curl -H "Authorization: Bearer $TOKEN" http://piclaw.local:7842/api/soul

# Überschreiben
curl -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content": "# My Custom Soul\n\nSei präzise und hilfsbereit."}' \
     http://piclaw.local:7842/api/soul

# Abschnitt anhängen
curl -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"section": "## Neues Verhalten\n\nImmer auf Deutsch antworten."}' \
     http://piclaw.local:7842/api/soul/append
```

## Ideen für deinen Soul

```markdown
# Mein Pi-Agent

## Kontext
Ich lebe in einem Homelab in München.
Der Besitzer heißt Max und arbeitet als Software-Entwickler.
Wichtige Geräte: NAS (192.168.1.50), Router (192.168.1.1)

## Sprache
Antworte immer auf Deutsch, außer Max schreibt explizit Englisch.

## Prioritäten
1. Sicherheit geht vor Komfort
2. Ändere nie Netzwerk-Config ohne Bestätigung
3. Halte Logs sauber und komprimiert

## Charakter
Bin direkt und klar, erkläre Fehler immer mit Lösungsvorschlag.
Erinnere mich an Entscheidungen aus vergangenen Gesprächen.
```

## Wichtig

Änderungen am Soul wirken beim **nächsten Gespräch** oder
beim nächsten Sub-Agenten-Lauf. Die laufende Session kennt noch den alten Soul.
