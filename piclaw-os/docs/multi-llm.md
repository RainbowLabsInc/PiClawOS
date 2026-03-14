# PiClaw OS – Multi-LLM Routing

## Konzept

PiClaw OS kann mehrere LLM-Backends gleichzeitig registrieren und wählt
automatisch das beste für jede Anfrage – basierend auf Fähigkeits-Tags und Priorität.

```
Eingehende Nachricht
  → Stage 1: Regex-Classifier (25 Muster, sofort, kein LLM)
  → confidence < 65%? Stage 2: Schnellstes LLM klassifiziert
  → LLMRegistry.find_by_tags() → sortiert nach (Überschneidung DESC, Priorität DESC)
  → degradierte Backends gefiltert (>3 Fehler → 120s Cooldown)
  → bestes Backend → bei Fehler: nächstes → finaler Fallback: lokal Phi-3
```

## Backends registrieren

```bash
# Über CLI
piclaw config set llm.registry.claude-sonnet '{
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "tags": ["coding", "reasoning", "german", "analysis"],
  "priority": 9,
  "api_key": "sk-ant-..."
}'

piclaw config set llm.registry.gpt4o '{
  "provider": "openai",
  "model": "gpt-4o",
  "tags": ["creative", "writing", "english"],
  "priority": 7
}'

# Oder via Chat:
"Registriere Claude Sonnet als primäres Backend für Coding-Aufgaben"
```

## Classifier-Tags

| Kategorie | Tags |
|-----------|------|
| Aufgabe | `coding`, `debugging`, `analysis`, `reasoning`, `creative`, `writing`, `summarization`, `translation`, `math`, `research`, `general` |
| Sprache | `german`, `english`, `french`, `spanish` |
| Stil | `fast`, `detailed`, `concise` |
| Technik | `technical` |

## Backend manuell wählen

Mit dem `@`-Präfix in einer Nachricht:

```
@claude-sonnet Erkläre mir Rust Lifetimes
@local Was ist die CPU-Temperatur?
@gpt4o Write a poem about the sea
```

## Status ansehen

```bash
piclaw model status              # alle Backends + Health
```

Web-UI: Dashboard → Mode-Badge (oben rechts) zeigt aktives Backend.

## Lokales Fallback

Wenn alle Cloud-APIs nicht erreichbar sind, fällt PiClaw automatisch auf
Phi-3 Mini (Q4, ~2.3 GB) zurück das lokal auf dem Pi läuft.

```bash
piclaw model download            # Phi-3 herunterladen
```

## Cooldown-Mechanismus

| Zustand | Verhalten |
|---------|-----------|
| < 3 Fehler | Normal verfügbar |
| ≥ 3 Fehler | 120s Cooldown, nächstes Backend |
| Nach Cooldown | Automatisch wieder probiert |
