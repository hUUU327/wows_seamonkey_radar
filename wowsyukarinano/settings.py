"""Per-user state kept between runs (settings.json in the data folder, not config.json).

Writes are atomic and a read that fails keeps the last good copy, so a half-written file can never wipe
the saved choices."""
import json
import os
import threading

from .paths import DATA

PATH = DATA / "settings.json"
_lock = threading.Lock()
_last = {}


def _read():
    return json.loads(PATH.read_text(encoding="utf-8"))


def load():
    global _last
    with _lock:
        try:
            _last = _read()
        except (OSError, ValueError):
            pass                        # unreadable right now: the last good copy stands
        return dict(_last)


def save(**changes):
    global _last
    with _lock:
        try:
            _last = _read()
        except (OSError, ValueError):
            pass
        values = dict(_last)
        values.update(changes)
        _last = values
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = PATH.with_name(PATH.name + ".tmp")
            tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, PATH)
        except OSError:
            pass
        return dict(values)
