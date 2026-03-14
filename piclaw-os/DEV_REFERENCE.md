# PiClaw OS – Entwicklungsreferenz für Claude
# Erstellt: März 2026 | Version: 0.13.3

## PROJEKTÜBERSICHT

PiClaw OS ist ein KI-Betriebssystem für Raspberry Pi 5 (arm64).
Agent-Name: PiClaw (konfigurierbar via piclaw setup)
Code: /home/claude/piclaw-os/ | Outputs: /mnt/user-data/outputs/

## DATEISTRUKTUR

```
piclaw-os/
├── pyproject.toml          # build-backend = "setuptools.build_meta" (WICHTIG)
├── CHANGELOG.md
├── ROADMAP.md
├── SOUL.md                 # Dameon Soul-Datei
├── boot/piclaw/
│   ├── install.sh          # Installer (PICLAW_VERSION="0.13.3")
│   ├── piclaw.conf         # Konfigurationsvorlage
│   ├── README.txt
│   └── piclaw-src/         # Wird nach /opt/piclaw/ kopiert
│       ├── pyproject.toml  # Muss synchron zu root pyproject.toml sein
│       └── piclaw/         # Paket-Quellcode (KEIN piclaw/piclaw/ Unterordner!)
└── piclaw/                 # Python-Paket
    ├── __init__.py         # __version__ = '0.13.3'
    ├── agent.py            # Haupt-Agent
    ├── api.py              # FastAPI REST + WebSocket
    ├── auth.py             # Token-Auth (require_auth, require_auth_ws)
    ├── cli.py              # CLI-Tool (piclaw Befehl)
    ├── config.py           # Konfiguration (_resolve_config_dir!)
    ├── daemon.py           # Systemd-Daemon
    ├── wizard.py           # SSH-Wizard (11 Schritte)
    ├── agents/
    │   ├── crawler.py      # Web-Crawler Sub-Agent
    │   ├── ipc.py          # SQLite IPC (jobs.db, watchdog.db)
    │   ├── orchestration.py
    │   ├── runner.py
    │   ├── sa_registry.py
    │   ├── sa_tools.py
    │   ├── sandbox.py
    │   └── watchdog.py     # Hardware-Watchdog (User: piclaw-watchdog)
    ├── hardware/
    │   ├── camera.py
    │   ├── i2c_scan.py
    │   ├── pi_info.py
    │   ├── sensors.py
    │   ├── thermal.py      # Thermisches LLM-Routing
    │   └── tools.py
    ├── llm/
    │   ├── __init__.py     # create_backend()
    │   ├── api.py          # AnthropicBackend, OpenAIBackend
    │   ├── anthropic.py
    │   ├── base.py         # LLMBackend, Message, ToolDefinition
    │   ├── classifier.py   # Task-Klassifikation
    │   ├── local.py        # LocalBackend (Gemma/Phi3/TinyLlama via llama.cpp)
    │   ├── mgmt_tools.py
    │   ├── model_manager.py # Download-Manager
    │   ├── multirouter.py  # MultiLLMRouter (Haupt-Router)
    │   ├── registry.py     # LLMRegistry
    │   └── router.py
    ├── memory/
    │   ├── middleware.py   # Memory-Injection in Prompts
    │   ├── qmd.py          # QMD BM25+Vektor Suche (SEARCH_TIMEOUT=6s!)
    │   ├── store.py
    │   └── tools.py
    ├── messaging/
    │   ├── discord.py
    │   ├── hub.py          # MessagingHub
    │   ├── mqtt.py
    │   ├── telegram.py
    │   ├── threema.py
    │   └── whatsapp.py
    ├── tools/
    │   ├── gpio.py
    │   ├── homeassistant.py # 11 HA-Tools
    │   ├── http.py
    │   ├── marketplace.py  # NEU: Kleinanzeigen/eBay/Web Crawler
    │   ├── network.py
    │   ├── scheduler.py
    │   ├── services.py
    │   ├── shell.py
    │   └── updater.py
    └── web/
        └── index.html      # Web-Dashboard (8 Tabs)
```

