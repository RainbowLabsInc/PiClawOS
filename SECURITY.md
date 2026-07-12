# 🔐 PiClaw OS – Security Policy

> Letzte Aktualisierung: 2026-07-12
> Gilt für: v0.18.x

---

## Überblick & Einsatz-Szenario

PiClaw OS ist für den Betrieb im **lokalen Heimnetzwerk** ausgelegt. Es ist kein
öffentlich exponiertes System und sollte **nicht ohne zusätzliche Absicherung**
(Reverse Proxy mit HTTPS, VPN) aus dem Internet erreichbar sein.

Wichtig für die Einordnung aller folgenden Punkte:

- Die API spricht ab Werk **HTTP ohne TLS**. Das lokale Netz gilt damit als
  Vertrauenszone – wer vollen Zugriff auf das LAN hat, ist im Bedrohungsmodell
  nicht enthalten. Für Zugriff von außen: ausschließlich über VPN oder einen
  TLS-terminierenden Reverse Proxy.
- Der Agent ist LLM-gesteuert und hat Werkzeuge mit Systemwirkung. Nur
  vertrauenswürdige Personen sollten freigeschaltet werden (siehe Multi-User).

---

## Sicherheitsarchitektur

### Authentifizierung & Autorisierung (seit v0.18.0: Multi-User)

| Kanal | Methode |
|---|---|
| REST-API `/api/*` | Bearer-Token **pro Nutzer** (`web_token`), kryptografisch zufällig generiert, timing-sicherer Vergleich |
| WebSocket `/ws/chat` | Bearer-Token als Query-Parameter |
| Telegram | Nutzer-Registrierung über `chat_id`: unbekannte Absender erhalten nur den `/start`-Hinweis, neue Nutzer warten auf Admin-Freigabe |
| WhatsApp | HMAC-SHA256-Signaturprüfung via `app_secret` – **Pflicht**, ohne Konfiguration wird abgelehnt |
| Threema | Threema-Gateway-Eigenverifizierung |
| `/health` | Unauthentifiziert – liefert nur Status-OK, keine Daten |

**Rollenmodell:** `pending` → `user` → `admin`. Der erste registrierte Nutzer
wird Admin; alle weiteren müssen von einem Admin freigegeben werden
(`/approve`). Der letzte Admin kann nicht entfernt werden. Systemändernde
Endpoints (Soul, Backups, Wizard, Sensoren, Nutzerverwaltung) erfordern die
Admin-Rolle.

**Rate-Limiting:** Wiederholte fehlgeschlagene Auth-Versuche führen zu einem
temporären IP-Lockout (Standard: 10 Fehlversuche → 15 Minuten Sperre).

**Web-UI-Login:** Seit v0.18.0 wird **kein API-Token mehr in die HTML-Seite
injiziert**. Das Dashboard fragt den Token einmalig ab und hält ihn nur im
Browser (localStorage). Jeder Nutzer verwendet seinen eigenen Token
(`/web_token` in Telegram oder `piclaw user token <Name>` per CLI).

**Legacy-Fallback:** Installationen ohne migrierte Nutzerverwaltung
akzeptieren übergangsweise den Alt-Token aus `config.toml`. Die Migration
(`scripts/migrate_to_multiuser.py`) überführt ihn in den Admin-Account.

### Netzwerk-Exposition

- API-Port 7842; die Firewall-Regeln des Installers beschränken den Zugriff
  auf private RFC-1918-Adressbereiche (LAN) statt „von überall".
- CORS ist per Middleware auf lokale Origins beschränkt – Anfragen fremder
  Websites werden unabhängig vom Firewall-Status abgelehnt.
- Security-Header (u.a. `X-Frame-Options`, `X-Content-Type-Options`,
  `Referrer-Policy`, `Cache-Control: no-store`) sind gesetzt.

### Dateisystem & Secrets

