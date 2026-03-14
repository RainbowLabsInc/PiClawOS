====================================================================
  PiClaw OS v0.13.2 – Installationsanleitung
  Lies diese Datei zuerst!
====================================================================

WIE INSTALLIEREN (3 Schritte)
-------------------------------

SCHRITT 1 – Diesen Ordner auf die SD-Karte kopieren
  Du liest diese Datei bereits im richtigen Ordner ("piclaw").
  Kopiere diesen gesamten Ordner auf die Boot-Partition
  deiner geflashten SD-Karte (Laufwerk heisst "bootfs").

  Ergebnis auf der SD-Karte:
    bootfs/
    ├── piclaw/        <-- dieser Ordner
    │   ├── piclaw.conf
    │   ├── install.sh
    │   └── piclaw-src/
    ├── config.txt
    └── ...

  Raspberry Pi 5: Falls "bootfs" ein Unterverzeichnis "firmware"
  enthaelt, kopiere den Ordner dort hinein statt direkt in bootfs.

SCHRITT 2 – API-Key eintragen
  Oeffne "piclaw.conf" mit einem Texteditor (Notepad, TextEdit,
  nano – alles funktioniert).

  Das EINZIGE das du ausfullen musst:
    PICLAW_LLM_KEY = "sk-ant-DEIN-API-KEY-HIER"

  API-Key holen (kostenlos testbar):
    Anthropic: https://console.anthropic.com/keys
    OpenAI:    https://platform.openai.com/api-keys
    Kein Key:  Feld leer lassen -> lokales KI-Modell wird genutzt

SCHRITT 3 – SD-Karte einlegen und Installer ausfuehren
  a) SD-Karte in den Pi stecken und einschalten
  b) Ca. 60 Sekunden warten
  c) Per SSH verbinden:
       ssh DEIN_BENUTZERNAME@piclaw.local
  d) Installer starten:
       sudo bash /boot/piclaw/install.sh
     (Pi 5: sudo bash /boot/firmware/piclaw/install.sh)

  Dauer: ca. 3–7 Minuten

FERTIG
  Web-Dashboard:  http://piclaw.local:7842
  KI-Chat:        piclaw
  Konfiguration:  piclaw setup
  Systemstatus:   piclaw doctor

====================================================================
HAEUFIGE PROBLEME
====================================================================

"piclaw.local nicht gefunden"
  -> Warte laenger (Pi braucht beim ersten Boot manchmal 90s)
  -> Nutze die IP-Adresse (zu finden im Router unter "Geraete")

"bash: install.sh: not found"
  -> Pi 5: Pfad ist /boot/firmware/piclaw/install.sh

"Permission denied"
  -> Benutzername oder Passwort falsch
  -> Im Raspberry Pi Imager: Einstellungen -> Benutzername gesetzt?

Kein API-Key zur Hand?
  -> Feld leer lassen, nach Installation:
       piclaw model download
     (laedt Phi-3 Mini herunter, ~2.4 GB, danach kein Internet mehr)

====================================================================
