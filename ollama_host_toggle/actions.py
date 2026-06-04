"""Core hosting actions — start/stop/status/preload/unload.

Thin wrappers around Ollama's HTTP API, Windows process control, and nvidia-smi.
All subprocess calls run windowless so nothing flashes a console under pythonw.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone

import requests

from .config import Config

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)


def _run(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )


_OLLAMA_IMAGES = ("ollama.exe", "ollama app.exe")


def ollama_running() -> bool:
    try:
        out = _run(["tasklist", "/FO", "CSV", "/NH"]).stdout.lower()
    except Exception:
        return False
    return any(img in out for img in _OLLAMA_IMAGES)


def get_version(cfg: Config) -> str | None:
    try:
        r = requests.get(cfg.version_url, timeout=3)
        r.raise_for_status()
        return r.json().get("version")
    except Exception:
        return None


def get_loaded_models(cfg: Config) -> list[dict]:
    try:
        r = requests.get(cfg.ps_url, timeout=3)
        r.raise_for_status()
        return r.json().get("models", []) or []
    except Exception:
        return []


def get_vram(cfg: Config) -> tuple[int | None, int | None]:
    try:
        out = _run([
            cfg.nvidia_smi_path,
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]).stdout.strip()
        used_s, total_s = (p.strip() for p in out.splitlines()[0].split(","))
        return int(used_s), int(total_s)
    except Exception:
        return None, None


def get_state(cfg: Config) -> dict:
    running = ollama_running()
    version = get_version(cfg) if running else None
    serving = version is not None
    models = get_loaded_models(cfg) if serving else []
    used, total = get_vram(cfg)
    return {
        "host": cfg.host_label,
        "ollamaRunning": running,
        "ollamaVersion": version,
        "loadedModels": [m.get("name") for m in models if m.get("name")],
        "vramUsedMB": used,
        "vramTotalMB": total,
        "serving": serving,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def start_serving(cfg: Config, wait_secs: int = 20) -> tuple[bool, str]:
    if not ollama_running():
        if not os.path.isfile(cfg.ollama_app_path):
            return False, f"ollama app not found at {cfg.ollama_app_path}"
        try:
            env = dict(os.environ, OLLAMA_HOST="0.0.0.0:11434")
            subprocess.Popen(
                [cfg.ollama_app_path],
                env=env,
                creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
                close_fds=True,
            )
        except Exception as e:  # noqa: BLE001
            return False, f"failed to launch ollama: {e}"

    for _ in range(wait_secs):
        if get_version(cfg) is not None:
            return True, "serving"
        time.sleep(1)
    return False, "ollama API did not respond in time"


def preload(cfg: Config, model: str) -> tuple[bool, str]:
    if not model:
        return False, "no model specified"
    try:
        r = requests.post(
            cfg.generate_url,
            json={"model": model, "prompt": "", "keep_alive": -1},
            timeout=180,
        )
        r.raise_for_status()
        return True, f"{model} loaded"
    except Exception as e:  # noqa: BLE001
        return False, f"preload failed: {e}"


def unload(cfg: Config, model: str) -> tuple[bool, str]:
    if not model:
        return False, "no model specified"
    try:
        r = requests.post(
            cfg.generate_url,
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=30,
        )
        r.raise_for_status()
        return True, f"{model} unloaded"
    except Exception as e:  # noqa: BLE001
        return False, f"unload failed: {e}"


def stop_serving(cfg: Config) -> tuple[bool, str]:
    killed_any = False
    # Kill the desktop app first so it can't respawn ollama.exe, then the server.
    for image in ("ollama app.exe", "ollama.exe"):
        try:
            if _run(["taskkill", "/F", "/T", "/IM", image]).returncode == 0:
                killed_any = True
        except Exception:
            pass
    time.sleep(1)
    if ollama_running():
        return False, "ollama still running after kill"
    return True, "stopped" if killed_any else "already stopped"
