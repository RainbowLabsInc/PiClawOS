# PiClaw OS — Roadmap

## Status: v0.16.0 (April 2026) 🟢 Release Candidate

Dameon läuft stabil auf Raspberry Pi 5.
- **Security-Audit abgeschlossen** – alle 6 Schwachstellen behoben
- 6 aktive Sub-Agenten (tokenlos: Netzwerk + 4× Marktplatz + Auktionen)
- LLM-Routing: Groq (10/9/8) → NVIDIA NIM (6) → Qwen3 lokal
- Alle kritischen Bugs aus 3 Debug-Runden behoben

---

## ✅ Abgeschlossen

### v0.16.0 — Security-Audit + Stabilisierung (April 2026)
- [x] SEC-1: WhatsApp Auth-Bypass geschlossen
- [x] SEC-2: UFW auf LAN-IPs eingeschränkt
- [x] SEC-3: GitHub-Token aus Prozessliste entfernt
- [x] SEC-4: CORS auf lokales Netzwerk beschränkt
- [x] SEC-5: Security-Header + Token nur für lokale IPs
- [x] SEC-6: Shell Command-Chaining geblockt
- [x] Troostwijk Auktions-Monitor (Stadt/Land, tokenlos)
- [x] LocationConfig für automatische Zeitzonenerkennung
- [x] 16 Stabilität- & Performance-Bugs behoben
- [x] 7 PRs gemergt (Security + Quality)
- [x] SECURITY.md vollständig dokumentiert

### v0.15.5 — marketplace_monitor Refactor (April 2026)
- [x] marketplace_monitor: JSON-Params in mission – neustart-sicher
- [x] Qwen3-1.7B Q4_K_M als Offline-Fallback
- [x] Monitor_Gartentisch, Monitor_Sonnenschirm, Monitor_Sauer505
- [x] Kleinanzeigen Radius-Suche: Location-ID via API
- [x] PATCH /api/subagents/{name}: Live-Update

### v0.15.4 — Home Assistant + Smart Routing (März 2026)
- [x] Home Assistant Integration (11 Tools, Fuzzy-Suche)
- [x] HA-Shortcut: Licht ohne LLM (~0ms, 0 Token)
- [x] Smart LLM Routing: Regex → Pattern → LLM
- [x] LLM Health Monitor: Selbstheilung (404/429/500)
- [x] Monitor_Netzwerk: direct_tool, Dreifach-Schutz

---

## 🚧 Vor v1.0 (Pflicht)

- [ ] **Zeitzone-Autosetup:** `timezonefinder` im Wizard → `timedatectl` setzen
- [ ] **Neuinstallationstest** auf frischem Pi (< 10 Minuten)
- [ ] **HA doctor-Fix:** Retry-Logik beim Neustart (5s Timeout → mehrfach versuchen)
- [ ] **Query-Extraktion:** Ortsnamen nicht in die Artikel-Query aufnehmen
- [ ] **Credentials-Rotation** nach Dev-Sessions dokumentieren/automatisieren

---

## 📋 Geplant

### v0.17 — Zeitzone-Wizard + HA-Erweiterungen
- [ ] Automatische TZ-Erkennung aus Koordinaten im Setup-Wizard
- [ ] `timedatectl set-timezone` aus Wizard heraus aufrufen
- [ ] HA doctor: Retry-Logik mit 30s Timeout
- [ ] Emergency Shutdown via schaltbare Steckdose

### v0.18 — IPC-Reload + Queue
- [ ] Registry-Reload via IPC (kein Daemon-Neustart bei neuem Sub-Agent)
- [ ] Queue für parallele Sub-Agent-Ausführung
- [ ] Sub-Agent-Status in Echtzeit via WebSocket

### v0.19 — Marketplace Erweiterungen
- [ ] Willhaben: Kategorie-Filter
- [ ] Troostwijk: Stadtfilter via API (wenn verfügbar)
- [ ] Query-Extraktion: Ortsnamen sauber entfernen

### v0.20 — Kamera & Sensoren
- [ ] ESP32-CAM / ESPHome vollständig
- [ ] Pond-Camera-Integration

### v1.0 — Stable Release
- [ ] Frische Installation < 10 Minuten
- [ ] `piclaw doctor` alles grün (inkl. HA)
- [ ] Mind. 3 Cloud-LLM-Anbieter aktiv
- [ ] Alle Marktplatz-Plattformen vollständig getestet
- [ ] Vollständige Testabdeckung kritischer Pfade

---

## 🎯 Release-Kriterien v1.0

| Kriterium | Status |
|---|---|
| Frische Installation < 10 Min | 🔲 Offen |
| `piclaw doctor` alles grün | 🔲 Offen |
| Security-Audit bestanden | ✅ v0.16.0 |
| marketplace_monitor stabil | ✅ v0.15.5 |
| `/api/shell` entfernt | ✅ v0.15.3 |
| Alle kritischen Bugs behoben | ✅ v0.16.0 |
| SECURITY.md vollständig | ✅ v0.16.0 |
| LLM Health Monitor aktiv | ✅ v0.15.4 |

---

## 🔧 Technical Debt

| # | Problem | Priorität | Version |
|---|---|---|---|
| TD-01 | /api/shell entfernt | ✅ Erledigt | v0.15.3 |
| TD-02 | Zeitzone-Autosetup im Wizard | 🟡 Mittel | → v0.17 |
| TD-03 | Daemon-Neustart bei neuem Sub-Agent | 🟡 Mittel | → v0.18 |
| TD-04 | Query-Extraktion nimmt Ortsnamen auf | 🟡 Mittel | → v0.19 |
| TD-05 | HA doctor Timing (5s Timeout) | 🟢 Klein | → v0.17 |
