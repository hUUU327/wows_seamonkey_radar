"""Screen capture through DXGI Desktop Duplication (dxcam), read-only.

grab() returns the newest frame in the 1920x1080 layout (screen.py); game_in_front() tells whether the
game owns the foreground window, i.e. whether the team list on screen is its own.
"""
import ctypes
import threading
import time


class Capturer:
    def __init__(self, geometry=None):
        """geometry: screen.ScreenGeometry. Reads the primary monitor until retarget() moves it."""
        import dxcam
        self.cam = dxcam.create(output_color="BGR")
        self.geometry = geometry
        self.lock = threading.Lock()

    def retarget(self, device_idx, output_idx, geometry):
        """Read another monitor (the game was started on it)."""
        import dxcam
        with self.lock:
            new = dxcam.create(device_idx=device_idx, output_idx=output_idx, output_color="BGR")
            if new is not self.cam:
                try:
                    self.cam.release()
                except Exception:       # noqa: BLE001 - an old camera that cannot be released is harmless
                    pass
                self.cam = new
            self.geometry = geometry

    def grab(self, timeout=0.2):
        """The next new frame, or None when the desktop did not change within timeout."""
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            with self.lock:
                img = self.cam.grab()
            if img is not None:
                if self.geometry is not None:
                    img = self.geometry.normalize(img)
                return time.perf_counter(), img
            time.sleep(0.001)
        return None


def _key_down(vk):
    """Is the key held right now? (GetAsyncKeyState: reads the state, installs no hook)"""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _mouse_clicked():
    """A mouse button held now, or pressed since the last check (a click shorter than one pass counts)."""
    get = ctypes.windll.user32.GetAsyncKeyState
    return any(get(vk) & 0x8001 for vk in (0x01, 0x02, 0x04))       # left, right, middle


def _foreground_title():
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    size = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(size + 1)
    user32.GetWindowTextW(hwnd, buf, size + 1)
    return buf.value


def _foreground_exe():
    """File name of the program owning the foreground window (WorldOfWarships64.exe)."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.replace("/", "\\").split("\\")[-1]
        return ""
    finally:
        kernel32.CloseHandle(handle)


def game_in_front(cfg):
    """Is the game's window in the foreground? (only it draws the Tab team list)"""
    trigger = cfg.get("trigger", {})
    title = trigger.get("window_title", "World of Warships")
    exe = trigger.get("game_exe", "WorldOfWarships")
    try:
        return exe.lower() in _foreground_exe().lower() or title.lower() in _foreground_title().lower()
    except Exception:                   # noqa: BLE001 - an unreadable window must not stop the loop
        return True
