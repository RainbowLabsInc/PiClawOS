====================================================================
  PiClaw OS v0.15.1 – Installationsanleitung
====================================================================

SCHNELLSTART (Online-Installation – empfohlen)
-----------------------------------------------

SCHRITT 1 – SD-Karte flashen
  Raspberry Pi Imager → Raspberry Pi OS Lite (64-bit)
  Einstellungen: SSH aktivieren, Benutzer + WLAN setzen

SCHRITT 2 – Pi starten & verbinden
  SD-Karte einlegen, Pi einschalten, ~60s warten
    ssh DEIN_BENUTZERNAME@piclaw.local

SCHRITT 3 – Installer herunterladen & starten
  curl -O https://raw.githubusercontent.com/RainbowLabsInc/PiClawOS/main/piclaw-os/boot/piclaw/install.sh
  sudo bash install.sh

  Dauer: ca. 5–10 Minuten (inkl. GitHub-Download)

FERTIG
  Web-Dashboard:  http://piclaw.local:7842
  KI-Chat:        piclaw
  Ersteinrichtung: piclaw setup
  Systemstatus:   piclaw doctor
  Updates:        piclaw update


====================================================================
OFFLINE-INSTALLATION (SD-Karte, kein Internet)
====================================================================

Vorbereitung (auf dem Entwickler-PC, im piclaw-os/ Verzeichnis):
  make sync     # befüllt piclaw-src/ mit aktuellem Code
  make sdcard   # erstellt piclaw-sdcard-v0.15.1.zip

1. ZIP entpacken → Ordner "boot/piclaw/" auf SD-Karte kopieren
   Ergebnis: bootfs/piclaw/install.sh + piclaw-src/ + piclaw.conf

2. piclaw.conf öffnen und API-Key eintragen (optional):
     PICLAW_LLM_KEY = "nvapi-DEIN-KEY"
   Leer lassen → lokales Gemma 2B Modell wird genutzt

3. Pi booten, SSH verbinden, dann:
     sudo bash /boot/piclaw/install.sh
   (Pi 5: sudo bash /boot/firmware/piclaw/install.sh)


====================================================================
HÄUFIGE PROBLEME
====================================================================

"piclaw.local nicht gefunden"
  → Warte länger (Pi braucht beim ersten Boot bis 90s)
  → IP-Adresse im Router nachschauen

"bash: install.sh: not found"
  → Pi 5: Pfad ist /boot/firmware/piclaw/install.sh

Kein API-Key?
  → Leer lassen, danach: piclaw model download (~1.6 GB Gemma 2B)

Update auf neue Version:
  → piclaw update check    # zeigt ausstehende Updates
  → piclaw update          # git pull + Neustart

====================================================================
