"""Configuration loading + first-run setup.

Generic by default: the host label is the machine's own hostname, the Ollama path
comes from %LOCALAPPDATA%, and the HTTP bind auto-detects a Tailscale IP. Nothing
machine-specific is baked in — ``config.toml`` overrides anything.

On first run (no ``config.toml``), one is created automatically with a freshly
generated ``auth_token`` and the detected tailnet IP, so a clone-and-run just works.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _default_ollama_path() -> str:
    base = os.environ.get("LOCALAPPDATA", "")
    return str(Path(base) / "Programs" / "Ollama" / "ollama app.exe")


def detect_tailscale_ip() -> str | None:
    """Best-effort: return this node's Tailscale IPv4 (100.64.0.0/10), else None."""
    # Preferred: the tailscale CLI.
    for exe in (
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        "tailscale",
    ):
        try:
            out = subprocess.run(
                [exe, "ip", "-4"],
                capture_output=True, text=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW,
            ).stdout
            for line in out.splitlines():
                ip = line.strip()
                if ip.startswith("100."):
                    return ip
        except Exception:
            continue
    # Fallback: scan local interface addresses for the CGNAT range.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("100."):
                return ip
    except Exception:
        pass
    return None


DEFAULTS: dict = {
    "ollama_app_path": _default_ollama_path(),
    "ollama_url": "http://localhost:11434",
    "models": ["qwen2.5:14b", "qwen2.5-coder:14b"],
    "default_preload": "qwen2.5:14b",
    "host_label": socket.gethostname().lower(),
    "http_bind": "127.0.0.1",   # safe default; first-run upgrades to the tailnet IP
    "http_port": 11435,
    "auth_token": "",
    "poll_interval": 8,
    "hub_status_url": "",
    "nvidia_smi_path": r"C:\Windows\System32\nvidia-smi.exe",
    "schedule": [],   # list of {at:"HH:MM", action:"on"|"off", days?:[...], preload?:"..."}
}


@dataclass
class Config:
    ollama_app_path: str
    ollama_url: str
    models: list[str]
    default_preload: str
    host_label: str
    http_bind: str
    http_port: int
    auth_token: str
    poll_interval: int
    hub_status_url: str
    nvidia_smi_path: str
    schedule: list = field(default_factory=list)
    source: Path | None = field(default=None)
    first_run: bool = field(default=False)

    @property
    def version_url(self) -> str:
        return f"{self.ollama_url.rstrip('/')}/api/version"

    @property
    def ps_url(self) -> str:
        return f"{self.ollama_url.rstrip('/')}/api/ps"

    @property
    def generate_url(self) -> str:
        return f"{self.ollama_url.rstrip('/')}/api/generate"


def _render_config(token: str, bind: str) -> str:
    models = ", ".join(f'"{m}"' for m in DEFAULTS["models"])
    return f"""# ollama-host-toggle configuration (auto-created on first run).
# This file holds your auth_token and is gitignored. The OMEN_AGENT_TOKEN /
# OLLAMA_HOST_TOGGLE_TOKEN env var, if set, overrides auth_token below.

# Path to Ollama's launcher (starts the server).
ollama_app_path = '{DEFAULTS["ollama_app_path"]}'

# Local Ollama API base.
ollama_url = "http://localhost:11434"

# Models offered in the tray "Start hosting" submenu.
models = [{models}]

# Model preloaded by /host/on and the default tray start (set "" for none).
default_preload = "{DEFAULTS["default_preload"]}"

# Label reported in /state (defaults to this machine's hostname).
host_label = "{DEFAULTS["host_label"]}"

# HTTP control API. Bound to the tailnet IP so it's reachable only over your
# tailnet. Do NOT set 0.0.0.0 unless you really mean to expose it.
http_bind = "{bind}"
http_port = 11435

# Shared secret for the HTTP API (clients send: Authorization: Bearer <token>).
auth_token = "{token}"

# Tray background poll interval (seconds).
poll_interval = 8

# "Open hub status" menu target (leave empty to hide the menu item).
hub_status_url = ""

# nvidia-smi location (for VRAM readout).
nvidia_smi_path = '{DEFAULTS["nvidia_smi_path"]}'

# Scheduled host on/off (optional). Each rule fires at local time "HH:MM".
# action = "on" (start serving, preload `preload` or default_preload) or "off".
# days (optional): subset of mon,tue,wed,thu,fri,sat,sun — or "daily"/"weekdays"/"weekends".
# Example: serve weekday mornings, free the GPU every night for gaming.
# [[schedule]]
# at = "08:00"
# action = "on"
# days = "weekdays"
# preload = "{DEFAULTS["default_preload"]}"
#
# [[schedule]]
# at = "23:30"
# action = "off"
"""


def create_default_config(path: Path) -> str:
    """Write a fresh config.toml with a generated token + detected tailnet IP.

    Returns the generated token.
    """
    token = secrets.token_urlsafe(32)
    bind = detect_tailscale_ip() or "127.0.0.1"
    path.write_text(_render_config(token, bind), encoding="utf-8")
    return token


def _token_env() -> str | None:
    return os.environ.get("OLLAMA_HOST_TOGGLE_TOKEN") or os.environ.get("OMEN_AGENT_TOKEN")


def load(path: str | os.PathLike | None = None) -> Config:
    """Load config, creating a default one on first run if none exists."""
    cfg_path = Path(path) if path else ROOT / "config.toml"
    first_run = False

    if not cfg_path.is_file():
        create_default_config(cfg_path)
        first_run = True

    data = dict(DEFAULTS)
    with cfg_path.open("rb") as fh:
        data.update(tomllib.load(fh))

    env_token = _token_env()
    if env_token:
        data["auth_token"] = env_token

    known = {f for f in Config.__dataclass_fields__ if f not in ("source", "first_run")}
    filtered = {k: v for k, v in data.items() if k in known}
    return Config(source=cfg_path, first_run=first_run, **filtered)
