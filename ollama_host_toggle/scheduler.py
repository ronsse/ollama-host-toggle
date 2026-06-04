"""Scheduled host on/off.

A tiny minute-granularity scheduler. Each rule is a dict from config:
    {at:"HH:MM", action:"on"|"off", days?:[...]|str, preload?:"model"}
Fires the matching action once per matching minute (deduped), in local time.
"""

from __future__ import annotations

import threading
from datetime import datetime

from . import actions
from .config import Config

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_GROUPS = {
    "daily": set(range(7)),
    "all": set(range(7)),
    "everyday": set(range(7)),
    "weekday": {0, 1, 2, 3, 4},
    "weekdays": {0, 1, 2, 3, 4},
    "weekend": {5, 6},
    "weekends": {5, 6},
}


def _rule_days(rule: dict) -> set[int]:
    days = rule.get("days")
    if not days:
        return set(range(7))
    if isinstance(days, str):
        return _GROUPS.get(days.lower().strip(), set(range(7)))
    out: set[int] = set()
    for d in days:
        key = str(d).lower().strip()[:3]
        if key in _DAYS:
            out.add(_DAYS.index(key))
        elif key in _GROUPS:
            out |= _GROUPS[key]
    return out or set(range(7))


def _parse_at(rule: dict) -> tuple[int, int] | None:
    try:
        hh, mm = str(rule["at"]).strip().split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except Exception:
        pass
    return None


def _fire(cfg: Config, rule: dict) -> None:
    action = str(rule.get("action", "")).lower()
    if action == "on":
        ok, _ = actions.start_serving(cfg)
        model = rule.get("preload", cfg.default_preload)
        if ok and model:
            actions.preload(cfg, model)
    elif action == "off":
        actions.stop_serving(cfg)


def describe(cfg: Config) -> str | None:
    """One-line summary for the tray menu, or None if no rules."""
    parts = []
    for rule in cfg.schedule or []:
        at = _parse_at(rule)
        if at:
            parts.append(f"{at[0]:02d}:{at[1]:02d} {str(rule.get('action','?')).lower()}")
    return " · ".join(parts) if parts else None


def run(cfg: Config, refresh=None, stop: threading.Event | None = None) -> None:
    """Background loop: check every ~20s, fire rules on their minute."""
    rules = cfg.schedule or []
    if not rules:
        return
    last: dict[int, tuple] = {}
    stop = stop or threading.Event()
    while not stop.is_set():
        now = datetime.now()
        stamp = (now.year, now.timetuple().tm_yday, now.hour, now.minute)
        for i, rule in enumerate(rules):
            at = _parse_at(rule)
            if not at:
                continue
            if now.hour == at[0] and now.minute == at[1] and now.weekday() in _rule_days(rule):
                if last.get(i) != stamp:
                    last[i] = stamp
                    _fire(cfg, rule)
                    if refresh:
                        try:
                            refresh()
                        except Exception:
                            pass
        stop.wait(20)
