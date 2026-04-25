# 🔐 PiClaw OS – Security Documentation

> Letzte Aktualisierung: 2026-04-24  
> Version: v0.17.0

---

## Überblick

PiClaw OS ist für den Betrieb im **lokalen Heimnetzwerk** ausgelegt. Es ist kein
öffentlich exponiertes System und sollte **nicht ohne Absicherung** (Reverse Proxy,
HTTPS, VPN) aus dem Internet erreichbar sein.

---

## Sicherheitsarchitektur

### Authentifizierung

| Kanal | Methode | Stärke |
|---|---|---|
| REST-API `/api/*` | Bearer Token (32 Byte random, `secrets.token_urlsafe`) | ✅ Stark |
| WebSocket `/ws/chat` | Bearer Token als Query-Parameter | ✅ Gut |
| Telegram | Chat-ID Whitelist (nur konfigurierte ID wird akzeptiert) | ✅ Stark |
| WhatsApp | HMAC-SHA256 Signatur via `app_secret` – **Pflicht** | ✅ Stark (wenn konfiguriert) |
| Threema | Threema-Gateway Eigenverifizierung | ✅ Gut |
| `/health` | Unauthentifiziert | ℹ️ Nur Status-OK, kein Datenleak |

### Dateisystem

| Datei | Permissions | Inhalt |
|---|---|---|
| `/etc/piclaw/config.toml` | `600 (piclaw:piclaw)` | API-Keys, Token, Passwörter |
| `/etc/piclaw/watchdog.toml` | `640 (piclaw-watchdog:piclaw-watchdog)` | Watchdog-Konfiguration |

> **Hinweis:** Der `piclaw-watchdog` User hat via ACL (`setfacl`) Leserechte auf kritische Systemdateien (wie `config.toml`, `/etc/sudoers`, `/etc/ssh/sshd_config`, `systemd-units`) für Integrity-Checks.
| `/var/log/piclaw/*.log` | `640` | Logs – keine API-Keys (gemaskert) |

### Sub-Agent Sandbox

Zwei-Tier-System in `piclaw/agents/sandbox.py`:

- **Tier 1 – BLOCKED_ALWAYS:** `shell`, `shell_exec`, `system_reboot`, `watchdog_stop`, `updater_apply` u.a. – kein Override möglich außer `privileged=True`
- **Tier 2 – BLOCKED_BY_DEFAULT:** `service_stop/restart`, `gpio_write`, `network_set` – nur mit `trusted=True` und explizitem allowlist-Eintrag

---

## Bekannte Schwachstellen & Status

### 🔴 Kritisch – Behoben in v0.17.0

#### SEC-7: WiFi-Passwort in Prozessliste – `network.py` ✅ BEHOBEN
**Beschreibung:** `wifi_connect()` übergab das WiFi-Passwort als CLI-Argument an `nmcli`:
`nmcli dev wifi connect <SSID> password <PASSWORT>`. Das Passwort war damit für alle
lokalen User über `ps aux` oder `/proc/<pid>/cmdline` lesbar, solange der Verbindungsaufbau
lief.

**Impact:** Klartext-Passwort-Diebstahl durch jeden lokalen Benutzer oder Prozess.

**Fix (Commit `86c6a22`):** `--ask`-Flag + Übergabe via stdin:
```python
cmd = ["nmcli", "--ask", "dev", "wifi", "connect", ssid]
return await _run(cmd, timeout=30, input_data=password + "\n")
```
Passwort erscheint nicht mehr als Prozessargument.

---

#### SEC-8: WiFi-Passwort in Prozessliste – `wizard.py` ✅ BEHOBEN
**Beschreibung:** Gleiche Schwachstelle wie SEC-7 im Setup-Wizard (`step_wifi()`).
`subprocess.run(["nmcli", ..., "password", password])` – Passwort sichtbar in `ps aux`.

**Impact:** Wie SEC-7, trifft Nutzer während des initialen Setups.

