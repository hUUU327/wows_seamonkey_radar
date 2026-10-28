"""Find the World of Warships install, whose replays folder the program follows.

In order: the folder chosen in the program, config.json game_dir, the running game, Windows' installed
programs, Steam library folders, then common folders on every drive. A folder counts when it holds
WorldOfWarships.exe; with several installs the one played last wins.
"""
import ctypes
import os
import pathlib
import re
import string
import winreg
from ctypes import wintypes

GAME_EXE = "WorldOfWarships.exe"
STEAM_APP = "World of Warships"


def is_game_dir(path):
    try:
        return bool(path) and (pathlib.Path(path) / GAME_EXE).is_file()
    except OSError:
        return False


def _game_root(exe_path):
    """Game root of a running client exe (…/bin/<build>/bin64/WorldOfWarships64.exe)."""
    for parent in list(pathlib.Path(exe_path).parents)[:5]:
        if is_game_dir(parent):
            return parent
    return None


def running_game_dir():
    """Install folder of a running game client, or None."""
    psapi, kernel32 = ctypes.windll.psapi, ctypes.windll.kernel32
    pids = (wintypes.DWORD * 4096)()
    count = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(count)):
        return None
    buf = ctypes.create_unicode_buffer(1024)
    for pid in pids[:count.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
                if name.startswith("worldofwarships") and name.endswith(".exe"):
                    root = _game_root(buf.value)
                    if root:
                        return root
        finally:
            kernel32.CloseHandle(handle)
    return None


def _registry_installs():
    """InstallLocation of every uninstall entry that mentions the game."""
    found = []
    for hive, view in ((winreg.HKEY_CURRENT_USER, 0), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                       (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)):
        try:
            base = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0,
                                  winreg.KEY_READ | view)
        except OSError:
            continue
        with base:
            for i in range(10000):
                try:
                    name = winreg.EnumKey(base, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(base, name) as key:
                        display = str(winreg.QueryValueEx(key, "DisplayName")[0])
                        if "world of warships" in display.lower():
                            found.append(str(winreg.QueryValueEx(key, "InstallLocation")[0]).strip('" '))
                except OSError:
                    continue
    return found


def _steam_installs():
    """…/steamapps/common/World of Warships for the Steam folder and every library folder."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = pathlib.Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return []
    libraries = [steam]
    try:
        vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="ignore")
        libraries += [pathlib.Path(m.replace("\\\\", "\\")) for m in re.findall(r'"path"\s+"([^"]+)"', vdf)]
    except OSError:
        pass
    return [str(library / "steamapps" / "common" / STEAM_APP) for library in libraries]


def _common_installs():
    """Folders on every drive whose name looks like the game."""
    found = []
    for drive in (f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")):
        for parent in (drive, os.path.join(drive, "Games"),
                       os.path.join(drive, "Program Files (x86)", "Steam", "steamapps", "common"),
                       os.path.join(drive, "SteamLibrary", "steamapps", "common")):
            try:
                for entry in os.scandir(parent):
                    if entry.is_dir() and ("world_of_warships" in entry.name.lower() or entry.name == STEAM_APP):
                        found.append(entry.path)
            except OSError:
                continue
    return found


def _last_played(path):
    try:
        return os.stat(pathlib.Path(path) / "replays").st_mtime
    except OSError:
        return 0.0


def find_game_dir(cfg, chosen=None):
    """(folder, how it was found) or (None, None)."""
    for path, how in ((chosen, "chosen"), (cfg.get("game_dir"), "config")):
        if is_game_dir(path):
            return pathlib.Path(path), how
    running = running_game_dir()
    if running:
        return running, "running game"
    found = []
    for how, getter in (("installed programs", _registry_installs), ("Steam", _steam_installs),
                        ("common folders", _common_installs)):
        try:
            found += [(path, how) for path in getter() if is_game_dir(path)]
        except Exception:               # noqa: BLE001 - a broken registry entry must not stop the search
            continue
    if not found:
        return None, None
    path, how = max(found, key=lambda item: _last_played(item[0]))
    return pathlib.Path(path), how