## KRITISCHE FIXES (nie rückgängig machen)

### 1. pyproject.toml
build-backend = "setuptools.build_meta"  # NICHT "setuptools.backends.legacy:build"

### 2. config.py – CONFIG_DIR
def _resolve_config_dir() -> Path:
    # Liest /etc/piclaw wenn config.toml dort existiert
    # Verhindert dass non-root User ~/.piclaw liest statt /etc/piclaw
    if Path("/etc/piclaw/config.toml").exists():
        return Path("/etc/piclaw")
    ...

### 3. agent.py – callable|None
on_token=None,  # Python 3.13: callable|None ist kein gültiger Type-Hint

### 4. agent.py – memory.enrich Timeout
messages = await asyncio.wait_for(self.memory.enrich(messages), timeout=8.0)
# Verhindert dass QMD-Timeout den Agent blockiert

### 5. agent.py – agent.boot() in cmd_chat
await agent.boot()  # Muss aufgerufen werden bevor agent.run() geht

### 6. api.py – require_auth
Depends(require_auth)  # NICHT Depends(verify_token) - verify_token existiert nicht

### 7. api.py – __main__ Block
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("piclaw.api:app", ...)
# Ohne dies: python -m piclaw.api beendet sich sofort

### 8. cli.py – WebSocket-Chat
# Prüft ob API läuft → verbindet per WebSocket → kein Modell-Reload
# Fallback: direkter Agent-Start mit "(Offline-Modus)" Hinweis

### 9. llm/local.py
DEFAULT_MODEL_PATH = Path("/etc/piclaw/models/gemma-2b-q4.gguf")  # .gguf nicht .ggu!
MODEL_URL = "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/..."  # bartowski Mirror

### 10. llm/multirouter.py
from pathlib import Path  # Muss importiert sein!

async def health_check(self) -> bool:
    if self.global_cfg and self.global_cfg.llm.backend == "local":
        return self._local.model_path.exists()  # Dateiexistenz, nicht ob geladen!

# Bei leerer Registry → lokaler Fallback statt RuntimeError

### 11. llm/registry.py
if not llm.api_key and llm.backend not in ("local", "ollama"):
    return False  # Lokales Backend ohne API-Key trotzdem registrieren

### 12. memory/qmd.py
SEARCH_TIMEOUT = 6  # war 30 – muss unter 8s Agent-Timeout liegen

### 13. wizard.py
def _flush_stdin():
    termios.tcflush(sys.stdin, termios.TCIFLUSH)
# Vor jeder Eingabe aufrufen – verhindert Überspringen durch stdin-Puffer

## LLM-ARCHITEKTUR

### MultiLLMRouter
- Verwaltet Registry (mehrere API-Backends)
- Klassifiziert Tasks und wählt bestes Backend
- Thermisches Routing: COOL→WARM→HOT→CRITICAL→EMERGENCY
- Lokales Modell als Fallback wenn alle APIs scheitern
- boot() muss aufgerufen werden vor chat()

### Lokale Modelle (llama.cpp)
- Gemma 2B: Prompt-Format <start_of_turn>user\n...<end_of_turn>
- Phi-3:    Prompt-Format <|system|>\n...<|end|>
- TinyLlama: ChatML Format
- _detect_format() erkennt Format anhand Dateiname

### Nach model download
- config.toml wird automatisch aktualisiert (llm.model = Pfad)
- Kein manuelles Editieren nötig

## DIENSTE & RECHTE

### Benutzer
- piclaw: Haupt-User für api, agent, crawler
- piclaw-watchdog: Isolierter User für watchdog

### Kritische Verzeichnis-Rechte
/etc/piclaw/ipc/           chmod 1777 (sticky, alle schreiben)
/etc/piclaw/ipc/watchdog.db  chown piclaw-watchdog:piclaw-watchdog
/etc/piclaw/ipc/jobs.db      chown piclaw:piclaw
/etc/piclaw/models/          chown -R piclaw:piclaw
/etc/piclaw/logs/watchdog/   chown -R piclaw-watchdog:piclaw-watchdog