**Fix (Commit `e013dab`):** `subprocess.run(..., input=password+"\n")` mit `--ask`-Flag.
Die Fixes wurden separat entdeckt – SEC-7 in `network.py` wurde zuerst behoben,
`wizard.py` war in der initialen Review übersehen worden.

---

#### SEC-9: Argument-Injection in `network_monitor.py` (nmap/ping) ✅ BEHOBEN
**Beschreibung:** Die Funktionen `scan_devices()`, `port_scan()` und `ping_host()` leiteten
Benutzereingaben (IP-Range, IP-Adresse, Hostname) ohne Validierung direkt als Argumente
an `nmap` und `ping` weiter. Ein Angreifer konnte über den LLM-gesteuerten Agent
präparierte Strings einspeisen (z.B. `192.168.1.0/24 --script malicious`).

**Impact:** Argument-Injection in externe Prozesse via Agent-Eingaben.

**Fix (Commit `800ae27`):** Strikte Eingabevalidierung vor jedem Prozessaufruf:
- IP-Adressen: `ipaddress.ip_address()` / `ipaddress.ip_network()`
- Hostnames: Regex `^[a-zA-Z0-9._-]+$`
- Ungültige Eingaben werden mit Fehlermeldung abgelehnt, kein Prozessstart

---

### 🟡 Mittel – Behoben in v0.17.0

#### SEC-10: `subprocess_shell` in `watchdog.py` ✅ BEHOBEN
**Beschreibung:** `_check_services()` nutzte `asyncio.create_subprocess_shell()` mit einem
f-String: `f"systemctl is-active {svc} 2>/dev/null"`. Obwohl `WATCHED_SERVICES` hardcoded
ist, öffnete dies grundsätzlich Shell-Injection – etwa wenn die Liste je dynamisch befüllt würde.

**Impact:** Theore­tische Shell-Injection bei dynamischen Service-Namen; schlechte Praxis.

**Fix (Commit `86c6a22`):** Umgestellt auf `asyncio.create_subprocess_exec("systemctl", "is-active", svc)` –
kein Shell-Kontext, kein Injection-Risiko.

---

### 🔴 Kritisch – Behoben in v0.15.5

#### SEC-1: WhatsApp Webhook Auth-Bypass ✅ BEHOBEN
**Beschreibung:** `verify_signature()` gab `return True` zurück wenn kein `app_secret`
konfiguriert war. Jeder im lokalen Netzwerk konnte über `POST /webhook/whatsapp`
beliebige Befehle an Dameon senden – ohne Authentifizierung.

**Impact:** Unauthentifizierte Remote Code Execution im Netzwerk-Scope.

**Fix (Commit 1fe2ff7):** `return False` + Warning-Log wenn kein `app_secret` gesetzt.
Konsequenz: WhatsApp-Integration erfordert jetzt zwingend `app_secret` in config.toml.

---

#### SEC-2: UFW öffnete Port 7842 für das Internet ✅ BEHOBEN
**Beschreibung:** `install.sh` führte `ufw allow 7842/tcp` aus – ohne Quelladressen-
Einschränkung. Bei öffentlicher IP-Adresse oder Port-Forwarding war die gesamte API
ohne Netzwerkschutz erreichbar. Da Token über HTTP (kein TLS) übertragen werden,
wäre ein passiver Angreifer bereits nach dem ersten Request im Besitz des Tokens.

**Impact:** Vollständiger API-Zugang bei öffentlicher IP.

**Fix (Commit 1fe2ff7):** UFW-Regeln beschränkt auf RFC-1918 LAN-Ranges:
`192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, `127.0.0.1`.

---

#### SEC-3: Command Injection + Token in Prozessliste (Updater) ✅ BEHOBEN
**Beschreibung:** `_git_remote_url()` bettet den GitHub-Token in die URL ein:
`https://x-access-token:{token}@github.com/...`. Diese URL wurde dann in einem
Shell-f-String verwendet: `_run(f"... git remote set-url origin '{url}' 2>&1")`.

