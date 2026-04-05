# PiClaw OS – Nächste Session
**Letzte Aktualisierung:** 2026-04-05 (Session 9 – Release Prep)
**Version:** v0.16.0 🟢

---

## ✅ Diese Session abgeschlossen

- Security-Audit (SEC-1 bis SEC-6 alle behoben)
- 16 Stabilität/Performance-Bugs behoben (3 Debug-Runden)
- Troostwijk Auktions-Monitor implementiert und deployed
- 7 PRs gemergt, 9 geschlossen
- README, CHANGELOG, ROADMAP, SECURITY.md vollständig aktualisiert
- Version auf v0.16.0 gebumpt

---

## 🚨 Sofort (nach dieser Session)

### 1. Credentials rotieren!
```bash
piclaw config token   # Neuen API-Token generieren
```
GitHub PAT rotieren: https://github.com/settings/tokens/3962689543

### 2. Pi updaten
```bash
sudo chown -R piclaw:piclaw /opt/piclaw/.git
piclaw update
```

### 3. Zeitzone prüfen
```bash
timedatectl status
# Erwartung: Time zone: Europe/Berlin (CEST, +0200)
# Falls nicht: sudo timedatectl set-timezone Europe/Berlin
```

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
