"""The replays folder: the battle file the game writes is where the player list comes from."""
import os
import pathlib


def replay_folder(cfg):
    """config live_replay.folder, else <game folder>/replays, else None."""
    folder = cfg.get("live_replay", {}).get("folder")
    if folder:
        return folder
    return str(pathlib.Path(cfg["game_dir"]) / "replays") if cfg.get("game_dir") else None


def find_battle_file(folder):
    """The replay being written during a battle (temp*.wowsreplay, not empty), or None between battles.

    os.stat, not DirEntry.stat(): the size the directory listing reports for a file the game holds open
    for writing lags behind."""
    if not folder:
        return None
    try:
        temps = [e.path for e in os.scandir(folder)
                 if e.is_file() and e.name.lower().startswith("temp") and e.name.endswith(".wowsreplay")]
    except OSError:
        return None
    found = []
    for path in temps:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if stat.st_size > 0:            # between battles the client empties it
            found.append((stat.st_mtime, path))
    return pathlib.Path(max(found)[1]) if found else None
