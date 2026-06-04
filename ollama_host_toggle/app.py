"""Entry point — single-instance guard, HTTP API, and tray UI."""

from __future__ import annotations

import ctypes
import sys
import threading

from . import APP_NAME, config, http_api, scheduler
from .tray import TrayApp

_MUTEX_NAME = "Global\\ollama-host-toggle-singleton"
_ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance():
    """Return a mutex handle, or None if another instance already holds it."""
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            return None
        return handle
    except Exception:
        # Non-Windows or API failure: don't block startup.
        return True


def main() -> None:
    mutex = _acquire_single_instance()
    if mutex is None:
        # Already running — exit quietly.
        sys.exit(0)

    cfg = config.load()

    try:
        httpd = http_api.serve(cfg)
    except OSError:
        # Tailnet IP not up yet, port in use, etc. — run tray-only.
        httpd = None

    def on_quit() -> None:
        if httpd is not None:
            httpd.shutdown()

    app = TrayApp(cfg, on_quit=on_quit)

    # Scheduled on/off (no-op if config has no [[schedule]] rules).
    if cfg.schedule:
        threading.Thread(
            target=scheduler.run, args=(cfg,), kwargs={"refresh": app._refresh},
            name="oht-sched", daemon=True,
        ).start()

    if cfg.first_run:
        # Greet once the tray icon is up (timer fires after .run() starts the loop).
        def _greet() -> None:
            try:
                app.icon.notify(
                    f"Ready. Config + token written to config.toml. "
                    f"API on {cfg.http_bind}:{cfg.http_port}.",
                    APP_NAME,
                )
            except Exception:
                pass
        threading.Timer(2.0, _greet).start()

    app.run()


if __name__ == "__main__":
    main()
