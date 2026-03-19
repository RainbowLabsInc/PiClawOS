# PiClaw OS – SD-Karten-Installation (Empfohlen)

Dies ist der einfachste Weg PiClaw OS zu installieren.
Kein Image-Bau, kein Docker, kein Entwicklungswerkzeug noetig.

## Was du brauchst

- Raspberry Pi 4 oder 5
- SD-Karte (mind. 16 GB, empfohlen 64+ GB)
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/) auf deinem PC
- Diese Datei: `piclaw-os-v0.11.0.zip`

---

## Schritt 1 – Raspberry Pi OS flashen

1. Raspberry Pi Imager starten
2. **Gerät:** Raspberry Pi 5 (oder 4)
3. **Betriebssystem:** Raspberry Pi OS Lite (64-bit) – *kein Desktop*
4. **SD-Karte:** deine Karte auswählen
5. Klick auf **Weiter** → **Einstellungen bearbeiten**:

   | Einstellung | Wert |
   |-------------|------|
   | Hostname | `piclaw` |
   | Benutzername | z.B. `pi` |
   | Passwort | sicheres Passwort wählen |
   | WLAN | SSID + Passwort eintragen |
   | SSH aktivieren | ✓ Ja |
   | Zeitzone | deine Zeitzone |

6. **Speichern** → **Ja** → Flashen abwarten (~3-5 Min)

---

## Schritt 2 – piclaw-Ordner auf SD-Karte kopieren

Nach dem Flashen die SD-Karte im PC lassen (oder kurz raus und wieder rein).

Ein Laufwerk namens **`bootfs`** erscheint im Explorer/Finder.

1. Die Datei `piclaw-os-v0.11.0.zip` entpacken
2. Den Ordner `boot/piclaw/` **komplett** auf das Laufwerk `bootfs` kopieren

   **Ergebnis auf der SD-Karte:**
   ```
   bootfs/
   ├── piclaw/               <-- dieser Ordner wurde kopiert
   │   ├── README.txt
   │   ├── piclaw.conf       <-- hier trägst du deinen API-Key ein
   │   ├── install.sh
   │   └── piclaw-src/
   ├── kernel8.img
   ├── config.txt
   └── ...
   ```

---

## Schritt 3 – piclaw.conf bearbeiten

Im kopierten Ordner die Datei `piclaw.conf` mit einem Texteditor öffnen.

**Das Einzige was du wirklich eintragen musst:**

```
PICLAW_LLM_KEY = "sk-ant-DEIN-API-KEY"
```

Optional aber empfohlen:
```
PICLAW_AGENT_NAME    = "MeinPi"
PICLAW_TELEGRAM_TOKEN   = "1234567890:ABCDE..."
PICLAW_TELEGRAM_CHAT_ID = "987654321"
```

Datei speichern. SD-Karte sicher auswerfen.

---

## Schritt 4 – Pi starten und SSH verbinden

SD-Karte in den Pi, Strom anschließen, 60 Sekunden warten.

```bash
ssh pi@piclaw.local
# oder mit IP-Adresse:
ssh pi@192.168.1.XXX
```

Tipp: `-t` erzwingt ein PTY (empfohlen für den Wizard):
```bash
ssh -t pi@piclaw.local
```

---

## Schritt 5 – Installer ausführen

Nach dem SSH-Login einen einzigen Befehl:

```bash
sudo bash /boot/piclaw/install.sh
```

> **Pi 5:** Der Boot-Pfad ist `/boot/firmware/piclaw/install.sh`

Der Installer läuft ca. 3–7 Minuten und zeigt jeden Schritt an.
Am Ende startet automatisch der Konfigurationswizard für alles was
nicht in piclaw.conf eingetragen war.

---

## Fertig!

```
Web-Dashboard:   http://piclaw.local:7842
KI-Chat:         piclaw
Konfiguration:   piclaw setup
Systemstatus:    piclaw doctor
```

---

## Häufige Probleme

**`piclaw.local` nicht erreichbar**
- Warte länger (erster Boot kann 90s dauern)
- Nutze die IP-Adresse (im Router unter "verbundene Geräte")
- Stelle sicher dass Pi und PC im gleichen Netzwerk sind

**WLAN funktioniert nicht**
- WLAN-Zugangsdaten im Raspberry Pi Imager korrekt eingetragen?
- Alternativ: `PICLAW_WIFI_SSID` und `PICLAW_WIFI_PASSWORD` in piclaw.conf

**`install.sh: not found`**
- Pi 5 nutzt `/boot/firmware/` statt `/boot/`
- Befehl: `sudo bash /boot/firmware/piclaw/install.sh`

**Kein API-Key vorhanden**
- Feld in piclaw.conf leer lassen
- Nach Installation: `piclaw model download` (Phi-3 Mini, ~2.4 GB)
