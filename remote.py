"""Local black privacy covers with explicit, fail-closed capture exclusion.

Capture exclusion is a Windows capability, not a guarantee about any remote
desktop product. Authentication and transition to an ordinary lock belong to
the application controller; this module retains its covers until stopped.
"""
from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QScreen
from PyQt6.QtWidgets import QApplication, QWidget

import dpi
from blind import _force_topmost
from displays import screen_key


def foreground_monitor() -> tuple[int, int]:
    """Return foreground HWND and HMONITOR; unknown foreground means no action."""
    if sys.platform != 'win32':
        return 0, 0
    try:
        getter = ctypes.windll.user32.GetForegroundWindow
        getter.argtypes = []
        getter.restype = ctypes.c_void_p
        hwnd = int(getter() or 0)
        return hwnd, window_monitor(hwnd) if hwnd else 0
    except (AttributeError, OSError, ValueError):
        return 0, 0


def window_monitor(hwnd: int) -> int:
    """Resolve an HWND to its actual monitor without nearest-monitor guessing."""
    if sys.platform != 'win32' or not hwnd:
        return 0
    try:
        getter = ctypes.windll.user32.MonitorFromWindow
        getter.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        getter.restype = ctypes.c_void_p
        return int(getter(ctypes.c_void_p(int(hwnd)), 0) or 0)
    except (AttributeError, OSError, ValueError):
        return 0


def set_capture_exclusion(hwnd: int, enabled: bool) -> bool:
    """Set WDA_EXCLUDEFROMCAPTURE only on Windows builds that support it."""
    if sys.platform != 'win32':
        return False
    try:
        if sys.getwindowsversion().build < 19041:
            return False
        setter = ctypes.windll.user32.SetWindowDisplayAffinity
        setter.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        setter.restype = ctypes.c_int
        return bool(setter(ctypes.c_void_p(int(hwnd)), 0x11 if enabled else 0))
    except (AttributeError, OSError, ValueError):
        return False


class PrivacyOverlay(QWidget):
    """Opaque local cover, optionally excluded from supported capture paths."""

    recoveryRequested = pyqtSignal()

    def __init__(self, screen, allowed: bool):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool)
        if allowed:
            flags |= Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(None, flags)
        self.allowed = allowed
        self._allow_close = False
        self.screen_id = screen_key(screen)
        self._screen = screen
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, allowed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus if allowed else Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, not allowed)
        self.setGeometry(screen.geometry())
        self.winId()  # Create a hidden HWND so affinity is installed before show().
        if isinstance(screen, QScreen):
            self.windowHandle().setScreen(screen)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('black'))
        painter.end()

    def closeEvent(self, event):
        if not self._allow_close:
            event.ignore()
        else:
            super().closeEvent(event)

    def mousePressEvent(self, event):
        if not self.allowed:
            self.recoveryRequested.emit()
        if event is not None:
            event.accept()

    def keyPressEvent(self, event):
        event.accept()

    def inputMethodEvent(self, event):
        event.accept()

    def force_topmost(self):
        hwnd = int(self.winId())
        physical = dpi.monitor_rect_for_hwnd(hwnd)
        rect = physical if physical is not None else self.geometry()
        # Existing positioning helper sets SWP_NOACTIVATE; pass a pointer-sized
        # HWND explicitly because native handles must not truncate on 64-bit.
        _force_topmost(ctypes.c_void_p(hwnd), rect.x(), rect.y(), rect.width(), rect.height())


class RemoteManager(QObject):
    failed = pyqtSignal(str)
    fallbackRequested = pyqtSignal()
    recoveryRequested = pyqtSignal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._active = False
        self._ready = False
        self._recovery_window = None
        self._overlays: list[PrivacyOverlay] = []
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(500)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(20)
        self._focus_timer.timeout.connect(self._guard_denied_foreground)

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._active:
            return self._ready
        screens = list(QApplication.screens())
        allowed = set(self._cfg.get('remote_allowed_screen_ids', []))
        if not any(screen_key(screen) in allowed for screen in screens):
            return False
        self._active = True
        self._topmost_timer.start()
        self._focus_timer.start()
        self._ready = self._replace_covers(screens)
        return self._ready

    def _replace_covers(self, screens) -> bool:
        allowed = set(self._cfg.get('remote_allowed_screen_ids', []))
        previous = list(self._overlays)
        created = []
        affinity_ok = True
        for screen in screens:
            overlay = PrivacyOverlay(screen, screen_key(screen) in allowed)
            overlay.recoveryRequested.connect(self.recoveryRequested)
            created.append(overlay)
            self._overlays.append(overlay)
            if not set_capture_exclusion(int(overlay.winId()), overlay.allowed):
                affinity_ok = False
        # Every new cover is ready before any previous protection is removed.
        for overlay in created:
            overlay.show()
            overlay.force_topmost()
        self._raise_recovery()
        if not affinity_ok:
            self.failed.emit('Windows capture exclusion could not be enabled. Privacy covers remain active.')
            return False
        if not any(overlay.allowed for overlay in created):
            # This includes a zero-screen topology. The controller must install
            # the ordinary lock before calling stop(); retain previous covers.
            self.fallbackRequested.emit()
            return False
        self._overlays = created
        self._dispose(previous)
        self._guard_denied_foreground()
        return True

    def reconcile_screens(self):
        if self._active:
            self._ready = self._replace_covers(list(QApplication.screens()))

    def update_allowed(self, ids):
        """Apply an allowlist already authenticated by the controller."""
        self._cfg['remote_allowed_screen_ids'] = list(dict.fromkeys(ids))
        self.reconcile_screens()

    def _enforce_topmost(self):
        for overlay in self._overlays:
            overlay.force_topmost()
        self._raise_recovery()
        self._guard_denied_foreground()

    def _guard_denied_foreground(self):
        recovery = self._recovery_window
        if recovery is not None and recovery.isVisible():
            return
        foreground, monitor = foreground_monitor()
        if not foreground or not monitor:
            return
        if any(int(overlay.winId()) == foreground for overlay in self._overlays):
            return
        for overlay in self._overlays:
            if overlay.allowed:
                continue
            hwnd = int(overlay.winId())
            if window_monitor(hwnd) == monitor:
                overlay.activateWindow()
                overlay.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
                return

    def _raise_recovery(self):
        window = self._recovery_window
        if window is not None and window.isVisible():
            window.raise_()

    def set_recovery_window(self, window_or_none):
        """Keep the controller's topmost recovery dialog above the masks."""
        self._recovery_window = window_or_none
        self._raise_recovery()
        if window_or_none is not None and window_or_none.isVisible():
            window_or_none.activateWindow()

    @staticmethod
    def _dispose(overlays):
        for overlay in overlays:
            overlay._allow_close = True
            overlay.hide()
            overlay.close()
            overlay.deleteLater()

    def stop(self):
        self._topmost_timer.stop()
        self._focus_timer.stop()
        self._active = False
        self._ready = False
        self._recovery_window = None
        overlays, self._overlays = self._overlays, []
        self._dispose(overlays)
