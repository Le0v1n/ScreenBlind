"""
Windows DPI handling.

Qt reports screen geometry in *logical* (device-independent) pixels. The Win32
calls this app relies on — SetWindowPos, ClipCursor, GetCursorPos — all speak
*physical* pixels. The two only agree at 100% scaling: on a 2560x1440 monitor
scaled to 150%, Qt says 1707x960 while Windows says 2560x1440.

Feeding Qt's numbers to those Win32 calls is what made blinds cover only part
of a scaled monitor and left the cursor clip in the wrong place — the bug the
"Override high DPI scaling behavior -> System (Enhanced)" compatibility hack
used to paper over. Everything in this module exists to translate between the
two spaces so that hack is no longer needed.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from PyQt6.QtCore import QRect

_u32 = ctypes.windll.user32

MONITOR_DEFAULTTONEAREST = 2
_MDT_EFFECTIVE_DPI = 0

# Per-Monitor V2 keeps every monitor's true pixel grid visible to the process
# and makes Windows send WM_DPICHANGED rather than silently virtualising
# coordinates behind our back.
_DPI_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_PROCESS_PER_MONITOR_DPI_AWARE = 2


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize",     wt.DWORD),
        ("rcMonitor",  wt.RECT),
        ("rcWork",     wt.RECT),
        ("dwFlags",    wt.DWORD),
        ("szDevice",   ctypes.c_wchar * 32),
    ]


_MonitorEnumProc = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,               # HMONITOR
    ctypes.c_void_p,               # HDC
    ctypes.POINTER(wt.RECT),       # LPRECT
    wt.LPARAM,
)

# Explicit signatures so 64-bit handles survive the round trip
_u32.MonitorFromWindow.restype    = ctypes.c_void_p
_u32.MonitorFromWindow.argtypes   = [ctypes.c_void_p, ctypes.c_uint]
_u32.GetMonitorInfoW.restype      = ctypes.c_bool
_u32.GetMonitorInfoW.argtypes     = [ctypes.c_void_p, ctypes.c_void_p]
_u32.EnumDisplayMonitors.restype  = ctypes.c_bool
_u32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     _MonitorEnumProc, wt.LPARAM]


# ---------------------------------------------------------------------------
# Process awareness
# ---------------------------------------------------------------------------

def enable_dpi_awareness() -> str:
    """
    Opt the process into Per-Monitor V2 DPI awareness.

    Must run before QApplication is constructed. Qt would eventually request
    per-monitor awareness itself, but doing it here means the very first window
    Windows sees is already unvirtualised, and it keeps the app correct even if
    the toolkit's default ever changes.

    Returns the mode actually applied, for diagnostics.
    """
    # The frozen build declares Per-Monitor V2 in its manifest, which Windows
    # applies before we get a say — and locks, so the calls below would fail.
    if current_awareness() == 2:
        return "already-per-monitor"

    try:
        _u32.SetProcessDpiAwarenessContext.restype  = ctypes.c_bool
        _u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if _u32.SetProcessDpiAwarenessContext(_DPI_CONTEXT_PER_MONITOR_AWARE_V2):
            return "per-monitor-v2"
    except Exception:
        pass

    # Windows 8.1 / early Windows 10
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(
            _PROCESS_PER_MONITOR_DPI_AWARE
        ) == 0:
            return "per-monitor"
    except Exception:
        pass

    # Last resort: system-wide awareness is still far better than unaware
    try:
        if _u32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass

    # Already locked in by an embedded manifest or a Compatibility-tab
    # override — nothing more we can do from here.
    return "unchanged"


def current_awareness() -> int:
    """0 = unaware, 1 = system, 2 = per-monitor. -1 if unknown."""
    try:
        v = ctypes.c_int()
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(v))
        return v.value
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Physical geometry
# ---------------------------------------------------------------------------

def _rect_of(hmonitor) -> tuple[QRect, str, int] | None:
    mi = _MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(_MONITORINFOEXW)
    if not _u32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
        return None
    r = mi.rcMonitor
    rect = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)

    dpi_x = ctypes.c_uint(96)
    try:
        ctypes.windll.shcore.GetDpiForMonitor(
            hmonitor, _MDT_EFFECTIVE_DPI,
            ctypes.byref(dpi_x), ctypes.byref(ctypes.c_uint()),
        )
    except Exception:
        pass
    return rect, mi.szDevice, dpi_x.value


def monitor_rect_for_hwnd(hwnd: int) -> QRect | None:
    """
    True physical bounds of the monitor a window sits on.

    This is the authoritative path: no guesswork mapping Qt screens onto Win32
    monitors, just ask Windows which monitor owns the window we already made.
    """
    try:
        hmon = _u32.MonitorFromWindow(ctypes.c_void_p(hwnd), MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return None
        info = _rect_of(ctypes.c_void_p(hmon))
        return info[0] if info else None
    except Exception:
        return None


def physical_monitors() -> list[dict]:
    """Every monitor's physical rect + DPI, ordered left-to-right, top-to-bottom."""
    found: list[dict] = []

    def _cb(hmon, _hdc, _lprc, _data):
        info = _rect_of(ctypes.c_void_p(hmon))
        if info:
            rect, device, dpi = info
            found.append({"rect": rect, "device": device, "dpi": dpi})
        return 1

    try:
        _u32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_cb), 0)
    except Exception:
        return []
    found.sort(key=lambda m: (m["rect"].x(), m["rect"].y()))
    return found


def native_geometry(screen) -> QRect:
    """
    Physical pixel bounds of a QScreen.

    Pairs Qt's screen list against the Win32 monitor list by desktop position —
    both describe the same monitors in the same arrangement, so sorting each by
    top-left corner lines them up. The pairing is sanity-checked against the
    screen's device pixel ratio; if anything looks off we fall back to scaling
    Qt's own geometry, which is right to within a pixel.
    """
    from PyQt6.QtWidgets import QApplication

    qt_screens = sorted(
        QApplication.screens(),
        key=lambda s: (s.geometry().x(), s.geometry().y()),
    )
    monitors = physical_monitors()

    if len(monitors) == len(qt_screens):
        for qs, mon in zip(qt_screens, monitors):
            expected = qs.devicePixelRatio()
            logical_w = qs.geometry().width() or 1
            actual = mon["rect"].width() / logical_w
            # A mismatched pairing shows up immediately as a bogus ratio
            if abs(actual - expected) > 0.05:
                break
            if qs is screen:
                return QRect(mon["rect"])

    g = screen.geometry()
    dpr = screen.devicePixelRatio()
    return QRect(g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr))


def native_size(screen) -> tuple[int, int]:
    """Physical (width, height) of a QScreen, in real pixels."""
    r = native_geometry(screen)
    return r.width(), r.height()


def scale_percent(screen) -> int:
    """Windows display scaling for a QScreen, e.g. 150 for 150%."""
    return round(screen.devicePixelRatio() * 100)
