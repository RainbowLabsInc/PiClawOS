# PiClaw OS – Offene Punkte für nächste Session
# Erstellt: 2026-03-28
# Letztes Update: 2026-03-28 (Session 2 – alle Tests grün)

---

## ✅ Alles getestet und funktioniert

- Groq (Kimi K2 via Groq) als Primary-LLM ✅
- Tool-Calls (Temperatur, Shell) ✅
- Willhaben Standortfilter Graz (areaId=601) ✅
- Kleinanzeigen Stadtname-Erkennung (Hamburg) ✅
- Netzwerk-Monitor Sub-Agent ✅
- Cron-Agent (täglich um 06:45 Uhr) ✅

---

## 🔧 Aktive Sub-Agenten auf dem Pi

- `Monitor_Netzwerk` – Netzwerk-Scan alle 5 Min
- `CPU_Temperatur_Melder` – täglich 06:45 Uhr (cron:45 6 * * *)
- (3 weitere aus früheren Sessions)

---

## 📋 Roadmap (nächste Features)

1. **fail2ban Integration** (v0.17)
   Brute-Force Schutz für SSH und API

2. **Emergency Shutdown** via schaltbare Steckdose (v0.16)
   Direktes Abschalten ohne Home Assistant

3. **Queue System v0.14** – parallele CLI + Telegram Anfragen
   Momentan: eine Anfrage zu Zeit

4. **Willhaben Kategorie-Filter**
   "Notebooks" findet auch Taschen + RAM → category_id Parameter
   Browser-Inspektion: areaId=601 funktioniert ✅, Kategorie noch offen

5. **Camera-Tools registrieren**
   piclaw/hardware/camera.py hat TOOL_DEFS aber fehlt in _build_tools()
   Fix: _reg(camera_mod.TOOL_DEFS, camera_mod.build_handlers()) in agent.py

6. **LLM Hot-Reload testen**
   `piclaw llm update <n> --priority X` → sofort ohne Neustart aktiv?

---

## 🔑 Wichtige Infos

- Pi IP: 192.168.178.120
- Primäres LLM: Groq / moonshotai/kimi-k2-instruct (Prio 9)
- Sekundär: NVIDIA NIM / meta/llama-3.3-70b-instruct (Prio 7)
- Nemotron: nvidia/llama-3.1-nemotron-70b-instruct (Prio 6, oft 404)
- Lokales Fallback: Gemma 2B Q4 (automatisch)
- Letzter erfolgreicher piclaw doctor: alle grün, CPU ~52°C
- Groq-Modelle verfügbar: llama-3.3-70b-versatile, moonshotai/kimi-k2-instruct,
  qwen/qwen3-32b, openai/gpt-oss-120b (kein Tool-Calling), meta-llama/llama-4-scout-17b
- github_token in /etc/piclaw/config.toml für piclaw update eintragen!

## ⚠️  Vor Repo-Veröffentlichung

- Groq API Key aus Git-History entfernen (wurde im Chat geteilt)
  → git filter-branch oder BFG Repo Cleaner
- NEXT_SESSION.md auf keine Keys prüfen
