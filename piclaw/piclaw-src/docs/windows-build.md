# PiClaw OS – Image-Build auf Windows

## Das Problem: debootstrap läuft nicht nativ unter Windows

`debootstrap` ist ein Linux-Tool das auf dem Linux-Kernel (speziell `chroot`, `mount`, QEMU-Binfmt) aufbaut. Es gibt **keinen nativen Windows-Port** und wird auch keinen geben.

**Aber:** Es gibt zwei saubere Wege um trotzdem unter Windows ein flashbares `.img` zu bauen.

---

## Methode 1: Docker Desktop ⭐ (Empfohlen)

Docker Desktop für Windows startet einen echten Linux-Kernel im Hintergrund (via Hyper-V oder WSL2). Der Build läuft vollständig darin – du merkst davon nichts.

### Voraussetzungen

| Anforderung | Mindest | Empfohlen |
|-------------|---------|-----------|
| Windows | 10 64-bit (Build 19041+) | Windows 11 |
| RAM | 8 GB | 16 GB |
| Freier Speicher | 20 GB | 40 GB |
| CPU | x86-64 mit Virtualisierung | – |

### Schritt 1 – Docker Desktop installieren

1. [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) herunterladen
2. Installer ausführen, alle Standardoptionen übernehmen
3. Neustart wenn gefordert
4. Docker Desktop starten und warten bis das Icon in der Taskleiste grün wird

Verifizieren (PowerShell):
```powershell
docker --version
# Docker version 27.x.x, build ...
```

### Schritt 2 – Repository klonen

```powershell
# PowerShell oder Windows Terminal
git clone https://github.com/youruser/piclaw-os
cd piclaw-os
```

