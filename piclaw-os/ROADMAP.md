# PiClaw OS — Roadmap

## Status: v0.15.4 (April 2026)

Dameon läuft stabil auf Raspberry Pi 5.
Home Assistant vollständig integriert (11 Tools, Fuzzy-Suche, Shortcut ohne LLM).
Smart LLM Routing: action → groq-actions (Llama 3.3), general → Kimi K2.
LLM Health Monitor: automatische Selbstheilung + Cross-Prozess-Status via Datei.
Sub-Agenten Monitor_Netzwerk + Monitor_Gartentisch: tokenlos via direct_tool.
Kleinanzeigen Radius-Suche: korrekte Location-ID URL (k0l{ID}r{km}).

---

## ✅ Abgeschlossen

### v0.15.4 — Home Assistant + Smart Routing + Selbstheilung + Token-Optimierung (März–April 2026)
- [x] Home Assistant Integration (11 Tools, piclaw setup HA-Wizard)
- [x] HA-Shortcut: Licht/Schalter ohne LLM (~0ms, 0 Token)
- [x] Smart LLM Routing: action/home_automation → groq-actions (Llama 3.3, 30k TPM)
- [x] Regex-Classifier Stage 0: HA-Befehle in <1ms klassifiziert
- [x] LLM Health Monitor: automatische Selbstheilung (404→Replacement, 429→Deprio)
- [x] LLM Health Monitor: Cross-Prozess Status via /etc/piclaw/llm_health_status.json
- [x] Monitor_Netzwerk: Dreifach-Schutzarchitektur + direct_tool (0 LLM-Calls)
- [x] Monitor_Gartentisch: direct_tool=_mp_monitor_gartentisch (0 LLM-Calls/Stunde)
- [x] Routinen: direct_check Action-Typ (cpu_temp, disk, ram, new_devices, ha_state)
- [x] Kleinanzeigen Radius-Suche: Location-ID URL-Format k0l{ID}r{km} (statt ?radius=N)
- [x] PATCH /api/subagents/{name}: Live-Update ohne Delete+Recreate
- [x] POST /api/subagents/mp-restore: Handler ohne Daemon-Neustart registrieren
- [x] metrics.py: CONFIG_DIR statt cfg.config_dir (AttributeError behoben)
- [x] nemotron-nvidia gefixt: Llama 4 Maverick als Replacement
- [x] 10+ kritische Bugfixes

### v0.15.3 — Stabilisierung Sub-Agenten (März 2026)
- [x] Telegram: parse_mode Fallback, MarkdownV1-Fix
- [x] Direct Tool Mode: Monitor_Netzwerk ohne LLM (0 API-Calls/Tag)
- [x] ClawHub Integration
- [x] Monitor_Gartentisch: Kleinanzeigen stündlich

### v0.15.2 — Release Candidate Basis (März 2026)
- [x] Groq / Kimi K2 als Primary-LLM
- [x] Network Security Tools
- [x] IPC Zwei-Prozess-Architektur
- [x] piclaw doctor erweitert

---

## 🚧 Vor Release (Pflicht)

- [x] `/api/shell` Endpoint entfernen (DEV-ONLY!)
- [ ] Groq API Key aus Git-History tilgen
- [ ] API-Token rotieren
- [ ] Sub-Agent via API → Daemon-Neustart vermeiden (IPC-Reload)
- [ ] Neuinstallationstest auf frischem Pi

---

## 📋 Geplant

### v0.16 — LLM Autonomie & Selbstverbesserung 🧠 ← NEU VOR RELEASE
- [ ] Dameon recherchiert neue LLM-Backends selbst bei hoher Last
- [ ] Bewertet Modelle (Latenz, TPM, Tool-Call-Support)
- [ ] Schlägt neue Backends vor → Nutzer bestätigt → auto-install
- [ ] Cerebras als weiterer Provider (Llama 3.3, 60+ Token/s)

### v0.17 — Emergency Shutdown
- [ ] Schaltbare Steckdose am Modem via HA
- [ ] emergency_network_off() mit Telegram-Bestätigung

### v0.18 — Queue System + IPC-Reload
- [ ] Registry-Reload via IPC (kein Neustart bei neuem Sub-Agent)

### v0.19 — Marketplace Erweiterungen
- [ ] Willhaben Kategorie-Filter
- [ ] Marketplace-Links garantiert (direct_tool)

### v0.20 — Kamera-Tools
- [ ] ESP32-CAM / ESPHome vollständig

### v0.21 — Self-Improving Memory
- [ ] Tiered Memory: HOT / WARM / COLD

---

## 🎯 Release-Kriterien v1.0

- [ ] Frische Installation unter 10 Minuten
- [ ] piclaw doctor alles grün (inkl. HA)
- [ ] Mind. 2 Cloud-LLM-Anbieter aktiv
- [ ] LLM Health Monitor läuft
- [x] /api/shell entfernt
- [ ] Alle kritischen Tests grün

---

## 🔧 Technical Debt

| # | Problem | Priorität |
|---|---------|-----------|
| TD-01 | /api/shell vor Release entfernen | ✅ Erledigt |
| TD-02 | Groq Key aus Git-History tilgen | 🔴 Kritisch |
| TD-03 | API-Token rotieren | 🔴 Kritisch |
| TD-04 | Daemon-Neustart bei neuem Sub-Agent | 🟡 Mittel |
| TD-05 | Marketplace-Links (LLM kürzt URLs) | ✅ Erledigt via direct_tool |
| TD-06 | Daemon-Neustart nach API-basierten Monitor-Agenten | 🟡 Mittel (IPC-Reload in v0.18) |
| TD-07 | API-Token aus Session in Browser-Console sichtbar | 🔴 Kritisch (rotieren!) |
