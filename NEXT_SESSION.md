# PiClaw OS – Offene Punkte für nächste Session
# Erstellt: 2026-03-28

---

## 🔧 Bekannte Bugs

### 1. `piclaw update` hängt gelegentlich
- Symptom: Update dauert sehr lange, bricht manchmal ab
- Verdacht: `git pull` Timeout oder git-Rechte Problem
- Prüfen: `git pull` manuell in `/opt/piclaw` ausführen und Fehler anschauen

### 2. Halluzinationen bei Tool Calling (Llama 3.3 70B / NIM)
- Symptom: Dameon beschreibt was er tun würde statt das Tool aufzurufen
  Beispiel: "Suche Laptop in Graz auf willhaben.at" → erfundene Ergebnisse
- Ursache: NIM Tool-Calling Format-Problem (bekannt seit Kimi K2)
- Fix-Ansatz: `tool_choice` in API-Payload oder System-Prompt Instruktion
- Siehe CLAUDE_REBUILD.md: TOOL_SYSTEM → KNOWN_ISSUE

### 3. Groq als primäres Backend noch nicht getestet
- Priorität wurde auf 9 gesetzt (höher als NIM mit 7)
- Hot-Reload Fix wurde implementiert (7d82bbf) aber noch nicht live getestet
- Test: nach `piclaw update` → `piclaw` → "Bist du da?" → Log prüfen ob Groq antwortet

---

## ✅ Fertig aber noch nicht getestet

### Cron-Job Sub-Agent
- `cron:<expr>` Schedule ist implementiert (croniter installiert)
- Noch kein aktiver Cron-Agent vorhanden
- Test: "Erstelle einen Agenten der jeden Tag um 8 Uhr die Temperatur meldet"

### Netzwerk-Monitoring Sub-Agent
- Implementiert: `_detect_network_monitor_intent()` + `_create_network_monitor_agent()`
- nmap muss installiert sein: `sudo apt install nmap -y`
- Test: "Überwache mein Netzwerk auf neue Geräte"

### LLM Hot-Reload
- Registry lädt sich neu wenn `llm_registry.json` sich ändert
- Test: `piclaw llm update groq-fallback --priority 9` → sofort ohne Neustart aktiv?

---

## 📋 Nächste Features (Roadmap)

1. **CLAUDE_REBUILD.md aktualisieren** auf v0.15.2 Stand
2. **fail2ban Integration** (IP-Blocking bei Brute-Force)
3. **Emergency Shutdown** ohne Home Assistant (direkt via schaltbare Steckdose)
4. **Tool-Calling Fix** für NIM/Groq – `tool_choice: required` testen
5. **Queue System v0.14** – parallele CLI + Telegram Anfragen
6. **Willhaben Umkreis-Suche** – PLZ → Bundesland-Mapping für areaId

---

## 🔑 Wichtige Infos

- Pi IP: 192.168.178.120
- Primäres LLM: NVIDIA NIM / meta/llama-3.3-70b-instruct (Prio 7)
- Fallback LLM: Groq / llama-3.3-70b-versatile (Prio 9 – soll primary werden)
- Lokales Fallback: Ollama / qwen2.5:1.5b (nur wenn explizit konfiguriert)
- Letzter erfolgreicher `piclaw doctor`: alle grün, CPU 49-51°C