| Bereich | Maßnahme |
|---|---|
| `/etc/piclaw/config.toml` | `600`, Besitzer `piclaw` – enthält API-Keys und Tokens |
| Logs `/var/log/piclaw/` | API-Keys werden maskiert (nur Präfix geloggt) |
| GitHub-Token (Updater) | Über den Git-Credential-Store, nicht als Prozessargument oder URL-Bestandteil |
| WLAN-Zugangsdaten | Übergabe an `nmcli` via stdin, nicht als Prozessargument |
| `/api/config` | Gibt Secrets bewusst nicht zurück |

### Eingabevalidierung

- Netzwerk-Tools validieren IP-Adressen, Netzbereiche und Hostnamen strikt,
  bevor externe Programme aufgerufen werden; ungültige Eingaben werden ohne
  Prozessstart abgelehnt.
- Externe Programme werden ohne Shell-Kontext gestartet (`subprocess_exec`
  mit Argumentliste statt Shell-Strings).
- Das Shell-Tool erlaubt nur Befehle aus einer Allowlist und lehnt Eingaben
  mit Shell-Metazeichen pauschal ab.
- Dateizugriffe (Workspace, Kamera) sind gegen Path-Traversal abgesichert
  (Auflösung + Verzeichnis-Containment-Prüfung).

### Sub-Agent-Sandbox

Sub-Agenten laufen mit einem reduzierten Tool-Satz. Sicherheitskritische
Werkzeuge (Shell, Systemsteuerung, Updater, Watchdog-Kontrolle u.ä.) sind für
Sub-Agenten grundsätzlich gesperrt; einzelne weitere Werkzeuge lassen sich nur
durch den Administrator gezielt freigeben. Die Freigabe erfolgt ausschließlich
über die authentifizierte API.

### Watchdog

Ein unabhängiger Daemon unter eigenem Linux-User (`piclaw-watchdog`), den der
Hauptagent nicht steuern kann. Er überwacht Systemressourcen, Service-Status
und die Integrität kritischer Dateien (u.a. `config.toml`, systemd-Units,
SSH-Konfiguration). Seine Logs sind append-only.

### Betriebshärtung (Juli 2026)

- Alle geteilten State-Dateien (`users.json`, `subagents.json`,
  `routines.json`, `parcels.json`, LLM-Registry, `config.toml`, …) werden
  atomar per Read-Merge-Write unter File-Lock aktualisiert – kein
  Datenverlust durch konkurrierende Prozesse.
- Korrupte State-Dateien werden **quarantänisiert** (`.corrupt-<timestamp>`)
  statt stillschweigend überschrieben.
- GitHub-Actions-CI führt auf jedem Pull Request Linting (ruff) und die
  Test-Suite (pytest) aus; Regressionstests decken u.a. Store-Concurrency,
  Quarantäne-Verhalten und Auth-Flows ab (222 Tests allein für Multi-User).

---

## Behobene Schwachstellen

Die folgenden Schwachstellen wurden intern gefunden und behoben. Diese Tabelle
dient der Transparenz; bewusst ohne technische Reproduktionsdetails – die
Fixes sind in der Commit-Historie der jeweiligen Releases nachvollziehbar.

| ID | Bereich | Schwere | Behoben in |
|---|---|---|---|
| SEC-1 | WhatsApp-Webhook: fehlende Signaturpflicht | 🔴 Kritisch | v0.15.5 |
| SEC-2 | Firewall-Regel nicht auf LAN beschränkt | 🔴 Kritisch | v0.15.5 |
| SEC-3 | GitHub-Token-Handhabung im Updater | 🔴 Kritisch | v0.15.5 |
| SEC-4 | CORS-Konfiguration zu weit gefasst | 🟡 Mittel | v0.15.5 |
| SEC-5 | Token-Auslieferung an das Web-UI | 🟡 Mittel | v0.15.5 (entschärft), v0.18.0 (vollständig: keine HTML-Injektion mehr) |
| SEC-6 | Unvollständige Filterung im Shell-Tool | 🟡 Mittel | v0.15.5 |
| SEC-7/8 | WLAN-Zugangsdaten als Prozessargument sichtbar | 🔴 Kritisch | v0.17.0 |
| SEC-9 | Fehlende Eingabevalidierung in Netzwerk-Tools | 🔴 Kritisch | v0.17.0 |
| SEC-10 | Shell-Aufruf statt direktem Prozessstart im Watchdog | 🟡 Mittel | v0.17.0 |
| – | Path-Traversal im Workspace-Dateizugriff | 🔴 Kritisch | v0.17.0 |
| – | Eingabevalidierung in Network-Security-Tools | 🟡 Mittel | v0.17.0 |
| – | Argument-Quoting im Updater | 🟡 Mittel | v0.17.0 |
| – | Netzwerk-Tool vollständig auf Shell-freie Prozessaufrufe umgestellt | 🟡 Mittel | v0.17.0 |

