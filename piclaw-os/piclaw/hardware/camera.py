"""
PiClaw OS – Pi-Kamera-Integration (v0.10)

Unterstützt:
  - Raspberry Pi Camera Module (libcamera / picamera2)
  - USB-Webcams (via OpenCV / v4l2)
  - Snapshot, Videostream (MJPEG), Zeitraffer
  - Vision-LLM-Tool: Bild aufnehmen → direkt analysieren lassen

Agent-Tools:
  camera_snapshot(filename?)  → nimmt Foto auf, gibt Pfad zurück
  camera_describe(prompt?)    → Foto + Vision-LLM → Beschreibung
  camera_list()               → verfügbare Kameras
  camera_timelapse(...)       → Zeitraffer starten/stoppen
"""

from __future__ import annotations

import asyncio
import base64
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CAPTURE_DIR = Path("/var/lib/piclaw/camera")
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


# ── Kamera-Detektion ─────────────────────────────────────────────


@dataclass
class CameraInfo:
    index: int
    name: str
    driver: str  # "libcamera" | "v4l2" | "picamera2"
    available: bool = True
    resolution: tuple[int, int] = (1920, 1080)


def detect_cameras() -> list[CameraInfo]:
    """Erkennt verfügbare Kameras automatisch."""
    cameras: list[CameraInfo] = []

    # Pi Camera über libcamera
    try:
        result = subprocess.run(
            ["libcamera-hello", "--list-cameras"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and "Available cameras" in result.stdout:
            lines = result.stdout.strip().split("\n")
            for i, line in enumerate(lines):
                if ":" in line and not line.startswith("Available"):
                    cameras.append(
                        CameraInfo(
                            index=len(cameras),
                            name=f"Pi Camera {len(cameras)}",
                            driver="libcamera",
                            resolution=(4608, 2592),  # Pi Camera 3 default
                        )
                    )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # USB-Webcams via v4l2
    try:
        for dev in sorted(Path("/dev").glob("video*")):
            idx = int(dev.name.replace("video", ""))
            result = subprocess.run(
                ["v4l2-ctl", f"--device={dev}", "--info"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            name = "USB Camera"
            if result.returncode == 0:
                for l in result.stdout.split("\n"):
                    if "Card type" in l:
                        name = l.split(":", 1)[-1].strip()
                        break
            cameras.append(
                CameraInfo(
                    index=idx,
                    name=name,
                    driver="v4l2",
                    resolution=(1920, 1080),
                )
            )
    except Exception as _e:
        log.debug("v4l2 camera enumeration: %s", _e)

    return cameras


# ── Aufnahme ─────────────────────────────────────────────────────


async def capture_snapshot(
    camera_index: int = 0,
    filename: str | None = None,
    resolution: tuple[int, int] = (1920, 1080),
    quality: int = 90,
) -> Path:
    """Nimmt ein Foto auf. Gibt den Pfad zur Datei zurück."""
    if filename is None:
        ts = int(time.time())
        filename = f"snapshot_{ts}.jpg"

    output = CAPTURE_DIR / filename
    output.parent.mkdir(parents=True, exist_ok=True)

    # Versuche libcamera zuerst (Pi Camera)
    try:
        result = await asyncio.create_subprocess_exec(
            "libcamera-still",
            "-o",
            str(output),
            "--width",
            str(resolution[0]),
            "--height",
            str(resolution[1]),
            "-q",
            str(quality),
            "--nopreview",
            "--timeout",
            "2000",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=15)
        if result.returncode == 0 and output.exists():
            logger.info("Snapshot (libcamera): %s", output)
            return output
    except (FileNotFoundError, asyncio.TimeoutError):
        pass

    # Fallback: fswebcam (USB-Webcam)
    try:
        result = await asyncio.create_subprocess_exec(
            "fswebcam",
            "-d",
            f"/dev/video{camera_index}",
            "-r",
            f"{resolution[0]}x{resolution[1]}",
            "--jpeg",
            str(quality),
            "--no-banner",
            str(output),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(result.communicate(), timeout=10)
        if output.exists():
            logger.info("Snapshot (fswebcam): %s", output)
            return output
    except (FileNotFoundError, asyncio.TimeoutError):
        pass

    # Fallback: raspistill (ältere Pis)
    try:
        result = await asyncio.create_subprocess_exec(
            "raspistill",
            "-o",
            str(output),
            "-w",
            str(resolution[0]),
            "-h",
            str(resolution[1]),
            "-q",
            str(quality),
            "-n",
            "-t",
            "2000",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(result.communicate(), timeout=15)
        if output.exists():
            logger.info("Snapshot (raspistill): %s", output)
            return output
    except (FileNotFoundError, asyncio.TimeoutError):
        pass

    raise RuntimeError(
        "Keine Kamera gefunden. Installiere libcamera-apps (Pi Camera) oder fswebcam (USB)."
    )


async def describe_image(
    image_path: Path,
    prompt: str = "Beschreibe was du auf diesem Bild siehst.",
    llm_client: Any = None,
) -> str:
    """
    Sendet ein Bild an das Vision-LLM und gibt die Beschreibung zurück.
    Funktioniert mit Claude (claude-3-sonnet und neuer) und OpenAI GPT-4V.
    """
    if not image_path.exists():
        return f"Fehler: Bild nicht gefunden: {image_path}"

    # Bild als Base64
    image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    media_type = "image/jpeg"
    if image_path.suffix.lower() == ".png":
        media_type = "image/png"

    if llm_client is None:
        # Versuche den Standard-Client zu laden
        try:
            from piclaw.llm import get_client

            llm_client = get_client()
        except Exception:
            return "Kein LLM-Client verfügbar für Vision."

    try:
        response = await llm_client.complete_with_image(
            prompt=prompt,
            image_data=image_data,
            media_type=media_type,
        )
        return response
    except AttributeError:
        # Client unterstützt kein Vision → beschreibende Antwort
        size_kb = round(image_path.stat().st_size / 1024, 1)
        return f"Bild aufgenommen: {image_path.name} ({size_kb} KB). Vision-LLM nicht verfügbar."
    except Exception as e:
        logger.error("Vision LLM Fehler: %s", e)
        return f"Vision-Analyse fehlgeschlagen: {e}"


# ── Zeitraffer ────────────────────────────────────────────────────


@dataclass
class TimelapseConfig:
    interval_s: int = 60
    max_frames: int = 1440  # 24h bei 1fps
    output_dir: Path = field(default_factory=lambda: CAPTURE_DIR / "timelapse")
    name: str = "timelapse"
    resolution: tuple[int, int] = (1280, 720)


class TimelapseController:
    """Steuert Zeitraffer-Aufnahmen als asyncio-Task."""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self._frame_counts: dict[str, int] = {}

    def status(self) -> dict:
        return {
            name: {
                "running": not self._stop_events[name].is_set(),
                "frames": self._frame_counts.get(name, 0),
            }
            for name in self._tasks
        }

    async def start(self, cfg: TimelapseConfig) -> str:
        if cfg.name in self._tasks and not self._tasks[cfg.name].done():
            return f"Zeitraffer '{cfg.name}' läuft bereits."

        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        stop_event = asyncio.Event()
        self._stop_events[cfg.name] = stop_event
        self._frame_counts[cfg.name] = 0
        task = asyncio.create_task(
            self._run(cfg, stop_event),
            name=f"timelapse_{cfg.name}",
        )
        self._tasks[cfg.name] = task
        return f"Zeitraffer '{cfg.name}' gestartet ({cfg.interval_s}s Intervall, max {cfg.max_frames} Frames)."

    async def stop(self, name: str) -> str:
        if name not in self._stop_events:
            return f"Zeitraffer '{name}' nicht gefunden."
        self._stop_events[name].set()
        frames = self._frame_counts.get(name, 0)
        return f"Zeitraffer '{name}' gestoppt. {frames} Frames aufgenommen."

    async def _run(self, cfg: TimelapseConfig, stop_event: asyncio.Event):
        frame = 0
        while not stop_event.is_set() and frame < cfg.max_frames:
            try:
                filename = f"{cfg.name}_{frame:05d}.jpg"
                await capture_snapshot(
                    filename=str(cfg.output_dir / filename),
                    resolution=cfg.resolution,
                    quality=80,
                )
                frame += 1
                self._frame_counts[cfg.name] = frame
            except Exception as e:
                logger.warning("Timelapse Frame %d fehlgeschlagen: %s", frame, e)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cfg.interval_s)
                break
            except asyncio.TimeoutError:
                pass

        logger.info("Timelapse '%s' beendet: %d Frames", cfg.name, frame)


# ── Agent-Tools ──────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "camera_snapshot",
        "description": "Nimmt ein Foto mit der Kamera auf. Gibt den Pfad zur gespeicherten Bilddatei zurück.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Optionaler Dateiname (ohne Pfad). Standard: snapshot_<timestamp>.jpg",
                },
                "resolution": {
                    "type": "string",
                    "description": "Auflösung: 'hd' (1920x1080), 'fhd' (1920x1080), '4k' (3840x2160). Standard: hd",
                },
            },
        },
    },
    {
        "name": "camera_describe",
        "description": "Nimmt ein Foto auf und lässt es vom Vision-LLM analysieren/beschreiben.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Aufgabe/Frage für das Vision-LLM. Standard: allgemeine Beschreibung",
                },
            },
        },
    },
    {
        "name": "camera_list",
        "description": "Listet alle verfügbaren Kameras auf (Pi Camera, USB-Webcams).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "camera_timelapse_start",
        "description": "Startet einen Zeitraffer. Macht automatisch Fotos im angegebenen Intervall.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name des Zeitraffers"},
                "interval_s": {
                    "type": "integer",
                    "description": "Intervall in Sekunden (z.B. 60 für 1 Foto/Min)",
                },
                "max_frames": {
                    "type": "integer",
                    "description": "Max. Anzahl Fotos (Standard: 1440)",
                },
            },
            "required": ["name", "interval_s"],
        },
    },
    {
        "name": "camera_timelapse_stop",
        "description": "Stoppt einen laufenden Zeitraffer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name des zu stoppenden Zeitraffers",
                }
            },
            "required": ["name"],
        },
    },
]

