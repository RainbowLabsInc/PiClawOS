"""
PiClaw OS – LLM Registry
Stores multiple LLM backend configurations with user-defined capability tags.

Each backend has:
  name        – unique identifier (e.g. "claude-sonnet", "gpt-4o", "local")
  provider    – anthropic | openai | ollama | local
  model       – model string (e.g. "claude-sonnet-4-20250514")
  tags        – user-defined capability labels (e.g. ["coding", "german"])
  priority    – tiebreaker when multiple backends match (higher = preferred)
  api_key     – can be empty if shared from global config
  base_url    – override endpoint
  enabled     – soft-disable without deleting
  max_tokens  – per-backend limit
  temperature – per-backend temperature

Tags are free-form strings. Built-in tag categories (used by the classifier):
  Task tags:   coding, debugging, analysis, reasoning, creative, writing,
               summarization, translation, math, research, general
  Language:    german, english, french, spanish, …
  Style:       fast, detailed, concise, step-by-step
  Domain:      medical, legal, finance, science, …
"""

import json
import logging
from dataclasses import dataclass, field, asdict, fields

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.llm.registry")

REGISTRY_FILE = CONFIG_DIR / "llm_registry.json"


@dataclass
class BackendConfig:
    name: str  # unique identifier
    provider: str  # anthropic | openai | ollama | local
    model: str
    tags: list[str] = field(default_factory=list)
    priority: int = 5  # 1–10, higher = preferred
    api_key: str = ""  # empty = use global config key
    base_url: str = ""  # empty = provider default
    enabled: bool = True
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60
    notes: str = ""  # user-visible description
    # ── Persistierter Health-State ────────────────────────────────────────
    # Diese zwei Felder gehören logisch zum LLMHealthMonitor, müssen aber
    # einen Prozess-Restart überleben. Lagen sie nur im In-Memory-
    # BackendHealth, war ein Backend nach Restart unrettbar: die Sperr-Info
    # war weg, der einzige Re-Enable-Pfad hing daran, und `enabled: False`
    # stand persistiert in der Registry. Ergebnis (25.07.2026): alle fünf
    # statischen Backends dauerhaft aus, nur noch auto-* im Betrieb.
    #
    # original_priority – geparkte Priorität während einer 429-Sperre.
    #                     None = keine Sperre aktiv.
    # max_input_tokens  – vom Provider gemeldetes Input-Budget (aus 413).
    #                     0 = unbekannt/kein bekanntes Limit.
    original_priority: int | None = None
    max_input_tokens: int = 0

    def __post_init__(self):
        """Coerce field types after init/JSON load to prevent TypeError in sort."""
        self.priority = int(self.priority)
        self.max_tokens = int(self.max_tokens)
        self.timeout = int(self.timeout)
        self.temperature = float(self.temperature)
        self.max_input_tokens = int(self.max_input_tokens or 0)
        if self.original_priority is not None:
            self.original_priority = int(self.original_priority)
        self.enabled = bool(self.enabled) if not isinstance(self.enabled, bool) else self.enabled
        if isinstance(self.tags, str):
            self.tags = [t.strip() for t in self.tags.split(",") if t.strip()]

    def has_tag(self, tag: str) -> bool:
        return tag.lower() in [t.lower() for t in self.tags]

    def tag_overlap(self, tags: list[str]) -> int:
        """How many of the given tags does this backend cover?"""
        my_tags = {t.lower() for t in self.tags}
        return sum(1 for t in tags if t.lower() in my_tags)


