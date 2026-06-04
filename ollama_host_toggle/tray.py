"""System-tray UI (pystray + Pillow).

Color-coded Cyberdyne-style icon, live tooltip, a right-click menu (hosting
controls + Start-at-login toggle + Settings/About line), and a background poll
that fires a desktop notification whenever hosting state changes — whether the
change came from the tray or from the hub over HTTP.
"""

from __future__ import annotations

import math
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

from . import APP_NAME, __version__, actions, autostart, scheduler
from .config import Config

# Status colors
_GREEN = (46, 204, 113)   # serving + model loaded
_AMBER = (241, 196, 15)   # serving but idle
_GREY = (127, 140, 141)   # not serving

# Cyberdyne-style tri-segment triangle geometry.
_TWIST_DEG = 16.0
_HOLE_SCALE = 0.40
_GAP_FRAC = 0.07


def _make_icon(color: tuple[int, int, int], size: int = 64) -> Image.Image:
    """Cyberdyne-style triangle of three blades around a central hole, status-tinted.
    Drawn at 4x and downsampled for crisp edges."""
    ss = 4
    s = size * ss
    cx = cy = s / 2
    R = s * 0.46
    tw = math.radians(_TWIST_DEG)
    angs = [math.radians(90), math.radians(210), math.radians(330)]

    def pt(r: float, a: float) -> tuple[float, float]:
        return (cx + r * math.cos(a), cy - r * math.sin(a))

    verts = [pt(R, a) for a in angs]
    hole = [pt(R * _HOLE_SCALE, a + tw) for a in angs]

    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    md.polygon(verts, fill=255)
    md.polygon(hole, fill=0)
    gap = max(1, round(s * _GAP_FRAC))
    for v, h in zip(verts, hole):
        md.line([v, h], fill=0, width=gap)

    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    solid = Image.new("RGBA", (s, s), color + (255,))
    return Image.composite(solid, canvas, mask).resize((size, size), Image.LANCZOS)


def _signature(state: dict) -> tuple:
    return (bool(state.get("serving")), tuple(sorted(state.get("loadedModels") or [])))


class TrayApp:
    def __init__(self, cfg: Config, on_quit=None):
        self.cfg = cfg
        self._on_quit = on_quit
        self._state: dict = {}
        self._prev_sig: tuple | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.icon = pystray.Icon(
            APP_NAME,
            icon=_make_icon(_GREY),
            title=f"{cfg.host_label}: …",
            menu=self._build_menu(),
        )

    # --- rendering ---------------------------------------------------------
    def _color_for(self, state: dict) -> tuple[int, int, int]:
        if not state.get("serving"):
            return _GREY
        return _GREEN if state.get("loadedModels") else _AMBER

    def _tooltip_for(self, state: dict) -> str:
        host = self.cfg.host_label
        if not state.get("serving"):
            return f"{host}: OFF"
        models = state.get("loadedModels") or []
        model = models[0] if models else "idle"
        used, total = state.get("vramUsedMB"), state.get("vramTotalMB")
        if used is not None and total is not None:
            return f"{host}: ON · {model} · {used / 1024:.1f}/{total / 1024:.1f} GB"
        return f"{host}: ON · {model}"

    def _notify_transition(self, prev: tuple | None, state: dict) -> None:
        if prev is None:
            return  # first poll establishes baseline, no toast
        sig = _signature(state)
        if sig == prev:
            return
        serving, models = sig
        if not serving:
            msg = "Hosting OFF · GPU freed"
        elif models:
            used = state.get("vramUsedMB")
            vram = f" ({used / 1024:.1f} GB)" if used is not None else ""
            msg = f"Hosting ON · {models[0]} loaded{vram}"
        else:
            msg = "Hosting ON · idle (no model loaded)"
        try:
            self.icon.notify(msg, APP_NAME)
        except Exception:
            pass

    def _refresh(self, _icon=None, _item=None) -> None:
        with self._lock:
            state = actions.get_state(self.cfg)
            self._notify_transition(self._prev_sig, state)
            self._prev_sig = _signature(state)
            self._state = state
            self.icon.icon = _make_icon(self._color_for(state))
            self.icon.title = self._tooltip_for(state)
            self.icon.menu = self._build_menu()

    # --- actions -----------------------------------------------------------
    def _start_with(self, model: str):
        def handler(_icon=None, _item=None):
            ok, _ = actions.start_serving(self.cfg)
            if ok and model:
                actions.preload(self.cfg, model)
            self._refresh()
        return handler

    def _stop(self, _icon=None, _item=None):
        actions.stop_serving(self.cfg)
        self._refresh()

    def _unload(self, _icon=None, _item=None):
        models = self._state.get("loadedModels") or []
        if models:
            actions.unload(self.cfg, models[0])
        self._refresh()

    def _toggle_autostart(self, _icon=None, _item=None):
        autostart.toggle()
        self.icon.menu = self._build_menu()

    def _open_hub(self, _icon=None, _item=None):
        if self.cfg.hub_status_url:
            webbrowser.open(self.cfg.hub_status_url)

    def _quit(self, _icon=None, _item=None):
        self._stop.set()
        if self._on_quit:
            self._on_quit()
        self.icon.stop()

    # --- menu --------------------------------------------------------------
    def _settings_line(self) -> str:
        tok = "✓" if self.cfg.auth_token else "✗ no token"
        return f"v{__version__} · {self.cfg.http_bind}:{self.cfg.http_port} · token {tok}"

    def _build_menu(self) -> pystray.Menu:
        serving = self._state.get("serving", False)
        loaded = set(self._state.get("loadedModels") or [])

        start_items = [
            pystray.MenuItem(
                m, self._start_with(m),
                checked=(lambda mm: lambda _i: mm in loaded)(m),
            )
            for m in self.cfg.models
        ]

        items = [
            pystray.MenuItem("Start hosting", pystray.Menu(*start_items)),
            pystray.MenuItem("Stop hosting", self._stop, enabled=serving),
            pystray.MenuItem("Unload model", self._unload, enabled=bool(loaded)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Refresh status", self._refresh),
            pystray.MenuItem(
                "Start at login", self._toggle_autostart,
                checked=lambda _i: autostart.is_enabled(),
            ),
        ]
        if self.cfg.hub_status_url:
            items.append(pystray.MenuItem("Open hub status", self._open_hub))
        items += [pystray.Menu.SEPARATOR]
        sched = scheduler.describe(self.cfg)
        if sched:
            items.append(pystray.MenuItem(f"Schedule: {sched}", None, enabled=False))
        items += [
            pystray.MenuItem(self._settings_line(), None, enabled=False),
            pystray.MenuItem("Quit", self._quit),
        ]
        return pystray.Menu(*items)

    # --- poll loop ---------------------------------------------------------
    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._refresh()
            if self._stop.wait(self.cfg.poll_interval):
                break

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, name="oht-poll", daemon=True).start()
        self.icon.run()
