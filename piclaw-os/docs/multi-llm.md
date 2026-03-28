# PiClaw OS – Multi-LLM Routing

## Konzept

PiClaw OS kann mehrere LLM-Backends gleichzeitig registrieren und wählt
automatisch das beste für jede Anfrage – basierend auf Fähigkeits-Tags und Priorität.

```
Eingehende Nachricht
  → Stage 0: _regex_classify() – HA-Befehle in <1ms (kein LLM!)
  → Stage 1: Pattern-Matching (25 Muster, sofort)
  → confidence < 65%? Stage 2: Schnellstes LLM klassifiziert (8s Timeout)
  → LLMRegistry.find_by_tags() → sortiert nach (Überschneidung DESC, Priorität DESC)
  → degradierte Backends gefiltert (>3 Fehler → Cooldown)
  → bestes Backend → bei Fehler: nächstes → finaler Fallback: lokal Gemma-2B
```

## Aktuelle Backends (v0.15.4)

| Priority | Name | Modell | Provider | Tags |
|---|---|---|---|---|
| 10 | groq-actions | llama-3.3-70b-versatile | Groq | action, home_automation, query, german |
| 9 | groq-fallback | kimi-k2-instruct | Groq | general, reasoning, analysis, coding |
| 8 | nemotron-nvidia | llama-4-maverick-17b | NVIDIA NIM | general, reasoning, fast |
| 7 | openai-default | llama-3.3-70b-instruct | NVIDIA NIM | general (Fallback) |
| – | lokal | gemma-2b-q4 | llama.cpp | letzter Fallback |

## Backends verwalten

```bash
piclaw llm list                          # Alle Backends anzeigen
piclaw llm add --name cerebras \         # Neues Backend hinzufügen
  --provider openai \
  --model llama-3.3-70b \
  --api-key csk-... \
  --base-url https://api.cerebras.ai/v1 \
  --priority 9 \
  --tags general,fast,german
piclaw llm update groq-fallback --priority 8   # Priorität ändern
piclaw llm disable nemotron-nvidia             # Deaktivieren
piclaw llm test groq-actions                   # Backend testen
```

## Classifier-Tags (vollständig)

```
coding, debugging, analysis, reasoning, creative, writing,
summarization, translation, math, research, technical,
general, german, english, french, spanish,
action, home_automation, query
```

**Neu in v0.15.4:**
- `action` – direkte Gerätebefehle (Licht, Steckdose, Rolladen)
- `home_automation` – Home Assistant Anfragen
- `query` – Statusabfragen ohne Aktion

## Regex-Classifier (Stage 0)

Erkennt HA-Befehle **ohne LLM-Aufruf** in < 1ms:

```python
# HA-Aktionen → tags=[action, home_automation, german], confidence=0.95
"Schalte das Licht im Fernsehzimmer aus"
"Mach die Küche an"
"Rolladen hoch"

# HA-Abfragen → tags=[query, home_automation, german], confidence=0.90
"Wie warm ist es im Schlafzimmer?"
"Ist der Fernseher an?"
```

## LLM Health Monitor

Stündlicher Background-Check aller Backends. Automatische Selbstheilung:

| Fehler | Reaktion |
|---|---|
| 404 (Modell entfernt) | Provider /models API → Preferred-Liste → auto-update |
| 429 (Rate-Limit) | Priorität -5 für 1h, danach wiederherstellen |
| 500/Timeout (3×) | Deaktivieren + Telegram-Notify |

**Preferred-Liste je Provider** (in `health_monitor.py`):
- Groq: llama-3.3-70b-versatile → llama-3.3-70b-specdec → llama-3.1-70b-versatile
- NVIDIA NIM: llama-4-maverick → llama-4-scout → llama-3.3-70b → llama-3.1-70b

**Telegram-Benachrichtigung bei Auto-Repair:**
```
🔧 LLM Health Monitor – Auto-Repair
✅ nemotron-nvidia: Modell ersetzt → meta/llama-4-maverick-17b-128e-instruct
```

## HA-Shortcut (kein LLM)

Für einfache Schalt-Befehle braucht PiClaw **keinen LLM**:

```
Vorher: Telegram → LLM (10k Token, 2-30s) → ha_turn_on → Antwort
Nachher: Telegram → Intent-Erkenner → ha_turn_on direkt → "💡 Licht an" (<100ms)
```

Erkannte Muster: `schalte/mach/licht/lampe/steckdose + Raum + an/aus/ein/off`

Bei fehlendem Match übernimmt der LLM (routed über groq-actions).

## Routing-Beispiele

```
"Licht Fernsehzimmer an"     → HA-Shortcut (0 Token, 0ms)
"Dimme Küche auf 50%"        → groq-actions (Llama 3.3, action-Tag)
"Wie warm ist Schlafzimmer?" → groq-actions (query-Tag)
"Analysiere meinen Code"     → groq-fallback (Kimi K2, reasoning-Tag)
"Schreibe einen Brief"       → groq-fallback (Kimi K2, writing-Tag)
```
