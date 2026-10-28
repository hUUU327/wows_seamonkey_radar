"""Where the program's files are, from source and in the packaged exe.

APP_DIR  config.json next to the exe (from source: the project root)
DATA     settings and logs: data/ next to the exe, from source local/data; if that is not writable,
         %LOCALAPPDATA%\\wowsyukarinano\\data
ASSETS   pictures, fonts and the bundled fallbacks (ship list, default config); from source
         local/assets
"""
import os
import pathlib
import sys

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    APP_DIR = pathlib.Path(sys.executable).resolve().parent
    ASSETS = pathlib.Path(getattr(sys, "_MEIPASS", APP_DIR)) / "assets"
else:
    APP_DIR = pathlib.Path(__file__).resolve().parents[1]
    ASSETS = APP_DIR / "local" / "assets"


def _writable(folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


DATA = APP_DIR / "data" if FROZEN else APP_DIR / "local" / "data"
if not _writable(DATA):
    DATA = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "wowsyukarinano" / "data"
    DATA.mkdir(parents=True, exist_ok=True)

CONFIG = APP_DIR / "config.json"
DEFAULT_CONFIG = ASSETS / "config.default.json"
GENERATED = DATA / "gamedata"          # ship names rebuilt from the client (shipdata.py)


def data_file(name):
    """ships.json / meta.json as they should be read now: the copy the program rebuilt itself, else the
    one next to the exe, else the bundled one."""
    for folder in (GENERATED, APP_DIR / "data", ASSETS):
        if (folder / name).exists():
            return folder / name
    return ASSETS / name


def _meta(folder):
    try:
        import json
        return json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def data_meta():
    """meta.json of the data in use (its client build), {} if it has none."""
    folder = data_file("ships.json").parent
    return _meta(folder) or (_meta(ASSETS) if folder != GENERATED else {})


def generated_meta():
    return _meta(GENERATED)


def rotate(path, max_bytes):
    """Past max_bytes a log becomes <name>.old (the previous .old is dropped)."""
    try:
        if path.stat().st_size > max_bytes:
            os.replace(path, path.with_name(path.stem + ".old" + path.suffix))
    except OSError:
        pass
