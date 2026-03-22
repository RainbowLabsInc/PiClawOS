import pytest

"""
PiClaw Debug – LLM API & tool_choice
Prüft welche api.py tatsächlich geladen wird und ob tool_choice korrekt gesetzt ist.
"""
import sys
import inspect
from pathlib import Path

sys.path.insert(0, "/opt/piclaw")


def section(t):
    print(f"\n{'=' * 60}\n  {t}\n{'=' * 60}")


def ok(m):
    print(f"  ✅ {m}")


def fail(m):
    print(f"  ❌ {m}")


def info(m):
    print(f"  ℹ  {m}")


section("1. Welche api.py wird geladen?")
try:
    from piclaw.llm import api as llm_api

    path = Path(inspect.getfile(llm_api))
    info(f"Geladen von: {path}")
    src = path.read_text()
    if "tool_choice wird NICHT gesetzt" in src or "NIM entscheidet selbst" in src:
        ok("Fix ist aktiv – tool_choice wird für NIM weggelassen")
    elif '"auto"' in src and "_is_nim" in src:
        fail("Alter Code aktiv – tool_choice='auto' wird für NIM gesetzt!")
        fail(f"Bitte kopieren: sudo cp /opt/piclaw/piclaw-os/piclaw/llm/api.py {path}")
    else:
        info("Unbekannte Version – Quellcode prüfen")
except Exception as e:
    fail(f"Import fehlgeschlagen: {e}")

section("2. LLM Registry – welche Backends sind aktiv?")
try:
    from piclaw.config import load

    cfg = load()
    info(f"Backend:  {cfg.llm.backend}")
    info(f"Model:    {cfg.llm.model}")
    info(f"Base URL: {cfg.llm.base_url}")
    info(f"API Key:  {'***gesetzt***' if cfg.llm.api_key else '(leer)'}")
except Exception as e:
    fail(f"Config laden: {e}")

section("3. Registry-Datei")
try:
    import json

    reg_path = Path("/etc/piclaw/llm_registry.json")
    if reg_path.exists():
        reg = json.loads(reg_path.read_text())
        backends = reg.get("backends", {})
        for name, b in backends.items():
            enabled = "✅" if b.get("enabled") else "⬜"
            info(
                f"{enabled} {name}: {b.get('model', '?')} @ {b.get('base_url', '?')[:40]}"
            )
    else:
        info("Keine Registry-Datei gefunden")
except Exception as e:
    fail(f"Registry: {e}")

section("4. Minimaler API-Test (ohne Tools)")
import asyncio


@pytest.mark.asyncio
async def test_api():
    try:
        from piclaw.llm.api import OpenAIBackend
        from piclaw.config import load

        cfg = load()
        if not cfg.llm.api_key:
            fail("Kein API-Key – Test nicht möglich")
            return
        backend = OpenAIBackend(
            api_key=cfg.llm.api_key,
            model=cfg.llm.model,
            base_url=cfg.llm.base_url,
            temperature=0.6,
            max_tokens=50,
            timeout=10,
        )
        info("Sende Test-Nachricht (ohne Tools)...")
        from piclaw.llm.base import Message

        resp = await backend.chat(
            [Message(role="user", content="Antworte nur mit: OK")]
        )
        ok(f"Antwort: {resp.content[:80]}")
    except Exception as e:
        fail(f"API-Test: {e}")


asyncio.run(test_api())

section("5. API-Test MIT Tools")


@pytest.mark.asyncio
async def test_with_tools():
    try:
        from piclaw.llm.api import OpenAIBackend
        from piclaw.llm.base import Message, ToolDefinition
        from piclaw.config import load

        cfg = load()
        if not cfg.llm.api_key:
            fail("Kein API-Key")
            return
        backend = OpenAIBackend(
            api_key=cfg.llm.api_key,
            model=cfg.llm.model,
            base_url=cfg.llm.base_url,
            temperature=0.6,
            max_tokens=50,
            timeout=10,
        )
        dummy_tool = ToolDefinition(
            name="test_tool",
            description="Ein Test-Tool",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        info("Sende Test-Nachricht MIT Tool...")
        resp = await backend.chat(
            [Message(role="user", content="Antworte nur mit: OK")], tools=[dummy_tool]
        )
        ok(f"Kein 400-Fehler! Antwort: {resp.content[:60]}")
    except Exception as e:
        if "400" in str(e):
            fail(f"HTTP 400 – tool_choice Fix nicht aktiv: {e}")
        else:
            fail(f"Anderer Fehler: {e}")


asyncio.run(test_with_tools())

print(f"\n{'=' * 60}\n  ✉  Output an Entwickler senden\n{'=' * 60}\n")