> Noch kein Git? [git-scm.com/download/win](https://git-scm.com/download/win)

### Schritt 3 – cloud-init anpassen

**Wichtig:** Diese Datei vor dem Build editieren:

```powershell
notepad cloud-init\user-data.yml
```

Folgendes unbedingt ändern:
- `ssh_authorized_keys` – euren SSH Public Key eintragen
- `passwd` – neuen Passwort-Hash generieren (siehe unten)
- `timezone` – eure Zeitzone, z.B. `Europe/Berlin`
- Telegram-Token falls vorhanden

Passwort-Hash generieren (in Docker, keine Python-Installation nötig):
```powershell
docker run --rm python:3.11 python3 -c "import crypt; print(crypt.crypt('EuerPasswort', crypt.mksalt(crypt.METHOD_SHA512)))"
```

### Schritt 4 – Image bauen

```powershell
# Windows PowerShell (als normaler User, KEIN Admin nötig)
.\build\docker-build.ps1

# Mit eigener Größe:
.\build\docker-build.ps1 -Size 8G

# Mit eigenem Dateinamen:
.\build\docker-build.ps1 -Output mein-piclaw.img
```

Der Build dauert **15–30 Minuten** (je nach Internetverbindung und CPU).  
Ausgabe: `piclaw-os-arm64.img` im aktuellen Verzeichnis.

### Schritt 5 – SD-Karte flashen

**Option A: Balena Etcher** (einfachste Methode)
1. [etcher.balena.io](https://etcher.balena.io/) herunterladen und installieren
2. "Flash from file" → `piclaw-os-arm64.img`
3. SD-Karte auswählen
4. "Flash!" klicken

**Option B: Raspberry Pi Imager**
1. [raspberrypi.com/software](https://www.raspberrypi.com/software/) herunterladen
2. "Use custom" → `piclaw-os-arm64.img`
3. SD-Karte auswählen
4. Schreiben

**Option C: dd in WSL2** (für Fortgeschrittene)
```bash
# In WSL2-Terminal:
# SD-Karte finden:
lsblk
# Schreiben (ACHTUNG: /dev/sdX korrekt angeben!):
sudo dd if=/mnt/c/Users/DeinName/piclaw-os/piclaw-os-arm64.img \
        of=/dev/sdX bs=4M status=progress
sync
```

---

## Methode 2: WSL2 (Windows Subsystem for Linux)

Direkter als Docker, aber mehr Setup. Ideal wenn WSL2 schon installiert ist.

### WSL2 aktivieren

```powershell
# PowerShell als Administrator:
wsl --install
# Neustart, dann Ubuntu öffnen
```

Oder manuell:
```powershell
# PowerShell als Administrator:
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
# Neustart
wsl --set-default-version 2
# Ubuntu aus dem Microsoft Store installieren
```

### Build in WSL2

```bash
# In Ubuntu/WSL2-Terminal:
sudo apt update && sudo apt install -y \
    debootstrap qemu-user-static binfmt-support \
    parted dosfstools e2fsprogs kpartx rsync curl git

# Repository klonen (WICHTIG: im Linux-Dateisystem, nicht in /mnt/c/!)
cd ~
git clone https://github.com/youruser/piclaw-os
cd piclaw-os

# cloud-init editieren
nano cloud-init/user-data.yml

# Image bauen (als root in WSL2)
sudo bash build/build.sh
```

> **Wichtig:** Das Repository muss im Linux-Dateisystem liegen (`~/` oder `/home/user/`), NICHT in `/mnt/c/`. Dateizugriffe über die Windows-Grenze sind zu langsam und verursachen Permission-Probleme.

Die erzeugte `.img`-Datei ist dann unter Windows erreichbar:
```
\\wsl$\Ubuntu\home\DeinUsername\piclaw-os\piclaw-os-arm64.img
```

### Bekanntes WSL2-Problem: NBD-Kernel-Modul

Der Standard-WSL2-Kernel enthält das `nbd`-Modul nicht. Das Build-Skript nutzt `losetup` statt `nbd`, daher ist das für `build/build.sh` kein Problem. Für `pi-gen` wäre ein Custom-Kernel nötig.

---

## Fehlersuche

### "Virtualization must be enabled"
→ Im BIOS/UEFI Virtualisierung aktivieren (Intel VT-x / AMD-V)

### Build bricht mit "Cannot allocate memory" ab
→ Docker Desktop mehr RAM geben:  
Docker Desktop → Settings → Resources → Memory → mindestens 4 GB

### "permission denied" beim Schreiben der SD-Karte in WSL2
→ SD-Karte Schreibschutz-Schalter (falls vorhanden) deaktivieren  
→ Als root: `sudo dd ...`

### Build dauert sehr lange
→ Normal: 15–30 Minuten für das erste Mal (download von ~300 MB Debian-Paketen)  
→ Zweiter Build deutlich schneller dank Docker-Cache

### Docker Desktop startet nicht
→ Hyper-V aktivieren: `bcdedit /set hypervisorlaunchtype auto` (Admin-PowerShell, Neustart)  
→ Oder WSL2-Backend nutzen: Docker Desktop → Settings → Use WSL 2 based engine

---

## Alternativer Weg ohne Build: install.sh

Wer keinen Image-Build machen möchte (viel einfacher):

1. **Raspberry Pi OS Lite 64-bit** normal flashen (via Raspberry Pi Imager)
2. Pi booten, SSH einloggen
3. `curl -fsSL https://...install.sh | sudo bash`
4. `piclaw setup`

Kein Windows, kein Docker, kein Build – einfach direkt auf dem Pi installieren.  
→ Empfohlen für alle die kein angepasstes Base-Image benötigen.

---

## Vergleich der Methoden

| | Direktinstall | Docker Build | WSL2 Build |
|---|:---:|:---:|:---:|
| Windows-kompatibel | ✅ | ✅ | ✅ |
| Kein Linux nötig | ✅ | ✅ | ✅* |
| Anpassbares Base-Image | ❌ | ✅ | ✅ |
| Flashbares .img-File | ❌ | ✅ | ✅ |
| Setup-Aufwand | ⭐ | ⭐⭐ | ⭐⭐⭐ |
| Empfohlen für | Einsteiger | Windows-User | WSL2-User |

*WSL2 ist ein Linux-Subsystem, aber direkt in Windows integriert
