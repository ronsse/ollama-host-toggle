"""Launch-at-login control — create/remove a Startup-folder shortcut.

No extra dependencies: the .lnk is created via the Windows Script Host COM object
through a short PowerShell call. Works both for the script (pythonw -m ...) and a
PyInstaller-frozen exe.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import APP_NAME

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def shortcut_path() -> Path:
    startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup / f"{APP_NAME}.lnk"


def _target() -> tuple[str, str, str]:
    """Return (target_exe, arguments, working_dir) for the shortcut."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return exe, "", str(Path(exe).parent)
    # Running as a module: launch windowless via pythonw -m <package>.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    pkg_parent = Path(__file__).resolve().parent.parent
    return exe, f"-m {__package__}", str(pkg_parent)


def is_enabled() -> bool:
    try:
        return shortcut_path().exists()
    except Exception:
        return False


def enable() -> bool:
    target, args, workdir = _target()
    lnk = shortcut_path()
    ps = (
        "$ErrorActionPreference='Stop';"
        "$ws=New-Object -ComObject WScript.Shell;"
        f"$sc=$ws.CreateShortcut('{lnk}');"
        f"$sc.TargetPath='{target}';"
        f"$sc.Arguments='{args}';"
        f"$sc.WorkingDirectory='{workdir}';"
        "$sc.WindowStyle=7;"
        f"$sc.Description='{APP_NAME}';"
        "$sc.Save()"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=20,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.returncode == 0 and lnk.exists()
    except Exception:
        return False


def disable() -> bool:
    try:
        shortcut_path().unlink(missing_ok=True)
        return True
    except Exception:
        return False


def toggle() -> bool:
    """Flip the state; return the new enabled state."""
    if is_enabled():
        disable()
    else:
        enable()
    return is_enabled()
