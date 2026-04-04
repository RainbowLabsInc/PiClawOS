# PiClaw OS — Roadmap

## Status: v0.15.5 (April 2026)

Dameon läuft stabil auf Raspberry Pi 5.
- 5 Sub-Agenten aktiv (3x marketplace_monitor, Netzwerk, CronJob)
- marketplace_monitor Refactor: neustart-sicher via JSON-Params in mission
- Qwen3-1.7B als lokales Offline-Fallback-Modell (Agent Score 0.96)
- LLM Routing: groq-actions (10) → groq-fallback (9) → groq-gptoss (8) → nvidia (6)
- Kleinanzeigen Radius-Suche: korrekte Location-ID URL

---

## ✅ Abgeschlossen

### v0.15.5 — marketplace_monitor Refactor + Stabilisierung (April 2026)
- [x] marketplace_monitor: Parameter als JSON in mission – neustart-sicher
- [x] Qwen3-1.7B Q4_K_M als Offline-Fallback (ersetzt Gemma 2B)
- [x] groq-gptoss (openai/gpt-oss-120b) auf Prio 8 eingetragen
- [x] Monitor_Gartentisch, Monitor_Sonnenschirm, Monitor_Sauer505 aktiv
- [x] Kleinanzeigen Radius-Suche: Location-ID via s-ort-empfehlungen.json API
- [x] PATCH /api/subagents/{name}: Live-Update ohne Delete+Recreate
- [x] LLM Health Monitor: Cross-Prozess Status via JSON-Datei
- [x] metrics.py: CONFIG_DIR Fix (AttributeError)
- [x] AGENTS.md: Architektur-Dokumentation für Sub-Agent-System

### v0.15.4 — Home Assistant + Smart Routing + Selbstheilung (März–April 2026)
- [x] Home Assistant Integration (11 Tools, HA-Wizard, Fuzzy-Suche)
- [x] HA-Shortcut: Licht/Schalter ohne LLM (~0ms, 0 Token)
- [x] Smart LLM Routing: Regex Stage 0 → Pattern Stage 1 → LLM Stage 2
- [x] LLM Health Monitor: automatische Selbstheilung (404→Replacement, 429→Deprio)
- [x] Monitor_Netzwerk: direct_tool, Dreifach-Schutzarchitektur (0 LLM-Calls)
- [x] direct_check Action-Typ für tokenlose Routinen

### v0.15.3 — Stabilisierung Sub-Agenten (März 2026)
- [x] Telegram: parse_mode Fallback, MarkdownV1-Fix
- [x] Direct Tool Mode: Monitor_Netzwerk ohne LLM
- [x] ClawHub Integration
- [x] IPC Zwei-Prozess-Architektur

### v0.15.2 — Release Candidate Basis (März 2026)
- [x] Groq / Kimi K2 als Primary-LLM
- [x] Network Security Tools
- [x] piclaw doctor erweitert

---

## 🚧 Vor Release (Pflicht)

- [x] `/api/shell` Endpoint entfernen
- [ ] Credentials rotieren (API-Token + GitHub PAT nach jeder Dev-Session)
- [ ] Sub-Agent via API → Daemon-Neustart vermeiden (→ v0.18)
- [ ] Query-Extraktion: Ortsnamen nicht in Query aufnehmen
- [ ] Neuinstallationstest auf frischem Pi
- [ ] Home Assistant Verbindung in piclaw doctor prüfen

---

## 📋 Geplant

### v0.16 — LLM Autonomie & Selbstverbesserung 🧠
- [ ] Qwen3-1.7B: lokales Tool Calling vollständig integrieren
- [ ] Dameon recherchiert neue LLM-Backends selbst bei hoher Last
- [ ] Bewertet Modelle (Latenz, TPM, Tool-Call-Support, Kosten)
- [ ] Schlägt neue Backends vor → Nutzer bestätigt → auto-install
- [ ] Cerebras als weiterer Provider (Llama 3.3, 60+ Token/s, kostenlos)

### v0.17 — Emergency Shutdown
- [ ] Schaltbare Steckdose am Modem via HA
- [ ] emergency_network_off() mit Telegram-Bestätigung

### v0.18 — Queue System + IPC-Reload
- [ ] Registry-Reload via IPC (kein Daemon-Neustart bei neuem Sub-Agent)
- [ ] Queue für parallele Sub-Agent-Ausführung

### v0.19 — Marketplace Erweiterungen
- [ ] Willhaben Kategorie-Filter
- [ ] Troostwijk vollständig getestet
- [ ] Query-Extraktion: Ortsnamen sauber aus Query entfernen

### v0.20 — Kamera-Tools
- [ ] ESP32-CAM / ESPHome vollständig

### v0.21 — Self-Improving Memory
- [ ] Tiered Memory: HOT / WARM / COLD

### v0.22 — Opus 4.6 Integration (optional)
- [ ] Schweres Geschütz für interne Optimierungen / ClawHub
- [ ] ~$1-5/Monat bei sporadischer Nutzung

---

## 🎯 Release-Kriterien v1.0

- [ ] Frische Installation unter 10 Minuten
- [ ] piclaw doctor alles grün (inkl. HA)
- [ ] Mind. 3 Cloud-LLM-Anbieter aktiv
- [ ] LLM Health Monitor läuft
- [x] /api/shell entfernt
- [ ] marketplace_monitor: alle Plattformen getestet
- [ ] Alle kritischen Tests grün

---

## 🔧 Technical Debt

| # | Problem | Priorität |
|---|---------|-----------|
| TD-01 | /api/shell entfernen | ✅ Erledigt |
| TD-02 | Credentials nach Dev-Session rotieren | 🔴 Kritisch |
| TD-03 | Daemon-Neustart bei neuem Sub-Agent nötig | 🟡 Mittel → v0.18 |
| TD-04 | Query-Extraktion nimmt Ortsnamen auf | 🟡 Mittel → v0.19 |
| TD-05 | Home Assistant doctor zeigt ⬜ nach Neustart | 🟡 Mittel (Timing) |
