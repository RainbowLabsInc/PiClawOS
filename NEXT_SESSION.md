# PiClaw OS – Nächste Session
**Letzte Aktualisierung:** 2026-04-10 (Session 10 – Security Merges + Troostwijk Umkreissuche)
**Version:** v0.16.1 🟢

---

## ✅ Diese Session abgeschlossen

### PRs gemergt (7 Stück → main)
- **PR #123** 🛡️ Path-Traversal-Fix in `write_workspace_file`
- **PR #128** 🛡️ IP-Validierung in `network_security.py`
- **PR #132** 🛡️ Command-Injection-Fix in `updater.py` (shlex.quote)
- **PR #135** 🛡️ `network.py` komplett auf subprocess_exec umgestellt
- **PR #125** ⚙️ Async-Sensors-Migration (native async statt thread pool)
- **PR #133** ⚙️ Igor: Timezone-Setup, Doctor-Timeout, Query-Fixes
- **PR #129** ⚙️ Location-Regex-Fix + City-Name-Leakage

### Troostwijk Umkreissuche implementiert
- `marketplace.py`: Geo-Utilities (Haversine, PLZ→Coords via zippopotam.us, Stadt→Coords via Nominatim)
- `_search_troostwijk_auctions`: PLZ + Radius Parameter, filtert gegen `collectionDays[].city`
- `agent.py`: Intent-Detection erkennt PLZ + Radius aus natürlicher Sprache
- Live-validiert: PLZ 21224 (Rosengarten) → Hamburg 17km ✅, Pinneberg 39km ✅, Walsrode 65km ✅

### Zoll-Auktion.de als Plattform hinzugefügt
- `_search_zoll_auktion()`: HTML-Scraper für das Auktionshaus von Bund/Ländern/Gemeinden
- Native PLZ + Umkreis-Suche (20/50/100/250/500km serverseitig)
- Parst Titel, Preis (EUR), PLZ+Ort, Restzeit, Anzahl Gebote
- Intent-Detection: "zoll-auktion", "zollauktion" in allen Keyword-Listen
- Emoji: ⚖️ für Text + Telegram Output

---

## 🚨 Sofort (nach dieser Session)

### 1. Pi updaten!
```bash
piclaw update
# Falls das nicht geht (alter Code ohne Token-Auth):
cd /opt/piclaw && sudo git pull
sudo systemctl restart piclaw-api piclaw-agent
```

### 2. Troostwijk Umkreis-Monitor testen
Nach dem Update über Dameon:
```
Überwache Troostwijk Auktionen im Umkreis von 100km um 21224
```
Oder manuell via API:
```bash
curl -X POST http://localhost:7842/api/subagents \
  -H "Authorization: Bearer $(cat /etc/piclaw/api_token)" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Monitor_TW_PLZ21224_100km",
    "description": "Troostwijk Auktionen: PLZ 21224, 100km – stündlich",
    "schedule": "interval:3600",
    "direct_tool": "marketplace_monitor",
    "mission": "{\"query\":\"\",\"platforms\":[\"troostwijk_auctions\"],\"location\":\"21224\",\"country\":\"de\",\"radius_km\":100,\"max_price\":null,\"max_results\":24}"
  }'
```

### 3. Credentials rotieren
```bash
piclaw config token   # Neuen API-Token generieren
```
GitHub PAT rotieren: https://github.com/settings/tokens

---

## 🔧 Offene Tasks (nächste Session)

### Zeitzone-Autosetup im Wizard (v0.17)
`config.py` hat `LocationConfig` bereit. Im Wizard:
```python
from timezonefinder import TimezoneFinder
tf = TimezoneFinder()
tz = tf.timezone_at(lat=lat, lng=lon)  # z.B. "Europe/Berlin"
subprocess.run(["sudo", "timedatectl", "set-timezone", tz])
```
Datei: `piclaw-os/piclaw/wizard.py` → Bereich `# Standort fuer Wetterdaten` (Zeile ~1381)

### HA Doctor Fix (v0.17)
`cli.py` doctor macht HTTP-Request mit 5s Timeout direkt nach Neustart.
Fix: Retry-Logik (3× versuchen mit 10s Pause).
Datei: `piclaw-os/piclaw/cli.py` → `doctor`-Funktion

### Query-Extraktion Ortsnamen (v0.19)
Dameon nimmt Ortsnamen in die Query auf: "Gartentisch Rosengarten" statt "Gartentisch".
Fix: Stadtname nach location-Extraktion aus `clean_text` entfernen.
Datei: `piclaw-os/piclaw/agent.py` → `_detect_marketplace_intent()`

---

## 🤖 Sub-Agenten (aktuell)

| Name | Plattform | Query | Intervall |
|---|---|---|---|
| Monitor_Netzwerk | intern | Neue Geräte | 5 Min (PROTECTED) |
| Monitor_Gartentisch | Kleinanzeigen | Gartentisch, 21224, 20km | 1h |
| Monitor_Sonnenschirm | Kleinanzeigen | Sonnenschirm, 21224, 20km | 1h |
| Monitor_Sauer505 | eGun | Sauer 505 | 1h |
| Monitor_TW_Deutschland | Troostwijk Events | Land=DE, alle Städte | 1h |
| CronJob_0715 | – | Tagesbericht | täglich 07:15 |

## 🏠 HA-Entities
```
light.licht_fernsehzimmer_switch_0, light.licht_schlafzimmer_switch_0
light.licht_esszimmer_switch_0, light.shellyplus1_08b61fd0b64c_switch_0
switch.licht_kuche_switch_0, switch.fernseher, switch.aquarium_licht
cover.shellyplus2pm_d48afc41a22c (Rolladen Büro)
cover.shellyplus2pm_c82e180c7a1c (Rolladen Schlafzimmer)
cover.rolladen_kuche, cover.rollladen_kinderzimmer
```

## 🔑 LLM Backends (aktuell)
```
[10] groq-actions:   llama-3.3-70b-versatile
[ 9] groq-fallback:  kimi-k2-instruct
[ 8] groq-gptoss:    openai/gpt-oss-120b
[ 6] nvidia-nim:     llama-4-maverick
lokal: qwen3-1.7b-q4_k_m (Offline-Fallback)
```
