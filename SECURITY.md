# 🔐 PiClaw OS – Security Documentation

> Letzte Aktualisierung: 2026-04-05 (Session 9)  
> Version: v0.15.5

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
| `/var/log/piclaw/*.log` | `640` | Logs – keine API-Keys (gemaskert) |

### Sub-Agent Sandbox

Zwei-Tier-System in `piclaw/agents/sandbox.py`:

- **Tier 1 – BLOCKED_ALWAYS:** `shell`, `shell_exec`, `system_reboot`, `watchdog_stop`, `updater_apply` u.a. – kein Override möglich außer `privileged=True`
- **Tier 2 – BLOCKED_BY_DEFAULT:** `service_stop/restart`, `gpio_write`, `network_set` – nur mit `trusted=True` und explizitem allowlist-Eintrag

---

## Bekannte Schwachstellen & Status

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

### 🟡 Mittel – Bekannt, Mitigation vorhanden

#### SEC-4: CORS `allow_origins=["*"]` auf HTTP
**Beschreibung:** Die FastAPI-App erlaubt Cross-Origin-Requests von beliebigen Domains.
Kombiniert mit HTTP (kein TLS) könnte eine Malicious-Website im Browser des Nutzers
API-Calls absetzen, wenn Port 7842 erreichbar ist.

**Mitigation:** Port 7842 ist durch SEC-2 auf LAN-IPs eingeschränkt. Browser blockieren
Cross-Origin-Requests standardmäßig auch bei `allow_origins=["*"]` wenn keine
CORS-preflight-Response kommt – das greift hier da der Port auf LAN beschränkt ist.

**Empfehlung:** Vor Public Release auf konkrete Origins einschränken:
`allow_origins=["http://piclaw.local:7842", "http://localhost:7842"]`

**Status:** Ausstehend – niedriges Risiko im aktuellen Scope.

---

#### SEC-5: Bearer Token im HTML über HTTP
**Beschreibung:** Die `/`-Route injiziert `window.PICLAW_TOKEN = "..."` in den HTML-Response.
Da kein TLS vorhanden, kann das Token durch passives Abhören im LAN erbeutet werden.

**Mitigation:** Durch SEC-2 ist nur das LAN berechtigt. Wer sich im LAN befindet,
hat in einem Heimnetzwerk typischerweise ohnehin physischen Zugang.

**Empfehlung:** Langfristig HTTPS via nginx-Reverse-Proxy oder Caddy.

**Status:** Architekturelle Einschränkung – akzeptiertes Risiko für Heimnetz-Deployment.

---

#### SEC-6: Shell-Tool allowlist umgehbar via Command Chaining
**Beschreibung:** `_is_allowed()` prüft nur das erste Wort des Shell-Befehls gegen die
Allowlist. `ls && rm -rf /opt/piclaw` würde die Prüfung bestehen wenn `ls` erlaubt ist.

**Mitigation:** Shell-Tool ist standardmäßig auf sehr enge Allowlist (`ls`, `cat`, `echo`, etc.)
beschränkt. Subagenten haben keinen Shell-Zugang (Tier 1 BLOCKED_ALWAYS). Nur der
Haupt-Agent (Dameon) kann shell aufrufen.

**Empfehlung:** Blocklist um `&&`, `||`, `;`, `|`, `$(`, `` ` `` ergänzen.

**Status:** Ausstehend – mittel.

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

Wir verpflichten uns zu:
- Bestätigung des Eingangs innerhalb 48h
- Einschätzung der Schwere innerhalb 7 Tagen
- Fix oder Workaround innerhalb 30 Tagen für kritische Issues

---

## Changelog Security-Fixes

| Version | Fix | Commit |
|---|---|---|
| v0.15.5 | SEC-1: WhatsApp Auth-Bypass | `1fe2ff7` |
| v0.15.5 | SEC-2: UFW LAN-Einschränkung | `1fe2ff7` |
| v0.15.5 | SEC-3: Git Token/Injection | `1fe2ff7` |
| v0.15.5 | Bug: `os.fsync()` blockierte Event-Loop | `576c44b` |
| v0.15.5 | Bug: WebSocket Session-Leak | `1fe2ff7` |
| v0.15.5 | Bug: Infinite Recursion LLM Router | `1fe2ff7` |
