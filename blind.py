"""
Blind: BlindState (shared across all overlays), BlindOverlay (per-screen
widget), and BlindManager (orchestrates everything).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import random

from PyQt6.QtCore import (
    QDateTime,
    QObject,
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QWidget

import animations as anim_module
from auth import verify_password


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------

def _clip_cursor(left: int, top: int, right: int, bottom: int) -> None:
    rect = ctypes.wintypes.RECT(left, top, right, bottom)
    ctypes.windll.user32.ClipCursor(ctypes.byref(rect))


def _release_cursor() -> None:
    ctypes.windll.user32.ClipCursor(None)


def _get_cursor_pos() -> tuple[int, int]:
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _set_cursor_pos(x: int, y: int) -> None:
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def _force_topmost(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    HWND_TOPMOST = ctypes.c_void_p(-1)
    SWP_NOACTIVATE = 0x0010
    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE)
    # Remove Windows 11 rounded corners
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(DWMWCP_DONOTROUND), ctypes.sizeof(DWMWCP_DONOTROUND),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Low-level keyboard hook (blocks Win key while locked)
# ---------------------------------------------------------------------------

_WH_KEYBOARD_LL = 13
_WM_KEYDOWN    = 0x0100
_WM_SYSKEYDOWN = 0x0104
_WM_KEYUP      = 0x0101
_WM_SYSKEYUP   = 0x0105
_VK_LWIN       = 0x5B
_VK_RWIN       = 0x5C
_VK_MENU       = 0x12   # Alt (either side)
_VK_TAB        = 0x09
_VK_F4         = 0x73
_VK_ESCAPE     = 0x1B


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      ctypes.c_uint),
        ("scanCode",    ctypes.c_uint),
        ("flags",       ctypes.c_uint),
        ("time",        ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


# Callback type: lParam declared as POINTER so ctypes handles 64-bit addresses
_LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    ctypes.c_uint,
    ctypes.POINTER(_KBDLLHOOKSTRUCT),
)

# Declare argtypes/restype so 64-bit pointers are handled correctly
_u32 = ctypes.windll.user32
_u32.SetWindowsHookExW.restype  = ctypes.c_void_p
_u32.SetWindowsHookExW.argtypes = [ctypes.c_int, _LowLevelKeyboardProc, ctypes.c_void_p, ctypes.c_uint]
_u32.CallNextHookEx.restype     = ctypes.c_long
_u32.CallNextHookEx.argtypes    = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(_KBDLLHOOKSTRUCT)]
_u32.UnhookWindowsHookEx.restype  = ctypes.c_bool
_u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_u32.GetAsyncKeyState.restype     = ctypes.c_short
_u32.GetAsyncKeyState.argtypes    = [ctypes.c_int]

_kb_hook_handle = None
_kb_hook_proc_ref = None  # keep alive to prevent GC


def _install_kb_hook() -> None:
    global _kb_hook_handle, _kb_hook_proc_ref

    def _proc(nCode: int, wParam: int, lParam) -> int:
        if nCode >= 0:
            vk = lParam.contents.vkCode
            # Block all events for the Win key (down AND up) so Windows
            # never sees it held — also stops Win+L via winlogon.
            if vk in (_VK_LWIN, _VK_RWIN):
                return 1
            # Block Alt+Tab / Alt+F4 / Alt+Esc on keydown by sniffing the
            # current Alt state. These are user-mode shortcuts (unlike Win+L
            # and Ctrl+Alt+Del) so the LL hook can swallow them cleanly.
            if wParam in (_WM_KEYDOWN, _WM_SYSKEYDOWN) and vk in (
                _VK_TAB, _VK_F4, _VK_ESCAPE,
            ):
                alt_state = _u32.GetAsyncKeyState(_VK_MENU)
                if alt_state & 0x8000:
                    return 1
        return _u32.CallNextHookEx(None, nCode, wParam, lParam)

    _kb_hook_proc_ref = _LowLevelKeyboardProc(_proc)
    _kb_hook_handle = _u32.SetWindowsHookExW(
        _WH_KEYBOARD_LL, _kb_hook_proc_ref, None, 0
    )


def _uninstall_kb_hook() -> None:
    global _kb_hook_handle, _kb_hook_proc_ref
    if _kb_hook_handle:
        _u32.UnhookWindowsHookEx(_kb_hook_handle)
        _kb_hook_handle = None
        _kb_hook_proc_ref = None




# ---------------------------------------------------------------------------
# Shared lock state
# ---------------------------------------------------------------------------

class BlindState(QObject):
    updated = pyqtSignal()
    unlocked = pyqtSignal()

    def __init__(self, cfg: dict, parent: QObject | None = None):
        super().__init__(parent)
        self._cfg = cfg
        self.showing_password = False
        self.password_buffer = ""
        self.in_screensaver = False
        self.shake_offset = 0
        self._wrong = False

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle)

        self._shake_frames: list[int] = []
        self._shake_idx = 0
        self._shake_timer = QTimer(self)
        self._shake_timer.setInterval(40)
        self._shake_timer.timeout.connect(self._do_shake)

        self.cursor_visible = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(530)
        self._cursor_timer.timeout.connect(self._blink_cursor)

        self.cursor_hidden = False   # True when screensaver is active

        # Clock position as screen fraction: x in [0,1], y in [0,1]
        # Starts centred; jumps to a random safe zone every 30-120 seconds.
        self.clock_rel_x = 0.50
        self.clock_rel_y = 0.38

        self._drift_timer = QTimer(self)
        self._drift_timer.setSingleShot(True)
        self._drift_timer.timeout.connect(self._pick_drift_target)
        self._drift_timer.start(random.randint(30, 120) * 1000)

        # Background hue (0-360). Fades smoothly to a new random hue periodically.
        self.bg_hue = 240.0          # start: deep indigo
        self._bg_target_hue = 240.0

        self._bg_fade_timer = QTimer(self)
        self._bg_fade_timer.setInterval(50)   # 20 fps fade
        self._bg_fade_timer.timeout.connect(self._fade_bg)

        self._bg_change_timer = QTimer(self)
        self._bg_change_timer.setSingleShot(True)
        self._bg_change_timer.timeout.connect(self._pick_bg_color)
        self._bg_change_timer.start(random.randint(30, 90) * 1000)

    # -- idle / screensaver --------------------------------------------------

    def start_idle_timer(self):
        ms = max(10, self._cfg.get("idle_timeout", 120)) * 1000
        self._idle_timer.start(ms)

    def reset_idle_timer(self):
        if self.in_screensaver:
            self.in_screensaver = False
            self.updated.emit()
        self.start_idle_timer()

    def on_mouse_move(self):
        """Mouse moved: show cursor but keep the screensaver playing."""
        changed = self.cursor_hidden
        self.cursor_hidden = False
        self.start_idle_timer()
        if changed:
            self.updated.emit()

    def _on_idle(self):
        self.in_screensaver = True
        self.cursor_hidden = True
        # Silently dismiss any open password prompt
        if self.showing_password:
            self._cursor_timer.stop()
            self.showing_password = False
            self.password_buffer = ""
            self._wrong = False
            self.shake_offset = 0
            self.cursor_visible = True
        self.updated.emit()

    # -- keyboard input ------------------------------------------------------

    def show_password_input(self):
        if not self.showing_password:
            self.showing_password = True
            self.password_buffer = ""
            self._wrong = False
            self.shake_offset = 0
            self.cursor_visible = True
            self.cursor_hidden = False   # always show cursor with the prompt
            self.in_screensaver = False  # stop screensaver when prompt appears
            self._cursor_timer.start()
            self.updated.emit()

    def hide_password_input(self):
        self._cursor_timer.stop()
        self.showing_password = False
        self.password_buffer = ""
        self._wrong = False
        self.shake_offset = 0
        self.cursor_visible = True
        self.updated.emit()

    def _blink_cursor(self):
        self.cursor_visible = not self.cursor_visible
        self.updated.emit()

    def _pick_drift_target(self):
        # x: 20-80% of width keeps the wide time text safely on screen
        # y: 15-58% of height stays well above the password prompt at 60%
        self.clock_rel_x = random.uniform(0.20, 0.80)
        self.clock_rel_y = random.uniform(0.15, 0.58)
        self.updated.emit()
        self._drift_timer.start(random.randint(30, 120) * 1000)

    def _pick_bg_color(self):
        self._bg_target_hue = random.uniform(0, 360)
        self._bg_fade_timer.start()
        self._bg_change_timer.start(random.randint(30, 90) * 1000)

    def _fade_bg(self):
        dh = self._bg_target_hue - self.bg_hue
        # Take the shortest path around the colour wheel
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
        if abs(dh) > 0.4:
            self.bg_hue = (self.bg_hue + dh * 0.025) % 360
            self.updated.emit()
        else:
            self.bg_hue = self._bg_target_hue % 360
            self._bg_fade_timer.stop()

    def handle_char(self, ch: str):
        self.password_buffer += ch
        self.updated.emit()

    def handle_backspace(self):
        if self.password_buffer:
            self.password_buffer = self.password_buffer[:-1]
            self.updated.emit()

    def attempt_unlock(self):
        if verify_password(self.password_buffer, self._cfg.get("password_hash", "")):
            self.unlocked.emit()
        else:
            self.password_buffer = ""
            self._wrong = True
            self._start_shake()

    # -- shake ---------------------------------------------------------------

    def _start_shake(self):
        self._shake_frames = [14, -14, 10, -10, 7, -7, 4, -4, 0]
        self._shake_idx = 0
        self.shake_offset = self._shake_frames[0]
        self._shake_timer.start()
        self.updated.emit()

    def _do_shake(self):
        self._shake_idx += 1
        if self._shake_idx >= len(self._shake_frames):
            self._shake_timer.stop()
            self.shake_offset = 0
            self._wrong = False
        else:
            self.shake_offset = self._shake_frames[self._shake_idx]
        self.updated.emit()

    @property
    def wrong(self) -> bool:
        return self._wrong


# ---------------------------------------------------------------------------
# Blind overlay widget (one per locked screen)
# ---------------------------------------------------------------------------

_MODIFIER_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock,
    Qt.Key.Key_ScrollLock, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R,
}


class BlindOverlay(QWidget):
    def __init__(self, geo: QRect, state: BlindState, cfg: dict):
        super().__init__(None)
        self._geo = geo
        self._state = state
        self._cfg = cfg
        self._animation: anim_module.BaseAnimation | None = None
        self._ss_active = False
        self._allow_close = False   # only the unlock flow may close us

        self._setup_window()
        self._setup_animation()
        self._setup_timers()

        state.updated.connect(self.update)
        state.updated.connect(self._sync_cursor)

    # -- setup ---------------------------------------------------------------

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setGeometry(self._geo)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _setup_animation(self):
        name = self._cfg.get("screensaver_type", "bubbles")
        self._animation = anim_module.make_animation(name, self, self._cfg)

    def _setup_timers(self):
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self.update)
        self._clock_timer.start()

    # -- after show() call this to truly cover the taskbar ------------------

    def force_topmost(self):
        _force_topmost(
            int(self.winId()),
            self._geo.x(), self._geo.y(),
            self._geo.width(), self._geo.height(),
        )

    # -- screensaver ---------------------------------------------------------

    def enter_screensaver(self):
        if not self._ss_active and self._animation:
            self._ss_active = True
            self._animation.start()

    def leave_screensaver(self):
        if self._ss_active and self._animation:
            self._ss_active = False
            self._animation.stop()

    def _sync_cursor(self):
        if self._state.cursor_hidden:
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        # Background gradient — hue rotates slowly between random dark tones
        h = self._state.bg_hue / 360.0
        top_c = QColor.fromHslF(h, 0.45, 0.06)
        bot_c = QColor.fromHslF(h, 0.32, 0.13)
        grad = QLinearGradient(0, 0, 0, rect.height())
        grad.setColorAt(0.0, top_c)
        grad.setColorAt(1.0, bot_c)
        painter.fillRect(rect, QBrush(grad))

        # Screensaver
        if self._state.in_screensaver and self._animation:
            self._animation.draw(painter, rect)
            painter.fillRect(rect, QColor(0, 0, 0, 70))

        # Clock (always visible)
        self._draw_clock(painter, rect)

        # Password prompt or hint
        if self._state.showing_password:
            self._draw_password_prompt(painter, rect)
        elif not self._state.in_screensaver:
            self._draw_hint(painter, rect)

    def _draw_clock(self, painter: QPainter, rect: QRect):
        now = QDateTime.currentDateTime()
        # Convert screen-relative position to pixel coords.
        # drift_x offsets the AlignHCenter rect so the visual centre lands on cx.
        cx = int(self._state.clock_rel_x * rect.width())
        y_base = int(self._state.clock_rel_y * rect.height())
        drift_x = cx - rect.width() // 2

        # Large time
        time_str = now.toString("HH:mm")
        font_time = QFont("Segoe UI", 82)
        font_time.setWeight(QFont.Weight.Light)
        painter.setFont(font_time)
        fm = QFontMetrics(font_time)
        th = fm.height()
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(
            QRect(drift_x, y_base - th // 2, rect.width(), th + 4),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            time_str,
        )

        # Seconds (smaller, to the right)
        sec_str = now.toString("ss")
        font_sec = QFont("Segoe UI", 28)
        font_sec.setWeight(QFont.Weight.Light)
        painter.setFont(font_sec)
        fm_time = QFontMetrics(font_time)
        time_w = fm_time.horizontalAdvance(time_str)
        sec_x = cx + time_w // 2 + 8
        painter.setPen(QColor(180, 180, 230, 180))
        painter.drawText(sec_x, y_base + 10, sec_str)

        # Date
        date_str = now.toString("dddd, MMMM d")
        font_date = QFont("Segoe UI", 18)
        font_date.setWeight(QFont.Weight.Light)
        painter.setFont(font_date)
        painter.setPen(QColor(190, 190, 240, 190))
        painter.drawText(
            QRect(drift_x, y_base + th // 2 + 8, rect.width(), 36),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            date_str,
        )

    def _draw_password_prompt(self, painter: QPainter, rect: QRect):
        ox = self._state.shake_offset
        pw, ph = 380, 130
        px = (rect.width() - pw) // 2 + ox
        py = int(rect.height() * 0.60)

        # Panel background
        painter.setBrush(QColor(0, 0, 0, 170))
        border_color = (
            QColor(220, 80, 80, 200) if self._state.wrong
            else QColor(80, 100, 160, 180)
        )
        painter.setPen(QPen(border_color, 1.5))
        painter.drawRoundedRect(px, py, pw, ph, 14, 14)

        # Password dots
        n = len(self._state.password_buffer)
        dot_r = 6
        spacing = 20
        dy = py + 40
        if n > 0:
            total = n * dot_r * 2 + (n - 1) * (spacing - dot_r * 2)
            dx = px + (pw - total) // 2
            painter.setPen(Qt.PenStyle.NoPen)
            for i in range(n):
                painter.setBrush(QColor(255, 255, 255, 230))
                painter.drawEllipse(dx + i * spacing, dy, dot_r * 2, dot_r * 2)
            # Blinking cursor after last dot
            if self._state.cursor_visible:
                cursor_x = dx + (n - 1) * spacing + dot_r * 2 + 6
                painter.fillRect(cursor_x, dy - 3, 2, dot_r * 2 + 6, QColor(255, 255, 255, 210))
        else:
            font = QFont("Segoe UI", 14)
            font.setWeight(QFont.Weight.Light)
            painter.setFont(font)
            painter.setPen(QColor(140, 140, 180))
            painter.drawText(
                QRect(px, py + 28, pw, 40),
                Qt.AlignmentFlag.AlignCenter,
                "Enter password",
            )
            # Blinking cursor centered in placeholder area
            if self._state.cursor_visible:
                painter.fillRect(px + pw // 2, py + 32, 2, 22, QColor(200, 200, 220, 200))

        # Status/hint line
        font2 = QFont("Segoe UI", 11)
        painter.setFont(font2)
        if self._state.wrong:
            painter.setPen(QColor(255, 100, 100, 220))
            painter.drawText(
                QRect(px, py + 88, pw, 30),
                Qt.AlignmentFlag.AlignCenter,
                "Incorrect password",
            )
        else:
            painter.setPen(QColor(130, 130, 175, 190))
            painter.drawText(
                QRect(px, py + 88, pw, 30),
                Qt.AlignmentFlag.AlignCenter,
                "↵  Unlock    Esc  Cancel",
            )

    def _draw_hint(self, painter: QPainter, rect: QRect):
        font = QFont("Segoe UI", 13)
        font.setWeight(QFont.Weight.Light)
        painter.setFont(font)
        painter.setPen(QColor(130, 130, 190, 160))
        painter.drawText(
            QRect(0, int(rect.height() * 0.84), rect.width(), 30),
            Qt.AlignmentFlag.AlignCenter,
            "Press any key to unlock",
        )

    # -- input ---------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() in _MODIFIER_KEYS:
            return
        if not self._state.showing_password:
            self._state.show_password_input()
            return
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._state.attempt_unlock()
        elif key == Qt.Key.Key_Escape:
            self._state.hide_password_input()
        elif key == Qt.Key.Key_Backspace:
            self._state.handle_backspace()
        else:
            text = event.text()
            if text and text.isprintable():
                self._state.handle_char(text)

    def mouseMoveEvent(self, _event):
        self._state.on_mouse_move()

    def mousePressEvent(self, _event):
        self.activateWindow()
        self.setFocus()
        self._state.show_password_input()

    def closeEvent(self, event):
        # The overlay must never close on its own (Alt+F4, WM_CLOSE, etc.).
        # The unlock flow flips _allow_close before calling close().
        if not self._allow_close:
            event.ignore()
            return
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Blind manager
# ---------------------------------------------------------------------------

class BlindManager(QObject):
    unlocked = pyqtSignal()

    def __init__(self, cfg: dict, parent: QObject | None = None):
        super().__init__(parent)
        self._cfg = cfg
        self._overlays: list[BlindOverlay] = []
        self._state: BlindState | None = None
        self._locked_rects: list[QRect] = []

        # Keep-on-top enforcer (taskbar can briefly appear above on some systems)
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(500)
        self._topmost_timer.timeout.connect(self._enforce_topmost)

        # Cursor guard: ClipCursor only handles a single bounding rect. When
        # an unlocked monitor sits inside that bounding rect, the cursor can
        # escape into it through the resulting gap. This 100Hz watchdog
        # snaps the cursor back to the nearest locked screen.
        self._cursor_guard = QTimer(self)
        self._cursor_guard.setInterval(10)
        self._cursor_guard.timeout.connect(self._enforce_cursor_clip)

    def lock(self):
        if self._overlays:
            return

        self._state = BlindState(self._cfg, self)
        self._state.unlocked.connect(self._on_unlocked)
        self._state.updated.connect(self._on_state_update)

        screens = QApplication.screens()
        locked_indices: list[int] = self._cfg.get("locked_screens", [])
        clip_rects: list[QRect] = []

        for idx in locked_indices:
            if idx >= len(screens):
                continue
            geo = screens[idx].geometry()
            overlay = BlindOverlay(geo, self._state, self._cfg)
            overlay.show()
            overlay.force_topmost()
            self._overlays.append(overlay)
            clip_rects.append(geo)

        if not self._overlays:
            self._state = None
            return

        # Trap mouse inside the bounding rect of all locked screens
        self._locked_rects = clip_rects
        left = min(r.left() for r in clip_rects)
        top = min(r.top() for r in clip_rects)
        right = max(r.right() for r in clip_rects)
        bottom = max(r.bottom() for r in clip_rects)
        _clip_cursor(left, top, right, bottom)

        self._state.start_idle_timer()
        self._topmost_timer.start()
        self._cursor_guard.start()
        _install_kb_hook()

        # Give the first overlay keyboard focus
        if self._overlays:
            self._overlays[0].activateWindow()
            self._overlays[0].setFocus()

    def _enforce_topmost(self):
        for o in self._overlays:
            o.force_topmost()

    def _enforce_cursor_clip(self):
        """Snap cursor back to the nearest locked screen if it escaped."""
        if not self._locked_rects:
            return
        x, y = _get_cursor_pos()
        # Fast path: cursor is already on a locked screen
        for r in self._locked_rects:
            if r.contains(x, y):
                return
        # Cursor sneaked into an unlocked region — find nearest locked rect
        best_x, best_y = x, y
        best_dist = float("inf")
        for r in self._locked_rects:
            cx = max(r.left(), min(r.right() - 1, x))
            cy = max(r.top(), min(r.bottom() - 1, y))
            d = (cx - x) * (cx - x) + (cy - y) * (cy - y)
            if d < best_dist:
                best_dist = d
                best_x, best_y = cx, cy
        _set_cursor_pos(best_x, best_y)

    def _on_state_update(self):
        if not self._state:
            return
        for o in self._overlays:
            if self._state.in_screensaver:
                o.enter_screensaver()
            else:
                o.leave_screensaver()

    def _on_unlocked(self):
        self._topmost_timer.stop()
        self._cursor_guard.stop()
        self._locked_rects.clear()
        _release_cursor()
        _uninstall_kb_hook()
        for o in self._overlays:
            o._allow_close = True
            o.close()
        self._overlays.clear()
        self._state = None
        self.unlocked.emit()
