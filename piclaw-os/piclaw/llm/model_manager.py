"""
PiClaw OS – Model Manager
Download, verify and manage local GGUF models.
"""

import logging
from pathlib import Path

import aiohttp

from piclaw.llm.local import DEFAULT_MODEL_PATH, MODEL_URL

log = logging.getLogger("piclaw.model")

MODELS = {
    "gemma2b-q4": {
        "name": "Gemma 2B Instruct Q4  ★ Standard",
        "url": MODEL_URL,
        "path": DEFAULT_MODEL_PATH,
        "size_gb": 1.6,
        "desc": "Empfohlen für Pi 5 – beste Qualität, ~10-15s Antwortzeit",
    },
    "phi3-mini-q4": {
        "name": "Phi-3 Mini 4K Instruct Q4",
        "url": (
            "https://huggingface.co/bartowski/Phi-3-mini-4k-instruct-GGUF"
            "/resolve/main/Phi-3-mini-4k-instruct-Q4_K_M.gguf"
        ),
        "url_fallback": (
            "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf"
            "/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
        ),
        "path": DEFAULT_MODEL_PATH.parent / "phi3-mini-q4.gguf",
        "size_gb": 2.2,
        "desc": "Gut für komplexe Aufgaben, ~30-90s Antwortzeit",
    },
    "tinyllama-q4": {
        "name": "TinyLlama 1.1B Q4  (schnellstes Modell)",
        "url": (
            "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"
            "/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
        ),
        "path": DEFAULT_MODEL_PATH.parent / "tinyllama-q4.gguf",
        "size_gb": 0.7,
        "desc": "Sehr schnell ~5s, begrenzte Intelligenz – gut als Fallback",
    },
}

DEFAULT_MODEL_ID = "gemma2b-q4"


async def download_model(model_id: str = DEFAULT_MODEL_ID) -> str:
    if model_id not in MODELS:
        return f"Unknown model: {model_id}. Available: {', '.join(MODELS.keys())}"

    info = MODELS[model_id]
    dest = Path(info["path"])
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        size_mb = dest.stat().st_size // 1_048_576
        return f"Model already downloaded: {dest} ({size_mb} MB)"

    log.info("Downloading %s (%.1f GB)…", info["name"], info["size_gb"])
    print(
        f"\n📥 Downloading {info['name']} ({info['size_gb']:.1f} GB)…"
    )  # intentional progress output
    print(f"   → {dest}\n")
    log.info("Model download start: %s → %s", info["name"], dest)

    # Primäre URL, bei 401/403 Fallback versuchen
    urls_to_try = [info["url"]]
    if info.get("url_fallback"):
        urls_to_try.append(info["url_fallback"])

    try:
        # Total-Timeout absichtlich sehr groß (große Modelle >4 GB), aber Connect-Timeout kurz
        dl_timeout = aiohttp.ClientTimeout(total=7200, connect=30, sock_read=120)
        async with aiohttp.ClientSession(timeout=dl_timeout) as session:
            last_err = None
            resp = None
            for url in urls_to_try:
                try:
                    resp = await session.get(url)
                    if resp.status in (401, 403):
                        log.warning(
                            "URL %s: HTTP %s – versuche Fallback", url, resp.status
                        )
                        await resp.release()
                        resp = None
                        continue
                    resp.raise_for_status()
                    break
                except Exception as e:
                    last_err = e
                    resp = None
            if resp is None:
                raise Exception(last_err or "Alle Download-URLs fehlgeschlagen")
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1 MB chunks

            with open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        done = int(pct / 2)
                        bar = "█" * done + "░" * (50 - done)
                        mb = downloaded // 1_048_576
                        print(f"\r  [{bar}] {pct:.1f}% ({mb} MB)", end="", flush=True)

        log.info("Downloaded: %s", dest)
        print(f"\n\n✅ Downloaded: {dest}")  # intentional progress output
        size_mb = dest.stat().st_size // 1_048_576
        log.info("Model download complete: %s (%d MB)", dest, size_mb)

        # Config automatisch aktualisieren damit doctor + agent den richtigen Pfad kennen
        try:
            from piclaw.config import load as _load, save as _save

            _cfg = _load()
            if _cfg.llm.backend == "local":
                _cfg.llm.model = str(dest)
                _save(_cfg)
                log.info("config.toml: llm.model → %s", dest)
                print(f"✅ config.toml aktualisiert: llm.model = {dest}")
        except Exception as _ce:
            log.debug("config update after download: %s", _ce)

        return f"Model ready: {dest} ({size_mb} MB)"

    except Exception as e:
        # Remove partial download
        if dest.exists():
            dest.unlink()
        log.error("Model download failed: %s", e)
        return f"Download failed: {e}"


def list_models() -> str:
    lines = ["Verfügbare lokale Modelle:\n"]
    for mid, info in MODELS.items():
        path = Path(info["path"])
        status = (
            f"✅ installiert ({path.stat().st_size // 1_048_576} MB)"
            if path.exists()
            else "⬇  nicht heruntergeladen"
        )
        default = "  ← Standard" if mid == DEFAULT_MODEL_ID else ""
        lines.append(
            f"  piclaw model download {mid}{default}\n"
            f"    {info['name']}\n"
            f"    {info['desc']}\n"
            f"    Größe: ~{info['size_gb']:.1f} GB  |  {status}\n"
        )
    return "\n".join(lines)


def remove_model(model_id: str) -> str:
    if model_id not in MODELS:
        return f"Unknown model: {model_id}"
    path = Path(MODELS[model_id]["path"])
    if not path.exists():
        return f"Model not found: {path}"
    path.unlink()
    return f"Removed: {path}"
