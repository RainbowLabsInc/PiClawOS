# 🐾 PiClaw OS

**KI-Betriebssystem für den Raspberry Pi 5**  
*v0.17.1 · April 2026*

PiClaw OS verwandelt einen Raspberry Pi 5 in einen autonomen KI-Agenten namens **Dameon**. Er läuft 24/7, überwacht Marktplätze, verfolgt Pakete, steuert Smart-Home-Geräte, reagiert auf Nachrichten und plant Aufgaben – alles natürlichsprachlich steuerbar per Terminal, Telegram oder Web-Dashboard.

---

## ✨ Features

| Feature | Beschreibung |
|---|---|
| 🤖 **KI-Agent „Dameon"** | Autonomer Agent mit persistenter Persönlichkeit (SOUL.md), Memory und natürlichsprachlicher Steuerung |
| 🧠 **Multi-LLM-Router** | Groq, NVIDIA NIM, Anthropic, OpenAI, Gemini, Mistral, Fireworks, Cerebras, lokales Gemma 4 E2B – mit automatischem Fallback |
| 🔍 **LLM-Autonomie** | Findet selbständig neue kostenlose LLM-Backends (Groq, NVIDIA NIM, Cerebras, OpenRouter) |
| 🌡️ **Thermisches Routing** | Wechselt bei Überhitzung automatisch auf sparsamere Cloud-Backends |
| 🛒 **Marketplace-Suche** | Kleinanzeigen, eBay, eGun, VDB, willhaben, Troostwijk, Zoll-Auktion, Web – PLZ, Stadtname, Radius, Preisfilter |
| 🌐 **Web-Suche** | DuckDuckGo-Integration mit echten Shop-URLs, Preis-Modus und Quellen-Modus |
| 👁️ **Sub-Agenten** | Autonome Hintergrund-Agenten mit Cron-, Interval- oder Continuous-Schedule |
| ⚡ **Direct Tool Mode** | Sub-Agenten ohne LLM – 0 Token-Verbrauch bei Routine-Tasks |
| 📦 **ClawHub Skills** | Skills von [clawhub.ai](https://clawhub.ai) mit einem Befehl installieren |
| 📢 **Benachrichtigungen** | Sub-Agenten-Ergebnisse automatisch via Telegram |
| 📡 **Messaging Hub** | Telegram, Discord, Threema, WhatsApp, MQTT |
| 🏠 **Home Assistant** | REST + WebSocket, 11 Tools, Push-Events in Echtzeit, HA-Shortcut (0 Token) |
| 🧠 **Hybrid Memory** | BM25 + Vektor-Suche (QMD), persistente Fakten über Gespräche hinweg |
| 🌐 **Web-Dashboard** | 8 Tabs: Dashboard · Memory · Sub-Agenten · Soul · Hardware · Metriken · Kamera · Chat |
| 📷 **Kamera** | Pi Camera v2/v3 + USB-Webcams, KI-Bildbeschreibung |
| 🔍 **Netzwerk-Monitoring** | Neue Geräte im LAN erkennen und per Telegram melden (LLM-frei) |
| 📦 **Paket-Tracking** | DHL, Hermes, DPD, GLS, UPS – Carrier-Auto-Erkennung, Parcello-Prognose, Telegram-Alerts |
| 📧 **AgentMail** | Eigene E-Mail-Adresse für Dameon – Versandbestätigungen weiterleiten → automatisches Tracking |
| 🔒 **Netzwerk-Sicherheit** | IP-Block, Tarpit, Honey Traps, WHOIS-Lookup, Abuse-Reports |
| 🔧 **Self-Update** | `piclaw update` – git pull + Service-Neustart |
| 🛡️ **Security-gehärtet** | Path-Traversal, Command-Injection, CORS-Schutz, LAN-only API |

---

## 🚀 Quick Start

### Voraussetzungen
- Raspberry Pi 5 (empfohlen) oder Pi 4
- Raspberry Pi OS Lite 64-bit (Bookworm)
- SD-Karte ≥ 16 GB
- LLM API-Key (optional – lokale Modelle funktionieren offline)

### Installation

```bash
curl -sL https://raw.githubusercontent.com/RainbowLabsInc/PiClawOS/main/piclaw-os/boot/piclaw/install.sh \
  | sudo bash
```

**Nach der Installation:**
```bash
piclaw setup    # LLM-Key, Telegram, Home Assistant konfigurieren
piclaw doctor   # Systemcheck – alle grün?
piclaw          # Chat starten
```

**Web-Dashboard öffnen:** `http://piclaw.local:7842`

---

## 🗣️ Bedienung

Dameon ist über vier Wege erreichbar – alle verstehen natürliche Sprache auf Deutsch und Englisch.

### 1. Terminal (SSH)

Die direkteste Schnittstelle. Nach `piclaw` erscheint eine interaktive Chat-Sitzung:

```
piclaw@PiClaw:~ $ piclaw

  Dameon v0.17.1 · bereit
  Tippe deine Nachricht oder 'exit' zum Beenden.

> Wie warm ist der Pi gerade?
🌡 CPU: 51.2°C · GPU: 49.8°C · Throttling: nein

> Suche auf Kleinanzeigen nach einem Rasenmäher in 21224 unter 200€
🔍 Suche auf kleinanzeigen.de nach: Rasenmäher, PLZ 21224 …
```

### 2. Telegram

Schreib einfach deinem Bot – er antwortet wie im Terminal:

```
Du:     Schalte das Wohnzimmerlicht aus
Dameon: 🌑 Wohnzimmerlicht ausgeschaltet

Du:     Wo ist mein Paket?
Dameon: 📦 DHL · Wird heute zugestellt
        Zeitfenster: 13:00 – 17:00 Uhr

Du:     Überwache Kleinanzeigen auf Makita Rasenmäher in 21224, 50km
Dameon: ✅ Monitor_Makita_Rasenmaher gestartet – prüft stündlich
```

Dameon sendet **von sich aus** Nachrichten, wenn:
- Ein Sub-Agent ein neues Ergebnis findet
- Ein Paket-Status sich ändert
- Ein neues Gerät im Netzwerk auftaucht
- Ein HA-Event ausgelöst wird (Bewegung, Tür, Rauch …)

### 3. Web-Dashboard

Öffne `http://piclaw.local:7842` im Browser. Das Dashboard hat 8 Tabs:

| Tab | Funktion |
|---|---|
| **Dashboard** | CPU-Temperatur, RAM, Dienste-Status, letzte Nachrichten |
| **Chat** | Browser-basierter Chat mit Streaming |
| **Sub-Agenten** | Alle Agenten anzeigen, starten, stoppen, erstellen |
| **Memory** | Gespeicherte Fakten durchsuchen und bearbeiten |
| **Soul** | Persönlichkeit (SOUL.md) live bearbeiten |
| **Hardware** | Sensoren, GPIO, Kamera, Netzwerk |
| **Metriken** | CPU/RAM-Verlauf, Temperatur-Graphen |
| **Kamera** | Livebild, Snapshot mit KI-Beschreibung |

### 4. Natürliche Sprache – Beispiele

**Marktplatz & Suche:**
```
> Suche auf Kleinanzeigen nach einem Raspberry Pi 5 in Hamburg unter 80€
> Gibt es einen Sauer 505 in 8x57 IS auf VDB?
> Wo kann ich eine Makita Kreissäge kaufen?
> Zeig mir Troostwijk-Auktionen in der Nähe von 21224
> Suche Behörden-Versteigerungen auf Zoll-Auktion für Werkzeug
```

**Pakete:**
```
> Tracke 1Z999AA10123456784
> Wo ist mein Amazon-Paket?
> Füge diese Sendungsnummer hinzu: 00340434161094042557
```

**Home Assistant:**
```
> Mach das Licht in der Küche an
> Stelle den Thermostat Schlafzimmer auf 20°C
> Welche Lampen brennen gerade?
> Ist die Haustür zu?
```

**Sub-Agenten erstellen:**
```
> Erstelle einen Agenten der täglich um 07:30 die Temperatur und CPU meldet
> Überwache Kleinanzeigen auf Schweißgeräte in 21224 stündlich
> Prüfe jede Stunde ob neue Troostwijk-Auktionen in Deutschland sind
```

**LLM verwalten:**
```
> Finde neue kostenlose KI-Backends
> Welche LLM-Backends sind aktiv?
> Teste das Groq-Backend
```

**Netzwerk:**
```
> Scanne das Netzwerk nach allen Geräten
> Wer ist 192.168.1.x?
> Blockiere 185.220.101.5
> Deploye eine Labyrinth-Falle auf Port 2222
```

---

## 🤖 Unterstützte LLM-Provider

| Key-Präfix | Provider | Empfohlenes Modell | Geschwindigkeit |
|---|---|---|---|
| `gsk_` | **Groq** | llama-3.3-70b-versatile | ⚡ Sehr schnell |
| `nvapi-` | NVIDIA NIM | Llama 3.3 70B / Llama 4 | 🔄 Gut |
| `sk-ant-` | Anthropic | Claude Sonnet 4 | 🔄 Gut |
| `AIza` | Google Gemini | Gemini 2.0 Flash | 🔄 Gut |
| `fw-` | Fireworks AI | Llama 3.1 70B | 🔄 Gut |
| `csk-` | Cerebras | Llama 3.3 70B | ⚡ Sehr schnell |
| `sk-` | OpenAI / Mistral | GPT-4o | 🔄 Gut |
| *(leer)* | Lokal (Gemma 4 E2B) | gemma-4-e2b-q4_k_m.gguf | 🐢 Offline-Fallback |

### Smart Routing

Der Multi-LLM-Router wählt automatisch das beste Backend je nach Aufgabe:

| Anfrage-Typ | Backend (Beispiel) | Warum |
|---|---|---|
| HA-Steuerung | `groq-actions` | Schnell, Tool-Calling, 30k TPM |
| Allgemeine Fragen | `groq-general` | Hohe Tokenrate |
| Komplexe Analysen | `nvidia-nim` | Größeres Kontextfenster |
| Offline / Notfall | Lokales Gemma 4 E2B | Immer verfügbar |

```bash
piclaw llm list                          # Alle Backends anzeigen
piclaw llm add --name groq-primary ...   # Backend hinzufügen
piclaw llm test groq-primary             # Backend direkt testen
```

### LLM-Autonomie

Dameon findet selbständig neue kostenlose Backends:
```
> Finde neue kostenlose KI-Backends
> Füge automatisch neue LLM-Anbieter hinzu
```

Unterstützte Provider ohne Kosten: **Groq · NVIDIA NIM · Cerebras · OpenRouter**

---

## 🛒 Marketplace-Suche

Dameon sucht auf 8 Plattformen gleichzeitig:

| Plattform | Land | Besonderheiten |
|---|---|---|
| **Kleinanzeigen.de** | 🇩🇪 | PLZ + Umkreis, Kategorie |
| **eBay.de** | 🇩🇪 | Auktionen + Sofortkauf |
| **eGun.de** | 🇩🇪 | Waffen & Zubehör |
| **VDB** | 🇩🇪 | Waffen & Jagd |
| **willhaben.at** | 🇦🇹 | PLZ + Stadtname, areaId |
| **Troostwijk** | 🌍 | Industrie-Auktionen, PLZ + Radius |
| **Zoll-Auktion.de** | 🇩🇪 | Behörden-Versteigerungen, PLZ + Radius |
| **Web (DDG)** | 🌐 | Allgemeine Produktsuche mit echten URLs |

```
> Suche auf Kleinanzeigen nach einem Raspberry Pi 5 in Hamburg unter 80€
> Gibt es Troostwijk-Auktionen um PLZ 21224 im Umkreis von 50km?
> Zeige Behörden-Versteigerungen für Werkzeug in meiner Nähe
> Wo kann ich eine Makita Kreissäge kaufen?
```

### Sub-Agenten für dauerhafte Überwachung

```
> Überwache Kleinanzeigen auf Makita Rasenmäher in 21224, 50km Umkreis
> Prüfe stündlich ob neue Sauer 505 8x57 auf VDB erscheinen
```

Sobald ein neues Ergebnis auftaucht → **sofortige Telegram-Nachricht**.

---

## 📦 Paket-Tracking

```
> Tracke 00340434161094042557
> Wo ist mein Paket?
> Alle Pakete anzeigen
```

Dameon erkennt den Carrier automatisch und meldet Statusänderungen per Telegram:

```
📦 Hermes – Amazon Bestellung
Status: In Zustellung
Zeitfenster: 14:00 – 17:30 Uhr
```

**Drei Wege Pakete hinzuzufügen:**
- **Chat/Telegram:** Trackingnummer direkt senden
- **AgentMail:** Versandbestätigung an `dameon@agentmail.to` weiterleiten → automatische Erkennung
- **Textnachricht:** Langen Text mit Trackingnummer einfach senden

Unterstützte Carrier: **DHL · Hermes · DPD · GLS · UPS · Amazon · FedEx**  
Zustellprognose via [Parcello](https://parcello.org) – KI-basiertes Zeitfenster für alle großen Carrier.

---

## 👁️ Sub-Agenten System

Sub-Agenten laufen im Hintergrund und handeln selbständig:

```
> Erstelle einen Agenten der täglich um 08:00 die CPU-Temperatur meldet
> Überwache mein Netzwerk auf neue Geräte
> Prüfe stündlich Kleinanzeigen auf Sauer 505
```

**Schedule-Formate:**
```
once              – einmalig
interval:3600     – alle 60 Minuten
cron:0 8 * * *    – täglich um 08:00
continuous        – Endlosschleife
```

**⚡ Direct Tool Mode** – für reine Monitoring-Tasks ohne LLM:
```
Monitor_Netzwerk:  288 Runs/Tag × 0 LLM-Calls = 0 Token-Verbrauch
Monitor_Pakete:    48  Runs/Tag × 0 LLM-Calls = 0 Token-Verbrauch
```

**Verwaltung:**
```bash
piclaw agent list            # Alle Agenten + Status
piclaw agent run <name>      # Sofortiger Test-Run
piclaw agent stop <name>     # Agenten pausieren
piclaw agent remove <name>   # Agenten löschen
```

Oder per Chat:
```
> Zeig mir alle laufenden Agenten
> Führe den CronJob_0800 jetzt aus
> Stopp den Monitor_Netzwerk
```

---

## 🏠 Home Assistant

```
> Schalte das Wohnzimmerlicht aus
> Stelle den Thermostat auf 22°C
> Welche Geräte sind gerade eingeschaltet?
> Ist die Haustür zu?
```

**11 HA-Tools:** `ha_turn_on`, `ha_turn_off`, `ha_toggle`, `ha_get_state`, `ha_list_entities`, `ha_set_temperature`, `ha_call_service`, u.a.

**HA-Shortcut:** Einfache Schaltbefehle ohne LLM, unter 100 ms, 0 Token.

**Push-Events:** Bewegung, Türen, Alarm, Rauchmelder → sofortige Telegram-Benachrichtigung.

Konfiguration in `piclaw setup` oder direkt in `config.toml`:
```toml
[home_assistant]
url   = "http://homeassistant.local:8123"
token = "ey..."
```

---

## 🌐 Web-Suche

```
> Wo kann ich einen Raspberry Pi 5 kaufen?
> Suche nach dem günstigsten Preis für eine Makita DK0172G
> Was sind die besten Ergebnisse für Sauer 505?
```

**Zwei Modi:**
- **`sources`** – Auflistung relevanter Webseiten mit echten Links
- **`price`** – Preisvergleich über mehrere Shops mit direkten Produktlinks

Die Suche läuft über DuckDuckGo ohne Tracking und gibt echte Shop-URLs zurück (keine Redirect-Links).

---

## 📦 ClawHub Skills

Skills von [clawhub.ai](https://clawhub.ai) erweitern Dameons Fähigkeiten ohne Code:

```bash
piclaw skill search calendar          # Skill suchen
piclaw skill info caldav-calendar     # Details anzeigen
piclaw skill install caldav-calendar  # Installieren
piclaw skill list                     # Alle installierten Skills
piclaw skill remove caldav-calendar   # Entfernen
```

Nach der Installation wird der SKILL.md-Inhalt automatisch in jeden Chat injiziert.

---

## 💻 CLI-Referenz

```bash
# Basis
piclaw                       # Chat starten
piclaw setup                 # Einrichtungsassistent
piclaw doctor                # Vollständiger Systemcheck
piclaw update                # Update via git pull + Neustart

# LLM
piclaw llm list              # Backends anzeigen
piclaw llm test <n>          # Backend direkt testen
piclaw llm add ...           # Backend hinzufügen

# Sub-Agenten
piclaw agent list            # Alle Agenten + Status
piclaw agent run <name>      # Sofort ausführen
piclaw agent stop <name>     # Pausieren
piclaw agent remove <name>   # Löschen

# Messaging
piclaw messaging status      # Adapter-Übersicht
piclaw messaging test        # Test-Nachricht senden
piclaw messaging setup       # Interaktiver Setup-Assistent

# Soul / Persönlichkeit
piclaw soul show             # Aktuelles SOUL.md anzeigen
piclaw soul edit             # In $EDITOR öffnen
piclaw soul reset            # Standard wiederherstellen

# Skills
piclaw skill install <slug>  # ClawHub-Skill installieren
piclaw skill list            # Installierte Skills
piclaw skill search <query>  # Skills suchen
piclaw skill remove <slug>   # Skill entfernen

# Sonstiges
piclaw briefing              # Aktuelles Briefing anzeigen
piclaw briefing send         # Via Telegram senden
piclaw backup                # Konfiguration sichern
piclaw backup restore        # Wiederherstellen
piclaw camera snapshot       # Foto + KI-Beschreibung
piclaw config get            # Konfiguration anzeigen
piclaw config set <k> <v>    # Konfiguration ändern
piclaw metrics               # System-Metriken
piclaw debug                 # Interaktives Diagnose-Menü
```

---

## 🏗️ Architektur

```
┌─────────────────────────────────────────────────────────┐
│                  piclaw-api (Port 7842)                  │
│         FastAPI · REST · WebSocket · Dashboard           │
└──────────────────────────┬──────────────────────────────┘
                           │ IPC (/etc/piclaw/ipc/)
┌──────────────────────────▼──────────────────────────────┐
│                  piclaw-agent (Daemon)                   │
│    Agent Dameon · Multi-LLM-Router · Memory              │
│    Sub-Agenten Runner · Messaging Hub                    │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │  Groq    │ │  NVIDIA  │ │ Cerebras │ │  Lokal    │  │
│  │ (prio 9) │ │  (prio7) │ │ (prio 8) │ │ Gemma 4   │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
└──────────┬───────────────────────────────────┬──────────┘
           │                                   │
    Telegram/Discord                    Home Assistant
    WhatsApp/Threema                    MQTT / GPIO
```

```
piclaw-os/
├── piclaw/
│   ├── agent.py              # Haupt-Agent (Dameon)
│   ├── api.py                # FastAPI REST + WebSocket
│   ├── cli.py                # Kommandozeile
│   ├── daemon.py             # Service-Einstiegspunkt
│   ├── ipc.py                # IPC zwischen API und Daemon
│   ├── soul.py               # Persönlichkeit + ClawHub Skill-Injection
│   ├── auth.py               # Bearer-Token-Auth, Rate-Limiting
│   ├── llm/
│   │   ├── multirouter.py    # Multi-Backend-Router mit Fallback
│   │   ├── registry.py       # Backend-Konfiguration
│   │   ├── classifier.py     # Task-Klassifikation (Regex + LLM)
│   │   ├── health_monitor.py # Auto-Repair bei ausgefallenen Backends
│   │   └── api.py            # Anthropic & OpenAI-kompatible Backends
│   ├── agents/               # Sub-Agenten Runner + Registry
│   ├── memory/               # QMD Hybrid-Memory (BM25 + Vektor)
│   ├── tools/
│   │   ├── marketplace.py    # Kleinanzeigen, eBay, willhaben, Troostwijk, …
│   │   ├── suche.py          # Web-Suche (DuckDuckGo, sources + price)
│   │   ├── parcel_tracking.py
│   │   ├── homeassistant.py
│   │   ├── clawhub.py        # ClawHub Skill-Manager
│   │   ├── network_monitor.py
│   │   ├── network_security.py
│   │   └── shell.py
│   ├── messaging/            # Telegram, Discord, MQTT, Threema, WhatsApp
│   └── hardware/             # Thermal, GPIO, Sensoren, Kamera
├── systemd/                  # Service-Definitionen
└── docs/                     # Handbücher DE + EN
```

**Konfigurationsverzeichnis auf dem Pi:**
```
/etc/piclaw/
├── config.toml           # Hauptkonfiguration
├── SOUL.md               # Persönlichkeit von Dameon
├── subagents.json        # Sub-Agenten Registry
├── llm_registry.json     # LLM-Backend-Registry
├── skills/               # Installierte ClawHub-Skills
├── models/               # Lokale GGUF-Modelle
├── memory/               # QMD Vektordatenbank
└── crashes/              # Crash-Dumps für Debugging
```

---

## 🛡️ Netzwerk-Sicherheit

```
> Scan das Netzwerk auf alle verbundenen Geräte
> Whois-Lookup für 185.220.101.5
> Blockiere die IP 185.220.101.5
> Deploye eine Labyrinth-Falle auf Port 2222
> Erstelle einen Abuse-Report für 185.220.101.5
```

**Honey Traps:**

| Typ | Beschreibung |
|---|---|
| `labyrinth` | Simuliert SSH-Session – hält Angreifer beschäftigt |
| `rickroll` | HTTP-Redirect zu YouTube – für Web-Scanner |
| `sinkhole` | Gefälschte gzip-Daten – verwirrt automatisierte Tools |

> ⚠️ iptables-Befehle erfordern sudo. Lokale IPs (192.168.x.x) sind automatisch geschützt.

**Sicherheitsmaßnahmen im System:**
- CORS auf LAN-Adressen beschränkt (kein Zugriff aus dem Internet)
- Bearer-Token-Auth mit Rate-Limiting (10 Fehlversuche → 15 Min. Lockout)
- Command-Injection-Schutz in Shell- und Netzwerk-Tools
- Path-Traversal-Schutz in Dateizugriff und Kamera-Endpoints
- GitHub-Token via Credential Store (nie in Prozessliste sichtbar)

---

## 🛠️ Troubleshooting

```bash
piclaw doctor                              # Vollständiger Check
journalctl -u piclaw-agent -n 50           # Service-Logs
journalctl -u piclaw-api -n 50             # API-Logs
strings /var/log/piclaw/agent.log | tail   # Agent-Logs
piclaw llm test <n>                        # LLM-Backend testen
cat /etc/piclaw/crashes/*.log              # Crash-Dumps anzeigen
```

| Problem | Lösung |
|---|---|
| Agent antwortet nicht | `piclaw doctor` → LLM-Status prüfen |
| Telegram sendet nicht | `piclaw messaging test` |
| `piclaw update` fehlgeschlagen | `sudo chown -R piclaw:piclaw /opt/piclaw/.git` |
| Sub-Agent startet nicht | `journalctl -u piclaw-agent \| grep <name>` |
| `piclaw skill install` Permission denied | `sudo chown -R piclaw:piclaw /etc/piclaw/skills` |
| LLM-Backend gibt 400 zurück | `piclaw llm test <n>` → Modell prüfen |
| Marketplace findet nichts | PLZ oder Stadtname explizit angeben |
| Paket-Tracking hängt | Trackingnummer nochmals senden oder Carrier manuell angeben |

---

## 🗺️ Roadmap

| Version | Feature | Status |
|---|---|---|
| v0.15 | Basis-System, Marketplace, Telegram, Web-Dashboard | ✅ |
| v0.16 | Security-Audit (6 CVEs), Troostwijk, Stabilität | ✅ |
| v0.17 | LLM-Autonomie, Zoll-Auktion, VDB, Web-Suche, Router-Fixes | ✅ |
| v0.18 | Queue System (parallele CLI + Telegram Anfragen) | 🔲 |
| v0.19 | Willhaben Kategorie-Filter | 🔲 |
| v0.20 | Kamera-Tools vollständig integriert | 🔲 |
| **v1.0** | **Public Release** | 🔲 |
| v1.1 | Mehrsprachigkeit (DE / EN / ES) | 🔲 |

---

## 📄 Lizenz

MIT – Rainbow Labs Inc.

---

## 🙏 Gebaut mit

[llama-cpp-python](https://github.com/abetlen/llama-cpp-python) · [FastAPI](https://fastapi.tiangolo.com) · [QMD](https://github.com/tobilu/qmd) · [python-telegram-bot](https://python-telegram-bot.org) · [Scrapling](https://github.com/D4Vinci/Scrapling) · [croniter](https://github.com/pallets/croniter) · [ClawHub](https://clawhub.ai) · [Parcello](https://parcello.org)

---

<div align="center">
  <a href="https://ko-fi.com/rainbowlabsinc">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Ko-fi">
  </a>
</div>

[Dokumentation](piclaw-os/README.md) · [Sicherheit](SECURITY.md) · [Changelog](piclaw-os/CHANGELOG.md) · [☕ Spenden](https://ko-fi.com/rainbowlabsinc)
