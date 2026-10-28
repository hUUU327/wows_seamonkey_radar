"""Ship names from the local game client, kept current by the program.

The team list shows each player's ship, so the rows are matched by name; the client's GameParams and
language file give those names. After a game update the list is rebuilt into DATA/gamedata, which
paths.data_file() prefers over the bundled copy. A build that failed is not retried until the client
changes.
"""
import datetime
import json
import os

from . import paths
from .gamefiles import client_texts, latest_build, load_game_params

REGION = "ASIA"
SKIP_GROUPS = {"disabled", "preserved", "unavailable", "event"}
FORMAT = 2                          # layout of the data files


def build(game_dir, lang="zh_sg"):
    """The ships from the client in game_dir: [{"ship_id", "name"}]."""
    params = load_game_params(game_dir)[REGION]
    names = client_texts(game_dir, lang)
    ships = []
    for ship in params.values():
        typeinfo = getattr(getattr(ship, "typeinfo", None), "__dict__", {})
        if typeinfo.get("type") != "Ship" or typeinfo.get("species") == "Auxiliary" or ship.group in SKIP_GROUPS:
            continue
        key = f"IDS_{ship.index}"
        if key not in names:
            continue
        ships.append({"ship_id": ship.id, "name": names[key]})
    ships.sort(key=lambda ship: ship["ship_id"])
    return ships


def write(folder, ships, build_id):
    """ships.json and meta.json in folder, each replaced in one step."""
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"build": build_id, "format": FORMAT,
            "generated": datetime.datetime.now().isoformat(timespec="seconds")}
    for name, value in (("ships.json", ships), ("meta.json", meta)):
        tmp = folder / (name + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, folder / name)


def update_if_needed(game_dir, say=print):
    """Rebuild the list when the client's build differs from the one in use.

    True when new data was written (the caller reloads it), False when nothing changed or it failed
    (the old data stays)."""
    try:
        build_id = latest_build(game_dir).name
    except OSError:
        return False
    meta = paths.data_meta()
    have = meta.get("build") if meta.get("format") == FORMAT else None
    if have == build_id or paths.generated_meta().get("failed") == build_id:
        return False
    say(f"游戏已更新（{build_id}），正在更新船只数据…")
    try:
        ships = build(game_dir)
        if len(ships) < 100:
            raise ValueError(f"only {len(ships)} ships found")
    except Exception as error:          # noqa: BLE001 - the client format may change; keep what we have
        say(f"船只数据更新失败，继续使用旧数据（{error!r}）")
        try:
            paths.GENERATED.mkdir(parents=True, exist_ok=True)
            (paths.GENERATED / "meta.json").write_text(
                json.dumps({**paths.generated_meta(), "failed": build_id}), encoding="utf-8")
        except OSError:
            pass
        return False
    write(paths.GENERATED, ships, build_id)
    say(f"船只数据已更新：{len(ships)} 艘船")
    return True