### Systemd Services
/etc/systemd/system/piclaw-api.service
/etc/systemd/system/piclaw-agent.service
/etc/systemd/system/piclaw-watchdog.service
/etc/systemd/system/piclaw-crawler.service

## BUILD-PROZESS

### WICHTIG: Sync ohne Doppelstruktur
```python
import shutil
from pathlib import Path
target = Path("boot/piclaw/piclaw-src/piclaw")
shutil.rmtree(target)
shutil.copytree("piclaw", str(target))
# NIEMALS: cp -r piclaw/ target/ → erstellt target/piclaw/piclaw/!
```

### ZIP-Build
```bash
zip -r piclaw-sdcard.zip piclaw/ \
  --exclude "piclaw/piclaw-src/*/__pycache__/*" \
  --exclude "piclaw/piclaw-src/piclaw/piclaw/*"  # Doppelstruktur ausschließen
```

### Verifikation vor jedem Release
```python
# Keine Doppelstruktur
assert not Path("boot/piclaw/piclaw-src/piclaw/piclaw").exists()
# Alle kritischen Fixes vorhanden
assert "setuptools.build_meta" in Path("pyproject.toml").read_text()
assert "_resolve_config_dir" in Path("piclaw/config.py").read_text()
assert "require_auth" in Path("piclaw/api.py").read_text()
assert "__main__" in Path("piclaw/api.py").read_text()
assert "gemma-2b-q4.gguf" in Path("piclaw/llm/local.py").read_text()
assert "SEARCH_TIMEOUT  = 6" in Path("piclaw/memory/qmd.py").read_text()
```

## TOOL-REGISTRIERUNG

Neue Tools in agent.py._build_tools() registrieren:
```python
from piclaw.tools.newtool import TOOL_DEFS, HANDLERS
_reg(TOOL_DEFS, HANDLERS)
```

Tool-Definition:
```python
ToolDefinition(name="...", description="...", parameters={"type":"object","properties":{...},"required":[...]})
```

## MARKETPLACE-CRAWLER

Datei: piclaw/tools/marketplace.py
- marketplace_search(query, platforms, max_price, location, max_results)
- Seen-IDs in /etc/piclaw/marketplace_seen.json
- Plattformen: kleinanzeigen, ebay, web
- format_results() → Telegram-formatierter Text

## WEB-DASHBOARD

Datei: piclaw/web/index.html
- Polling-Intervalle: stats=15s, services=60s, mode=30s, memory=60s, subagents=45s
- Tab-Pause: document.visibilitychange → stopPolling() / startPolling()
- WebSocket: /ws/chat?token=...

## ROADMAP (nächste Features)

v0.14: Queue-System (parallel CLI + Telegram), llama.cpp stdout unterdrücken
v0.15: Netzwerk-Monitoring (nmap, neue Geräte, Port-Scan)
v0.16: Notfall-Shutdown (schaltbare Steckdose am Modem, Shelly/Tapo)
v0.17: Security Tools (nmap, fail2ban, IP-Blocking, Abuse-Reports)
v0.18: LLM-Verbesserungen (Ollama optimieren, Antwortzeit)

## AKTUELLE KONFIGURATION (Pi)

[llm]
backend = "api"
provider = "openai"
model = "moonshotai/kimi-k2-instruct-0905"
base_url = "https://integrate.api.nvidia.com/v1"
temperature = 0.6

Lokales Fallback-Modell: /etc/piclaw/models/gemma-2b-q4.gguf

## TESTING

Nach jeder Änderung:
1. python3 -c "import ast; ast.parse(open('piclaw/DATEI.py').read())" 
2. Alle 65 Dateien: python3 -m py_compile
3. Sync + ZIP-Bau (shutil.copytree, kein cp -r!)
4. ZIP-Verifikation (keine Doppelstruktur, kritische Fixes vorhanden)
5. Neuinstallation testen
