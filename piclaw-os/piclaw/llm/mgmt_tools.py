"""
PiClaw OS – LLM Management Tools
Agent-callable tools for managing the LLM registry at runtime.
"""

from piclaw.llm.base import ToolDefinition
from piclaw.llm.registry import LLMRegistry, BackendConfig

TOOL_DEFS = [
    ToolDefinition(
        name="llm_list",
        description="Show all configured LLM backends with their tags, priority and health status.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="llm_add",
        description=(
            "Add a new LLM backend to the registry. "
            "Tags define what kinds of tasks this backend is good at. "
            "Example tags: coding, debugging, creative, writing, german, reasoning, math, fast."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name, e.g. 'gpt4o-coding'",
                },
                "provider": {
                    "type": "string",
                    "enum": ["anthropic", "openai", "ollama", "local"],
                },
                "model": {
                    "type": "string",
                    "description": "Model string, e.g. 'gpt-4o'",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Capability tags this backend is best at",
                },
                "priority": {
                    "type": "integer",
                    "description": "1–10, higher = preferred when tied",
                    "default": 5,
                },
                "api_key": {
                    "type": "string",
                    "description": "API key (leave empty to use global key)",
                },
                "base_url": {
                    "type": "string",
                    "description": "Override API endpoint URL",
                },
                "temperature": {"type": "number", "default": 0.7},
                "max_tokens": {"type": "integer", "default": 4096},
                "notes": {
                    "type": "string",
                    "description": "Human-readable description",
                },
            },
            "required": ["name", "provider", "model", "tags"],
        },
    ),
    ToolDefinition(
        name="llm_update",
        description="Update tags, priority, or other settings of an existing LLM backend.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "integer"},
                "enabled": {"type": "boolean"},
                "notes": {"type": "string"},
                "temperature": {"type": "number"},
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="llm_remove",
        description="Remove an LLM backend from the registry.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="llm_test",
        description="Send a test message to a specific backend to verify it works.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Backend name to test"},
                "prompt": {
                    "type": "string",
                    "description": "Test prompt",
                    "default": "Reply with OK.",
                },
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="llm_classify",
        description="Show how PiClaw would classify a given message and which backend would handle it.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to classify"},
            },
            "required": ["message"],
        },
    ),
    ToolDefinition(
        name="llm_discover",
        description=(
            "Proactively discover and register new free LLM backends. "
            "Scans all known providers (Groq, NVIDIA NIM, Cerebras, OpenRouter) for "
            "available free-tier models, tests them, and auto-registers working ones. "
            "Also suggests providers where no API key exists yet. "
            "Call this periodically or when backends are degraded."
        ),
        parameters={
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "description": "If true, re-test even already-registered models",
                    "default": False,
                },
            },
        },
    ),
]


