"""Which monitor the game is on: the capture follows it and the overlay is laid out for its size.

Everything here is in physical pixels (the program is per-monitor DPI aware through Qt).
"""
import ctypes
import os
from ctypes import wintypes

user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
MIN_AREA = 300 * 300           # smaller windows (launcher, dialogs) are not the game


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def game_window():
    """Handle of the game's biggest visible window, or None."""
    found = []
    buf = ctypes.create_unicode_buffer(1024)
    enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return True
        try:
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                if os.path.basename(buf.value).lower().startswith("worldofwarships"):
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    area = (rect.right - rect.left) * (rect.bottom - rect.top)
                    if area >= MIN_AREA:
                        found.append((area, hwnd))
        finally:
            kernel32.CloseHandle(handle)
        return True

    user32.EnumWindows(enum(visit), 0)
    return max(found)[1] if found else None


def monitor_rect(hwnd):
    """(left, top, right, bottom) of the monitor the window is mostly on, or None."""
    mon = user32.MonitorFromWindow(hwnd, 2)         # MONITOR_DEFAULTTONEAREST
    if not mon:
        return None
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        return None
    rect = info.rcMonitor
    return rect.left, rect.top, rect.right, rect.bottom


def game_monitor():
    """The rectangle of the monitor the game is on, or None when it is not running."""
    try:
        hwnd = game_window()
        return monitor_rect(hwnd) if hwnd else None
    except Exception:                   # noqa: BLE001 - never stop the program for this
        return None


def dxcam_output(rect):
    """(device index, output index) of the dxcam output covering `rect`; the first one if none does."""
    try:
        import dxcam
        for device, outputs in enumerate(dxcam.__factory.outputs):
            for index, output in enumerate(outputs):
                output.update_desc()
                coords = output.desc.DesktopCoordinates
                if (coords.left, coords.top, coords.right, coords.bottom) == tuple(rect):
                    return device, index
    except Exception:                   # noqa: BLE001 - fall back to the primary output
        pass
    return 0, 0


def pick_screen(app, rect):
    """The Qt screen of the monitor `rect`: same physical size, then the nearest left edge."""
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    alike = [s for s in app.screens()
             if round(s.geometry().width() * s.devicePixelRatio()) == width
             and round(s.geometry().height() * s.devicePixelRatio()) == height]
    if not alike:
        return None
    return min(alike, key=lambda s: abs(s.geometry().left() * s.devicePixelRatio() - rect[0]))