Zwei Probleme:
1. **Token in Prozessliste:** `ps aux` zeigt den Token im Klartext als Prozessargument
2. **Shell Injection:** Ein `repo_url` mit Sonderzeichen (z.B. `'`) bricht aus dem Shell-String aus

**Impact:** Token-Diebstahl via `ps aux` by any local user; Shell Injection wenn `repo_url` kompromittiert.

**Fix (Commit 1fe2ff7):** GitHub-Token wird via `git credential store` (~/.git-credentials, chmod 600)
konfiguriert statt in die URL eingebettet. Keine Tokens mehr in Prozessargumenten.

---

### 🟡 Mittel – Behoben in v0.15.5

#### SEC-4: CORS `allow_origins=["*"]` auf HTTP ✅ BEHOBEN
**Beschreibung:** Die FastAPI-App erlaubte Cross-Origin-Requests von beliebigen Domains.
Kombiniert mit HTTP (kein TLS) könnte eine Malicious-Website im Browser des Nutzers
API-Calls absetzen, wenn Port 7842 erreichbar ist.

**Impact:** Cross-Site-Request-Forgery gegen API bei erreichbarem Port.

**Fix (Commit folgt):** `LocalNetworkCORSMiddleware` ersetzt `allow_origins=["*"]`.
Erlaubt nur RFC-1918 IPs, `localhost`, `127.0.0.1`, `piclaw.local`.
Externe Origins werden abgelehnt – unabhängig vom UFW-Status.

---

#### SEC-5: Bearer Token im HTML über HTTP ✅ TEILWEISE BEHOBEN
**Beschreibung:** Die `/`-Route injizierte `window.PICLAW_TOKEN = "..."` in den HTML-Response.
Da kein TLS vorhanden, konnte das Token durch passives Abhören im LAN erbeutet werden.

**Impact:** Token-Diebstahl bei passivem Angreifer im selben LAN.

**Fix (Commit folgt):** Zwei Verbesserungen:
1. **Token-Injection nur für lokale IPs:** Externe Clients (z.B. bei versehentlich offenem Port) erhalten das Token nicht mehr
2. **Security-Header hinzugefügt:** `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin`, `Cache-Control: no-store`

**Verbleibendes Risiko:** Innerhalb des LANs ist passives Abhören weiterhin möglich (HTTP, kein TLS).
Vollständige Lösung: nginx + Let's Encrypt als Reverse Proxy (siehe Deployment-Empfehlungen).

---

#### SEC-6: Shell-Tool allowlist umgehbar via Command Chaining ✅ BEHOBEN
**Beschreibung:** `_is_allowed()` prüfte nur das erste Wort des Shell-Befehls gegen die
Allowlist. `ls && rm -rf /opt/piclaw` bestand die Prüfung weil `ls` erlaubt ist.

**Impact:** Privilegien-Eskalation durch Command-Chaining wenn Shell-Tool aktiv.

