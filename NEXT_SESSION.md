# PiClaw OS – Nächste Session
**Letzte Aktualisierung:** 2026-04-18 (Session 11 – Wizard-Repair + HA-Shortcut Bugs)
**Version:** v0.17.0 🟢

---

## ✅ Diese Session abgeschlossen

### Bugs behoben
- **`wizard.py` HA-Save** – lokaler Hotfix mit `re.sub()` ohne `import re` verursachte beim Speichern der HA-Config `NameError: name 're' is not defined`. Rollback via `git checkout`, der Patch war nicht auf `main`.
- **`_ha_shortcut` TypeError** – `on_kw + off_kw + toggle_kw + [liste]` verband Tuples mit einer Liste → Python `TypeError` → generisches "Internal error processing message" in Telegram. Fix: Liste → Tuple.
- **`_ha_shortcut` Entity-Auswahl** – bei mehreren schaltbaren Entities im selben Raum (Licht + Rolladen + Steckdose) wurde alphabetisch das erste gewählt. "Schalte das Licht in der Küche an" landete auf `cover.rolladen_kuche`. Neue `device_hint`-Logik (licht/rolladen/ventilator/steckdose) priorisiert korrekt. Live getestet mit Gäste-WC.
- **`messaging/hub.py` Traceback-Schlucker** – `log.error(..., e)` → `log.exception(...)`. Vorher landete nur `str(e)` im Log, ganze Tracebacks waren unsichtbar. Genau wegen dieses Schluckers war der HA-Shortcut-Bug so lange unentdeckt.
- **`tools/fix_install_path.sh`** – rief `pip install -e /opt/piclaw` auf, aber `pyproject.toml` liegt in `/opt/piclaw/piclaw-os/`. Bei jeder Symlink-Reparatur kam "not a Python project". Fix committed: `38acebe`.

### Manuelle Reparatur auf dem Pi
- `/opt/piclaw/piclaw` Symlink wiederhergestellt (über repariertes fix_install_path.sh)
- Home Assistant konfiguriert und verbunden: `http://homeassistant:8123` ✅
- `piclaw.bak/` (statischer Altcode) entfernt

### Commits auf `main`
- `38acebe` fix(install): pip install -e mit korrektem pyproject-Pfad
- *(noch lokal, wartet auf Commit):* `_ha_shortcut` tuple+list + device-hint + `hub.py` log.exception

---

## 🚨 Top-Priorität nächste Session

### 1. Watchdog Permission-Denied ⚠️ STUMME FEHLER SEIT WOCHEN

**Symptom:**
Alle 5 Minuten, seit mindestens 2026-04-01.

**Ursache:** `piclaw-watchdog`-User hat keine Leserechte auf die zu prüfenden Dateien. Die Integrity-Checks (SHA256-Vergleich) laufen seit Wochen komplett ins Leere — eine Manipulation von `config.toml` oder `/etc/sudoers` würde **nicht erkannt werden**.

**Lösungs-Optionen (Aufwand-Schätzung):**

| Option | Aufwand | Vor/Nachteil |
|---|---|---|
| **A) ACL-Read-Access** | **45 Min** | `setfacl` in install.sh + SECURITY.md-Update. Einfach, funktioniert. Nachteil: Watchdog-User kann API-Keys in config.toml lesen. |
| **B) Separates Integrity-Manifest** | **2–3 Std** | Root-Helper schreibt Hashes in `/var/lib/piclaw/integrity.json` (world-readable). Watchdog vergleicht gegen Manifest. Saubere Trennung. |
| **C) Scope überdenken** | **1 Std** | `config.toml` ändert sich legitim (Tokens, Sub-Agenten) → taugt nicht als Integrity-Target. Rauswerfen, nur stabile Pfade prüfen (SOUL.md, Code, systemd-Units). Separat Root-Hash-Helper für `/etc/sudoers`. |

**Empfehlung:** A als Sofort-Fix, in Folge-Session C aufsetzen (das konzeptionelle Problem: eine ständig geänderte Datei kann kein Integrity-Target sein).

### 2. AgentMail 400 bei LLM-Discovery
Bei proaktiver LLM-Discovery wird eine Mail mit leerer/ungültiger Empfänger-Adresse rausgeschickt:
Vermutlich in `llm/health_monitor.py` oder `tools/agentmail.py`: null/leerer String als Recipient bei Discovery-Report. **Aufwand: ~20 Min** (null-Check + Default-Empfänger).

### 3. Credentials rotieren
- `piclaw config token` → neuen API-Token
- GitHub PAT rotieren: https://github.com/settings/tokens

---

## 🔧 Weitere offene Tasks

### Cover-Intents für Rolladen/Jalousien
Aktuell nur on/off erkannt. "Fahr den Rolladen hoch" findet kein Match. Fix: Neue Keyword-Familie `hoch/runter/öffnen/schließen/auf/zu` → mappt auf `cover.open_cover` / `cover.close_cover`. **Aufwand: ~30 Min.**
Datei: `piclaw-os/piclaw/agent.py` → `_ha_shortcut()`

### Zeitzone-Autosetup im Wizard (v0.17 offen)
`config.py` hat `LocationConfig` bereit. Im Wizard `timezonefinder` nutzen, `timedatectl set-timezone` aufrufen.
Datei: `piclaw-os/piclaw/wizard.py` (~Zeile 1381)

