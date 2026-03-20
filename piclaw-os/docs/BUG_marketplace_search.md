# BUG: Marketplace Search returns "Keine neuen Inserate" despite results existing

**Status:** Open  
**Priority:** High  
**Date:** 2026-03-20  

---

## Symptom

```
[you] Suche Raspberry Pi 5 auf Kleinanzeigen.de im Umkreis von 30km um 21224
[Dameon] Keine neuen Inserate gefunden für 'Raspberry Pi 5 21224'.
```

The query in the error message contains `'Raspberry Pi 5 21224'` — the PLZ is still in the query string. This is a key clue.

---

## What we know

### 1. The tool itself works perfectly
Direct test on Pi returns 5 results:
```python
await marketplace_search(
    query="Raspberry Pi 5",
    platforms=["kleinanzeigen"],
    location="21224",
    radius_km=20,
    notify_all=True,
)
# → Total: 5, Neu: 5 ✅
```

### 2. `_detect_marketplace_intent` works correctly
Direct test on Pi:
```python
a._detect_marketplace_intent(
    "Suche einen Raspberry Pi 5 im Umkreis von 30km um 21224 Rosengarten auf Kleinanzeigen.de"
)
# → {'query': 'Raspberry Pi 5', 'platforms': ['kleinanzeigen'], 'location': '21224', 'radius_km': 30} ✅
```

### 3. The shortcut code IS in RAM
```python
inspect.getsource(Agent._run_internal)
# → "✅ Shortcut ist in _run_internal"
```

### 4. Log never shows "Marketplace intent detected"
The shortcut has `log.info("Marketplace intent detected, calling tool directly: %s", mp_kwargs)` — this line NEVER appears in `/var/log/piclaw/agent.log`.

### 5. The query in the error contains the PLZ
`'Raspberry Pi 5 21224'` — our shortcut produces `query='Raspberry Pi 5'` (PLZ-free). This means Kimi K2 is calling marketplace_search with a different/dirty query.

---

## Root cause hypothesis

The shortcut in `_run_internal` is likely throwing a silent exception and falling back to the LLM flow. The except block:

```python
except Exception as e:
    log.warning("Marketplace shortcut failed: %s — falling back to LLM", e)
```

The warning may not be visible because the log level filter doesn't show it, OR Kimi K2 is calling marketplace_search itself with query='Raspberry Pi 5 21224'.

---

## Next debugging steps

### Step 1: Check if shortcut exception fires
```bash
sudo grep -i "shortcut\|marketplace shortcut" /var/log/piclaw/agent.log
```

### Step 2: Add debug logging to shortcut
In `agent.py` `_run_internal`, change:
```python
except Exception as e:
    log.warning("Marketplace shortcut failed: %s — falling back to LLM", e)
```
to:
```python
except Exception as e:
    import traceback
    log.error("Marketplace shortcut FAILED: %s\n%s", e, traceback.format_exc())
```

### Step 3: Check if Kimi K2 calls tool directly
The query `'Raspberry Pi 5 21224'` suggests Kimi K2 is calling marketplace_search itself. Add logging at the top of the marketplace_search function:
```python
log.info("marketplace_search called with query=%r location=%r radius=%r", query, location, radius_km)
```

### Step 4: Verify seen_ids not recreated
```bash
watch -n 2 "ls -la /etc/piclaw/marketplace_seen.json 2>/dev/null || echo 'not found'"
```

---

## Files involved

- `piclaw-os/piclaw/agent.py` — `_detect_marketplace_intent()`, `_run_internal()` shortcut
- `piclaw-os/piclaw/tools/marketplace.py` — `marketplace_search()`, `format_results()`

---

## Architecture note

The CLI connects via WebSocket to `piclaw-api` (port 7842).  
`piclaw-api` has its own `Agent` instance (`_agent` in `api.py` line 40).  
Requests go: CLI → WebSocket → api.py `_agent.run()` → `_run_internal()` → shortcut.  
The `piclaw-agent` daemon is a separate process used for background tasks.  
**Logging goes to `/var/log/piclaw/agent.log` via piclaw-agent, NOT via the API agent.**  
This means the shortcut may be running in the API process but logging nowhere visible!

### Fix for logging:
The API agent logs to its own logger but the file handler may only be set up for the daemon.  
Check: `sudo tail -f /var/log/piclaw/api.log` during a search — does marketplace appear there?