_timelapse_ctrl = TimelapseController()
_RESOLUTIONS = {"hd": (1280, 720), "fhd": (1920, 1080), "4k": (3840, 2160)}


async def handle_tool(name: str, params: dict, llm_client=None) -> str:
    if name == "camera_snapshot":
        res_key = params.get("resolution", "hd")
        resolution = _RESOLUTIONS.get(res_key, (1280, 720))
        try:
            path = await capture_snapshot(
                filename=params.get("filename"),
                resolution=resolution,
            )
            size_kb = round(path.stat().st_size / 1024, 1)
            return f"Foto aufgenommen: {path} ({size_kb} KB)"
        except Exception as e:
            return f"Kamera-Fehler: {e}"

    elif name == "camera_describe":
        prompt = params.get("prompt", "Beschreibe was du auf diesem Bild siehst.")
        try:
            path = await capture_snapshot(resolution=(1280, 720))
            description = await describe_image(path, prompt, llm_client)
            return f"Bild: {path.name}\n\n{description}"
        except Exception as e:
            return f"Fehler: {e}"

    elif name == "camera_list":
        cameras = detect_cameras()
        if not cameras:
            return "Keine Kameras gefunden. Ist eine Pi Camera oder USB-Webcam angeschlossen?"
        lines = [f"Gefundene Kameras ({len(cameras)}):"]
        for cam in cameras:
            lines.append(
                f"  [{cam.index}] {cam.name} ({cam.driver}, {cam.resolution[0]}x{cam.resolution[1]})"
            )
        return "\n".join(lines)

    elif name == "camera_timelapse_start":
        cfg = TimelapseConfig(
            name=params["name"],
            interval_s=int(params["interval_s"]),
            max_frames=int(params.get("max_frames", 1440)),
        )
        return await _timelapse_ctrl.start(cfg)

    elif name == "camera_timelapse_stop":
        return await _timelapse_ctrl.stop(params["name"])

    return f"Unbekanntes Kamera-Tool: {name}"