### HA Doctor Fix
`cli.py doctor` macht HTTP-Request mit 5s Timeout direkt nach Neustart → häufig `Nicht erreichbar`. Retry-Logik: 3× mit 10s Pause.

### Query-Extraktion Ortsnamen
Dameon nimmt Ortsnamen in die Query auf: "Gartentisch Rosengarten" statt "Gartentisch".
Fix: Stadtname nach location-Extraktion aus `clean_text` entfernen.

### Troostwijk Umkreis-Monitor einrichten
Nach Update-Runde via Dameon:
> Überwache Troostwijk Auktionen im Umkreis von 100km um 21224

---

## 🤖 Sub-Agenten (Stand 2026-04-18)

| Name | Plattform | Intervall | Status |
|---|---|---|---|
| Monitor_Netzwerk | intern | 5 Min | PROTECTED |
| Monitor_Gartentisch | Kleinanzeigen | 1h | aktiv |
| Monitor_Sonnenschirm | Kleinanzeigen | 1h | aktiv |
| Monitor_Sauer505 | eGun | 1h | aktiv |
| Monitor_TW_Deutschland | Troostwijk Events | 1h | aktiv |
| Monitor_Pakete | AgentMail + DHL | 30 Min | aktiv |
| CronJob_0715 | – | täglich 07:15 | aktiv |

## 🏠 HA-Entities Küche (für device_hint Regression-Tests)
## 🔑 LLM Backends


---

## 📡 CYD/HaleHound-Integration (Geplant)

Hardware: ESP32-2432S028 „Cheap Yellow Display" mit HaleHound-CYD Firmware (https://github.com/JesseCHale/HaleHound-CYD)
Anschluss: USB-Serial an Pi 5 (UART0, 115200 Baud)

### Serielle Befehlsschnittstelle (Patch erforderlich)

HaleHound hat keine native Serial-CLI. Patch-Aufwand: ~50–100 Zeilen C++ in `HaleHound-CYD.ino`.

| Befehl | Funktion | HaleHound-Modul |
|---|---|---|
| `DEAUTH <BSSID> <ch>` | Gerät aus WLAN werfen | WiFi Deauther |
| `LOCKDOWN` | Auth Flood + Deauth gleichzeitig → alle WLAN-Verbindungen kappen | Auth Flood + Deauther |
| `COUNTER_DEAUTH <BSSID> <ch>` | Rück-Deauth bei erkanntem Angriff auf eigenes Netz | WiFi Deauther |
| `SCAN_STATIONS` | Verbundene Clients auflisten (MAC + RSSI) | Station Scanner |
| `PROBE_SNIFF <sek>` | Geräte die sich nähern erkennen (Probe Requests) | Probe Sniffer |
| `BLE_SCAN` | BLE-Geräte in der Nähe | BLE Scanner |
| `AIRTAG_SCAN` | Apple FindMy / AirTag Tracker-Detektion | AirTag Detect |
| `AP_SCAN` | Nachbar-APs (Baseline + neue APs erkennen) | WiFi Scanner |
| `SUBGHZ_REPLAY <profil>` | Gespeichertes SubGHz-Signal abspielen (Tor/Garage) | SubGHz Replay |
| `STATUS` | CYD Heartbeat / bereit? | – |

### Garagentor / Hoftor per Telegram

- Tore nutzen **Festcode** (kein Rolling Code) → CC1101-Replay funktioniert
- - Benötigt: CC1101 HW-863 Modul an CYD (VSPI, CS=GPIO27)
  - - Flow: Telegram-Befehl → Dameon → Serial `SUBGHZ_REPLAY garage` → CYD sendet Signal
    - - Signal einmalig mit HaleHound Replay-Modul aufnehmen und als Profil auf SD-Karte speichern
     
      - ### LOCKDOWN-Modus
     
      - Notfall-Killswitch: Dameon erkennt kritisches Ereignis oder manueller Telegram-Befehl.
      - - CYD startet Auth Flood + Deauth gleichzeitig
        - - Alle WLAN-Verbindungen im Umkreis brechen zusammen (inkl. eigene Geräte!)
          - - Eigener Zugriff danach nur noch per LAN-Kabel oder direkt am Pi
            - - Aufheben: `LOCKDOWN_STOP` oder CYD-Neustart
             
              - ### Rück-Deauth bei Angriff
             
              - - Dameon Monitor erkennt Deauth-Angriff auf eigenes Netz (Quelle-BSSID/MAC bekannt)
                - - Automatisch oder per Telegram-Bestätigung: `COUNTER_DEAUTH <MAC> <ch>`
                  - - CYD sendet Deauth-Storm zurück an Angreifer-Gerät
                   
                    - ### Aufwand-Schätzung
                   
                    - | Task | Aufwand |
                    - |---|---|
                    - | Serial-Command-Parser in HaleHound patchen | 2–3 Std |
                    - | Dameon-Tool `cyd_command(cmd)` via pyserial | 1 Std |
                    - | SubGHz-Profile aufnehmen (Garage + Hoftor) | 30 Min |
                    - | LOCKDOWN-Intent in Dameon + Telegram | 1 Std |
                    - | Rück-Deauth-Erkennung + Counter-Logik | 2 Std |