**Fix (Commit folgt):** Explizite Blocklist für Shell-Metacharakter **vor** der allowlist-Prüfung:
`&&`, `||`, `;`, `|`, `$(`, `` ` ``, `${`, `>`, `>>`, `<`
Jeder Befehl mit diesen Zeichen wird pauschal abgelehnt – unabhängig vom ersten Wort.

---

### 🟢 Kein Problem / Best Practice vorhanden

| Bereich | Details |
|---|---|
| Token-Vergleich | `secrets.compare_digest()` – timing-safe ✅ |
| Token-Generierung | `secrets.token_urlsafe(32)` – 256 bit Entropie ✅ |
| config.toml | `chmod 600` in install.sh ✅ |
| API-Keys in Logs | Nur erste 8 Zeichen (`%.8s…`) geloggt ✅ |
| Telegram Sender | `from_id != chat_id` → Fremde werden ignoriert ✅ |
| Path Traversal (Kamera) | `is_relative_to(CAPTURE_DIR)` Guard ✅ |
| Memory/API Auth | Alle `/api/*` hinter `require_auth` ✅ |
| Privileged Sub-Agents | Nur per API mit Bearer Token setzbar (nur du) ✅ |
| `datetime.utcnow()` | Ersetzt durch `datetime.now(timezone.utc)` (Python 3.12+) ✅ |
| `os.fsync()` im Event-Loop | Nur für terminale Stati, nicht "running" ✅ |

---

## Deployment-Empfehlungen

### Muss (Heimnetz)
```toml
# /etc/piclaw/config.toml
[whatsapp]
app_secret = "dein-meta-app-secret"   # PFLICHT wenn WhatsApp aktiv
```

```bash
# Zeitzone korrekt setzen (für Cron-Scheduling)
sudo timedatectl set-timezone Europe/Berlin
```

### Empfohlen (öffentlicher Zugang)
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
Dann `api.py` auf `host = "127.0.0.1"` umstellen (nur localhost).

### Niemals
- `sudo piclaw update` ausführen (erzeugt root-eigene .git-Dateien → Berechtigungsfehler)
- API-Token committen (automatisch in `/etc/piclaw/config.toml` mit chmod 600)
- Port 7842 per Port-Forwarding ins Internet öffnen ohne HTTPS + starkes Passwort

---

## Vulnerability Disclosure

Sicherheitslücken bitte als **private Issue** melden oder direkt an den Maintainer.
Bitte keinen öffentlichen Issue erstellen bevor ein Fix verfügbar ist.

Wir bemühen uns zu:
- Bestätigung des Eingangs innerhalb 48h
- Einschätzung der Schwere innerhalb 7 Tagen
- Fix oder Workaround innerhalb 30 Tagen für kritische Issues

Achtung: Diese Software wird aktuell von einem Micro-Team in ihrer Freizeit entwickelt. 

---

## Changelog Security-Fixes

| Version | Fix | Commit |
|---|---|---|
| v0.17.0 | SEC-7: WiFi-Passwort in Prozessliste (`network.py` → stdin/--ask) | `86c6a22` |
| v0.17.0 | SEC-8: WiFi-Passwort in Prozessliste (`wizard.py` → stdin/--ask) | `e013dab` |
| v0.17.0 | SEC-9: Argument-Injection in `network_monitor.py` (nmap/ping Validation) | `800ae27` |
| v0.17.0 | SEC-10: subprocess_shell → subprocess_exec in `watchdog.py` | `86c6a22` |
| v0.17.0 | Path-Traversal in `write_workspace_file` (PR #123) | `2b7ac6b` |
| v0.17.0 | IP-Validierung in `network_security.py` (PR #128) | `2ca758d` |
| v0.17.0 | Command-Injection in `updater.py` via shlex.quote (PR #132) | `2838785` |
| v0.17.0 | `network.py` komplett auf subprocess_exec (PR #135) | `1e81e45` |
| v0.15.5 | SEC-1: WhatsApp Auth-Bypass | `1fe2ff7` |
| v0.15.5 | SEC-2: UFW LAN-Einschränkung | `1fe2ff7` |
| v0.15.5 | SEC-3: Git Token/Injection | `1fe2ff7` |
| v0.15.5 | SEC-4: CORS LAN-only Middleware | `ec1af4d` |
| v0.15.5 | SEC-5: Security-Header + Token nur für lokale IPs | `ec1af4d` |
| v0.15.5 | SEC-6: Shell Metacharakter-Blocklist | `ec1af4d` |
| v0.15.5 | Bug: `os.fsync()` blockierte Event-Loop | `576c44b` |
| v0.15.5 | Bug: WebSocket Session-Leak | `1fe2ff7` |
| v0.15.5 | Bug: Infinite Recursion LLM Router | `1fe2ff7` |