def build_handlers(registry: LLMRegistry, router) -> dict:

    async def llm_list() -> str:
        status = router.get_status_dict()
        backends = status.get("backends", [])
        if not backends:
            return "No backends configured. Use llm_add to add one."
        lines = [f"LLM Backends ({len(backends)}):\n"]
        for b in backends:
            icons = []
            if b["enabled"]:
                icons.append("✅")
            else:
                icons.append("⏸")
            if b["degraded"]:
                icons.append("⚠️")
            lines.append(
                f"  {''.join(icons)} [{b['priority']:2}] {b['name']}\n"
                f"       {b['provider']}/{b['model']}\n"
                f"       tags: {', '.join(b['tags']) or '(none)'}\n"
                f"       calls: {b['calls']}  errors: {b['errors']}  avg: {b['avg_ms']}ms"
            )
        lines.append(f"\nAll tags in use: {', '.join(status.get('all_tags', []))}")
        return "\n\n".join(lines)

    async def llm_add(
        name: str,
        provider: str,
        model: str,
        tags: list,
        priority: int = 5,
        api_key: str = "",
        base_url: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        notes: str = "",
    ) -> str:
        cfg = BackendConfig(
            name=name,
            provider=provider,
            model=model,
            tags=tags,
            priority=priority,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            notes=notes,
        )
        result = registry.add(cfg)
        # Register health tracker
        from piclaw.llm.multirouter import BackendHealth

        router._health[name] = BackendHealth(name=name)
        return result + f"\nTags assigned: {', '.join(tags)}"

    async def llm_update(name: str, **kwargs) -> str:
        return registry.update(
            name, **{k: v for k, v in kwargs.items() if v is not None}
        )

    async def llm_remove(name: str) -> str:
        result = registry.remove(name)
        router._instances.pop(name, None)
        router._health.pop(name, None)
        return result

    async def llm_test(name: str, prompt: str = "Reply with OK.") -> str:
        import time

        cfg = registry.get(name)
        if not cfg:
            return f"Backend '{name}' not found."
        try:
            from piclaw.llm.base import Message

            instance = router._get_instance(cfg)
            t = time.time()
            resp = await instance.chat([Message(role="user", content=prompt)])
            ms = int((time.time() - t) * 1000)
            return f"✅ Backend '{name}' responded in {ms}ms:\n{resp.content[:500]}"
        except Exception as e:
            return f"❌ Backend '{name}' failed: {e}"

    async def llm_classify(message: str) -> str:
        result = await router._classifier.classify(message)
        matches = registry.find_by_tags(result.tags, min_overlap=1)
        lines = [
            f'Message: "{message[:80]}"',
            f"Detected tags: {', '.join(result.tags)}",
            f"Confidence: {result.confidence:.0%} (method: {result.method})",
            "",
            "Backend selection:",
        ]
        if matches:
            for i, b in enumerate(matches[:3]):
                marker = "→ SELECTED" if i == 0 else f"  fallback {i}"
                overlap = b.tag_overlap(result.tags)
                lines.append(
                    f"  {marker}: {b.name} "
                    f"(overlap={overlap}/{len(result.tags)}, priority={b.priority})"
                )
        else:
            lines.append("  No matching backends – would use highest-priority backend.")
        return "\n".join(lines)

    async def llm_discover(force: bool = False) -> str:
        """
        Proaktive LLM-Backend-Discovery: Scannt alle bekannten Free-Tier-Provider,
        findet neue kostenlose Modelle, testet sie und registriert funktionierende.

        Ablauf:
          1. Provider MIT vorhandenem API-Key → neue Modelle entdecken + testen
          2. Provider OHNE Key → als Vorschlag melden
          3. Ergebnis: Report mit registrierten + vorgeschlagenen Backends
        """
        import aiohttp
        import time
        from urllib.parse import urlparse
        from piclaw.llm.health_monitor import (
            _PROVIDER_MODEL_ENDPOINTS,
            _FREE_TIER_MODELS,
            _PROVIDER_SIGNUP_URLS,
        )

        lines = ["🔍 LLM Auto-Discovery gestartet…\n"]
        registered = []
        tested_ok = []
        tested_fail = []
        suggestions = []

        # ── 1. Bestehende Keys nach Provider-Host gruppieren ──────
        all_backends = registry.list_all() if hasattr(registry, "list_all") else []
        used_models = {b.model for b in all_backends}
        used_names = {b.name for b in all_backends}

        provider_keys: dict[str, tuple[str, str]] = {}  # host → (api_key, base_url)
        for b in all_backends:
            if not b.base_url or not b.api_key or b.provider == "local":
                continue
            host = urlparse(b.base_url).netloc
            if host not in provider_keys:
                provider_keys[host] = (b.api_key, b.base_url)

        # ── 2. Provider MIT Key: Modelle entdecken + testen ───────
        for host, (api_key, base_url) in provider_keys.items():
            models_url = _PROVIDER_MODEL_ENDPOINTS.get(host)
            if not models_url:
                continue

            host_short = {
                "api.groq.com": "Groq",
                "integrate.api.nvidia.com": "NVIDIA NIM",
                "api.cerebras.ai": "Cerebras",
                "openrouter.ai": "OpenRouter",
                "generativelanguage.googleapis.com": "Google Gemini",
                "models.github.ai": "GitHub Models",
            }.get(host, host)

            lines.append(f"📡 **{host_short}** (Key vorhanden)")

            # Modell-Liste abrufen
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        models_url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as r:
                        if r.status != 200:
                            lines.append(f"   ⚠️ Modell-Liste nicht abrufbar (HTTP {r.status})")
                            continue
                        data = await r.json()
                available = {m["id"] for m in data.get("data", [])}
            except Exception as e:
                lines.append(f"   ❌ Fehler: {e}")
                continue

            # Whitelist-Modelle filtern
            whitelist = _FREE_TIER_MODELS.get(host, [])
            candidates = [
                m for m in whitelist
                if m in available and (force or m not in used_models)
            ]

            if not candidates:
                lines.append(f"   ✅ Alle freien Modelle bereits registriert")
                continue

            lines.append(f"   🔎 {len(candidates)} Kandidat(en) gefunden, teste…")

            for model in candidates:
                # Test: einfacher Chat-Request
                try:
                    url = f"{base_url.rstrip('/')}/chat/completions"
                    payload = {
                        "model": model,
                        "messages": [{"role": "user", "content": "Reply with: OK"}],
                        "max_tokens": 5,
                    }
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }
                    t0 = time.time()
                    async with aiohttp.ClientSession() as s:
                        async with s.post(
                            url, json=payload, headers=headers,
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as r:
                            ms = int((time.time() - t0) * 1000)
                            if r.status == 200:
                                tested_ok.append((model, host_short, ms))

                                # Auto-registrieren wenn noch nicht vorhanden
                                p_short = {
                                    "api.groq.com": "groq",
                                    "integrate.api.nvidia.com": "nvidia",
                                    "api.cerebras.ai": "cerebras",
                                    "openrouter.ai": "openrouter",
                                    "generativelanguage.googleapis.com": "gemini",
                                    "models.github.ai": "github",
                                }.get(host, host.split(".")[0])
                                m_short = model.split("/")[-1][:20]
                                new_name = f"auto-{p_short}-{m_short}"

                                if new_name not in used_names:
                                    new_cfg = BackendConfig(
                                        name=new_name,
                                        provider="openai",
                                        model=model,
                                        api_key=api_key,
                                        base_url=base_url,
                                        tags=["general", "auto-discovered", "free-tier"],
                                        priority=4,  # Niedrig – Originale bevorzugen
                                        temperature=0.7,
                                        notes=f"Auto-discovered free-tier ({host_short})",
                                    )
                                    registry.add(new_cfg)
                                    from piclaw.llm.multirouter import BackendHealth
                                    router._health[new_name] = BackendHealth(name=new_name)
                                    registered.append((new_name, model, host_short, ms))
                                    used_names.add(new_name)
                                    lines.append(
                                        f"   ✅ `{model}` → registriert als `{new_name}` ({ms}ms)"
                                    )
                                else:
                                    lines.append(
                                        f"   ✅ `{model}` → OK ({ms}ms), bereits als `{new_name}` vorhanden"
                                    )
                            else:
                                body = await r.text()
                                reason = body[:80] if body else f"HTTP {r.status}"
                                tested_fail.append((model, host_short, reason))
                                lines.append(f"   ❌ `{model}` → {reason}")
                except Exception as e:
                    tested_fail.append((model, host_short, str(e)[:60]))
                    lines.append(f"   ❌ `{model}` → {e}")

        # ── 3. Provider OHNE Key: Vorschlagen ─────────────────────
        known_hosts = set(provider_keys.keys())
        for host, (signup_url, env_name, info) in _PROVIDER_SIGNUP_URLS.items():
            if host in known_hosts:
                continue

            host_short = {
                "api.groq.com": "Groq",
                "integrate.api.nvidia.com": "NVIDIA NIM",
                "api.cerebras.ai": "Cerebras",
                "openrouter.ai": "OpenRouter",
                "generativelanguage.googleapis.com": "Google Gemini",
                "models.github.ai": "GitHub Models",
            }.get(host, host)

            free_models = _FREE_TIER_MODELS.get(host, [])
            suggestions.append((host_short, signup_url, info, len(free_models)))
            lines.append(
                f"\n🆓 **{host_short}** – kein API-Key vorhanden"
                f"\n   {info}"
                f"\n   {len(free_models)} freie Modelle verfügbar"
                f"\n   Anmeldung: {signup_url}"
                f"\n   → `piclaw llm add --name {host_short.lower()}-free "
                f"--provider openai --model {free_models[0] if free_models else '...'} "
                f"--base-url https://{host}/v1 --api-key <KEY>`"
            )

        # ── 4. Zusammenfassung ────────────────────────────────────
        lines.append("\n" + "─" * 40)
        lines.append("📊 **Ergebnis:**")
        lines.append(f"   Neu registriert: {len(registered)}")
        lines.append(f"   Getestet OK: {len(tested_ok)}")
        lines.append(f"   Getestet fehlgeschlagen: {len(tested_fail)}")
        if suggestions:
            lines.append(f"   Neue Provider verfügbar: {len(suggestions)}")
            lines.append(
                "   → Melde dich kostenlos an und füge den Key hinzu!"
            )

        return "\n".join(lines)

    return {
        "llm_list": lambda **_: llm_list(),
        "llm_add": lambda **kw: llm_add(**kw),
        "llm_update": lambda **kw: llm_update(**kw),
        "llm_remove": lambda **kw: llm_remove(**kw),
        "llm_test": lambda **kw: llm_test(**kw),
        "llm_classify": lambda **kw: llm_classify(**kw),
        "llm_discover": lambda **kw: llm_discover(**kw),
    }