---

## Bekannte Einschränkungen

Diese Punkte sind bewusst dokumentiert, damit Betreiber sie beim Deployment
berücksichtigen können:

- **Kein TLS ab Werk.** Die Kommunikation im LAN ist unverschlüsselt. Wer das
  Dashboard oder die API außerhalb des eigenen Netzes nutzen will, muss einen
  HTTPS-Reverse-Proxy oder ein VPN davorschalten (siehe unten).
- **LLM-Agent mit Systemzugriff.** Wie bei jedem agentischen System besteht
  ein Restrisiko durch Prompt-Injection über verarbeitete Inhalte (Webseiten,
  E-Mails). Gegenmaßnahmen: Tool-Sandbox für Sub-Agenten, Allowlist im
  Shell-Tool, Admin-Gate für systemändernde Aktionen – und: nur
  vertrauenswürdige Nutzer freischalten.
- **Amateur-Projekt.** PiClaw OS wird von einem Micro-Team in der Freizeit
  entwickelt. Trotz Audit und CI kann es schwerwiegende unentdeckte Lücken
  geben.

---

## Deployment-Empfehlungen

### Muss (Heimnetz)

```toml
# /etc/piclaw/config.toml
[whatsapp]
app_secret = "dein-meta-app-secret"   # PFLICHT, wenn WhatsApp aktiv
```

```bash
# Zeitzone korrekt setzen (für Cron-Scheduling)
sudo timedatectl set-timezone Europe/Berlin
```

- Nach der Migration auf Multi-User: nur bekannte Personen mit `/approve`
  freischalten, `piclaw user pending` regelmäßig prüfen.

### Empfohlen (Zugriff von außen)

```nginx
# nginx als HTTPS-Reverse-Proxy
server {
    listen 443 ssl;
    server_name piclaw.deinedomain.de;
    ssl_certificate     /etc/letsencrypt/live/.../fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:7842;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Dann die API nur noch an `127.0.0.1` binden (in `api.py` bzw. Konfiguration),
sodass sie ausschließlich über den Proxy erreichbar ist. Alternativ: VPN
(z.B. WireGuard) und gar keine öffentliche Exposition.

### Niemals

- `sudo piclaw update` ausführen (erzeugt root-eigene `.git`-Dateien → Berechtigungsfehler)
- API-Tokens oder API-Keys committen oder weitergeben (sie liegen in `/etc/piclaw/config.toml` bzw. `users.json` mit restriktiven Rechten)
- Port 7842 per Port-Forwarding direkt ins Internet öffnen
- Unbekannte Telegram-Nutzer freischalten, „nur um zu testen"

---

## Vulnerability Disclosure

Sicherheitslücken bitte **vertraulich** melden – über GitHubs private
Vulnerability-Reports (Security → Report a vulnerability) oder direkt an den
Maintainer. Bitte keinen öffentlichen Issue erstellen, bevor ein Fix verfügbar
ist.

Wir bemühen uns um:
- Bestätigung des Eingangs innerhalb von 48 h
- Einschätzung der Schwere innerhalb von 7 Tagen
- Fix oder Workaround innerhalb von 30 Tagen für kritische Issues

Hinweis: Diese Software wird von einem Micro-Team in der Freizeit entwickelt –
die Fristen sind Zielwerte, keine Garantie.