class LLMRegistry:
    """
    Persistent store for all LLM backend configurations.
    CRUD operations + tag-based lookup.
    """

    def __init__(self):
        self._backends: dict[str, BackendConfig] = {}
        self._file_mtime: float = 0.0
        self._load()

    # ── Persistence ───────────────────────────────────────────────

    def _read_disk(self) -> dict[str, BackendConfig] | None:
        """Liest registry.json. None = Datei fehlt oder ist fehlerhaft.

        Unbekannte Felder werden verworfen statt zu werfen. BackendConfig ist
        ein plain dataclass: ein Feld, das eine neuere Version geschrieben hat,
        ließ `BackendConfig(**v)` mit TypeError scheitern – der Except-Zweig
        schluckte das zu "Registry load error" und der Prozess startete mit
        LEERER Registry, also ohne jedes Cloud-Backend. Bei rollierenden
        Deploys (api und agent starten nicht gleichzeitig neu) ist das ein
        realer Ausfallpfad, kein theoretischer.
        """
        if not REGISTRY_FILE.exists():
            return None
        try:
            data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.error("Registry load error: %s", e)
            return None

        known = {f.name for f in fields(BackendConfig)}
        out: dict[str, BackendConfig] = {}
        for k, v in data.items():
            if not isinstance(v, dict):
                log.warning("Registry: Eintrag '%s' ist kein Objekt – übersprungen", k)
                continue
            unknown = set(v) - known
            if unknown:
                log.warning(
                    "Registry: Backend '%s' hat unbekannte Felder %s – ignoriert "
                    "(neuere PiClaw-Version hat sie geschrieben?)",
                    k, sorted(unknown),
                )
            try:
                out[k] = BackendConfig(**{kk: vv for kk, vv in v.items() if kk in known})
            except Exception as e:
                log.error("Registry: Backend '%s' unlesbar – übersprungen: %s", k, e)
        return out

    def _load(self):
        fresh = self._read_disk()
        if fresh is None:
            self._backends = {}
            return
        self._backends = fresh
        try:
            self._file_mtime = REGISTRY_FILE.stat().st_mtime
        except OSError:
            pass
        log.info("LLM registry loaded: %s backends", len(self._backends))

    def _reload_if_changed(self):
        """Lädt Registry neu wenn die Datei sich geändert hat (Hot-Reload)."""
        if not REGISTRY_FILE.exists():
            return
        try:
            mtime = REGISTRY_FILE.stat().st_mtime
            if mtime != self._file_mtime:
                log.info("LLM registry file changed – reloading")
                self._load()
        except Exception:
            pass

    def _atomic_modify(self, mutate) -> bool:
        """Read-Merge-Write unter File-Lock (Muster: ReminderStore).

        Re-Read unter dem Lock, gezielte Mutation via `mutate(backends)`,
        atomarer Write nur bei truthy-Rückgabe. Beide Prozesse (api↔daemon)
        bootstrappen und mutieren die Registry – der alte Code schrieb den
        In-Memory-Snapshot komplett zurück und konnte so parallele Änderungen
        verlieren. `_file_mtime` wird nach dem Write aktualisiert, damit
        `_reload_if_changed` den eigenen Write nicht sofort erneut lädt.
        Bei fehlerhafter Datei bleibt der In-Memory-Stand erhalten.
        """
        from piclaw.fileutils import safe_write_json, with_file_lock

        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with with_file_lock(REGISTRY_FILE):
                fresh = self._read_disk()
                if fresh is not None:
                    self._backends = fresh
                changed = bool(mutate(self._backends))
                if changed:
                    data = {k: asdict(v) for k, v in self._backends.items()}
                    if safe_write_json(REGISTRY_FILE, data, label="llm_registry"):
                        try:
                            self._file_mtime = REGISTRY_FILE.stat().st_mtime
                        except OSError:
                            pass
                return changed
        except TimeoutError as e:
            log.error("LLM registry: %s", e)
            return False

    # ── CRUD ──────────────────────────────────────────────────────

    def clear(self):
        """Löscht alle Backends aus der Registry (z.B. nach Backend-Wechsel)."""
        def _mut(d: dict) -> bool:
            d.clear()
            return True

        self._atomic_modify(_mut)
        log.info("LLM Registry geleert")

    def add(self, cfg: BackendConfig) -> str:
        def _mut(d: dict) -> bool:
            d[cfg.name] = cfg
            return True

        self._atomic_modify(_mut)
        log.info("Registry: added backend '%s' tags=%s", cfg.name, cfg.tags)
        return f"Backend '{cfg.name}' added."

    def update(self, name: str, **kwargs) -> str:
        def _mut(d: dict) -> bool:
            backend = d.get(name)
            if backend is None:
                return False
            _INT_FIELDS = {"priority", "max_tokens", "timeout", "max_input_tokens"}
            _FLOAT_FIELDS = {"temperature"}
            _BOOL_FIELDS = {"enabled"}
            # original_priority ist bewusst nullable – None löscht die Parkung.
            _NULLABLE_INT_FIELDS = {"original_priority"}
            for k, v in kwargs.items():
                if not hasattr(backend, k):
                    continue
                if k in _NULLABLE_INT_FIELDS:
                    v = None if v is None else int(v)
                elif k in _INT_FIELDS:
                    v = int(v)
                elif k in _FLOAT_FIELDS:
                    v = float(v)
                elif k in _BOOL_FIELDS:
                    if isinstance(v, str):
                        v = v.lower() not in ("false", "0", "no", "off")
                    else:
                        v = bool(v)
                elif k == "tags" and isinstance(v, str):
                    v = [t.strip() for t in v.split(",") if t.strip()]
                setattr(backend, k, v)
            return True

        if not self._atomic_modify(_mut):
            return f"Backend '{name}' not found."
        return f"Backend '{name}' updated."

    def remove(self, name: str) -> str:
        def _mut(d: dict) -> bool:
            if name not in d:
                return False
            del d[name]
            return True

        if not self._atomic_modify(_mut):
            return f"Backend '{name}' not found."
        return f"Backend '{name}' removed."

    def get(self, name: str) -> BackendConfig | None:
        return self._backends.get(name)

    def list_all(self) -> list[BackendConfig]:
        self._reload_if_changed()
        return sorted(self._backends.values(), key=lambda b: (-int(b.priority), b.name))

    def list_enabled(self) -> list[BackendConfig]:
        return [b for b in self.list_all() if b.enabled]

    # ── Tag-based lookup ──────────────────────────────────────────

    def find_by_tags(
        self, tags: list[str], min_overlap: int = 1
    ) -> list[BackendConfig]:
        """
        Return enabled backends sorted by tag overlap (descending),
        then priority (descending).

        If tags are empty or no overlap is found (with min_overlap=1),
        it falls back to all enabled backends sorted by priority.
        """
        all_enabled = self.list_enabled()
        if not tags:
            return all_enabled

        results = []
        for b in all_enabled:
            overlap = b.tag_overlap(tags)
            if overlap >= min_overlap:
                results.append((overlap, b.priority, b))

        if not results and min_overlap == 1:
            return all_enabled

        results.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [b for _, _, b in results]

    def best_for_tags(self, tags: list[str]) -> BackendConfig | None:
        """Return the single best backend for the given tags."""
        matches = self.find_by_tags(tags, min_overlap=1)
        return matches[0] if matches else None

    def all_tags(self) -> list[str]:
        """All unique tags across all registered backends."""
        tags = set()
        for b in self._backends.values():
            tags.update(t.lower() for t in b.tags)
        return sorted(tags)

    # ── Bootstrap from global config ─────────────────────────────

    _NVIDIA_NIM_URL = "integrate.api.nvidia.com"

    def bootstrap_from_config(self, cfg) -> bool:
        """
        Auto-populate registry from PiClawConfig on first boot.
        Only runs if registry is empty.
        Returns True if backends were added.
        """
        if self._backends:
            return False

        llm = cfg.llm
        # Lokales Backend hat keinen API-Key – trotzdem registrieren
        if not llm.api_key and llm.backend not in ("local", "ollama"):
            return False

        # Kimi K2 via NVIDIA NIM bekommt empfohlene temperature=0.6
        is_nim = self._NVIDIA_NIM_URL in (llm.base_url or "")
        temp = 0.6 if is_nim else 0.7

        name = f"{llm.backend}-default"
        default = BackendConfig(
            name=name,
            provider=llm.backend,
            model=llm.model,
            api_key=llm.api_key,
            base_url=llm.base_url,
            tags=["general", "reasoning", "analysis", "coding"],
            priority=8,
            temperature=temp,
            notes="Auto-imported from config.toml",
        )
        self.add(default)
        log.info("Registry bootstrapped from config: %s", name)

        # NVIDIA NIM: Nemotron automatisch als zweites Backend hinzufügen
        if is_nim:
            self._add_nemotron_backend(llm.api_key)

        return True

    def ensure_nemotron_backend(self, cfg) -> bool:
        """
        Fügt Nemotron als zweites NVIDIA-NIM-Backend hinzu falls:
          - NVIDIA NIM als base_url konfiguriert ist
          - Nemotron noch nicht in der Registry ist
        Kann auch nachträglich aufgerufen werden (Registry nicht leer).
        Returns True wenn Nemotron hinzugefügt wurde.
        """
        llm = cfg.llm
        if self._NVIDIA_NIM_URL not in (llm.base_url or ""):
            return False
        if "nemotron-nvidia" in self._backends:
            return False
        return self._add_nemotron_backend(llm.api_key)

    def _add_nemotron_backend(self, api_key: str) -> bool:
        """Internes Hinzufügen des Nemotron-Backends."""
        # Falls das Modell auf NIM nicht verfügbar ist, kann es über piclaw llm update geändert werden
        nemotron = BackendConfig(
            name="nemotron-nvidia",
            provider="openai",
            model="meta/llama-4-maverick-17b-128e-instruct",  # aktuelles Modell (Stand 2026-03)
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1",
            tags=["general", "reasoning", "fast", "summarization"],
            priority=6,
            temperature=0.7,
            timeout=90,
            notes=(
                "Llama 4 Maverick via NVIDIA NIM – "
                "Redundanz-Backend wenn Groq nicht verfügbar. "
                "Modell-ID anpassen: piclaw llm update nemotron-nvidia --model <model>"
            ),
        )
        self.add(nemotron)
        log.info(
            "Registry: NVIDIA NIM Backend hinzugefügt (meta/llama-4-maverick-17b-128e-instruct)"
        )
        return True

    # ── Status summary ────────────────────────────────────────────

    def summary(self) -> str:
        backends = self.list_all()
        if not backends:
            return "No backends registered. Run: piclaw llm add"
        lines = [f"LLM Backends ({len(backends)} registered):\n"]
        for b in backends:
            status = "✅" if b.enabled else "⏸"
            key = "🔑" if b.api_key else "  "
            lines.append(
                f"  {status} {key} [{b.priority:2}] {b.name}\n"
                f"        {b.provider}/{b.model}\n"
                f"        tags: {', '.join(b.tags) or '(none)'}\n"
                f"        {b.notes or ''}"
            )
        return "\n".join(lines)
