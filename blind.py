"""
Blind: BlindState (shared across all overlays), BlindOverlay (per-screen
widget), and BlindManager (orchestrates everything).
"""

from __future__ import annotations

from i18n import tr

import ctypes
import ctypes.wintypes
import random

from PyQt6.QtCore import (
    QObject,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication, QWidget, QGraphicsScene, QGraphicsBlurEffect

import animations as anim_module
import dpi
from displays import display_name, screen_key, selected_screen_indices
from clocks import clock_bounds, draw_clock
from widgets import PasswordEdit
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
    if not isinstance(hwnd, ctypes.c_void_p):
        hwnd = ctypes.c_void_p(hwnd)
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
        self._unlock_emitted = False

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
        # Fixed by default; optional movement every 30-120 seconds.
        self.clock_rel_x = 0.50
        self.clock_rel_y = 0.38

        self._drift_timer = QTimer(self)
        self._drift_timer.setSingleShot(True)
        self._drift_timer.timeout.connect(self._pick_drift_target)
        if self._cfg.get('clock_moving', False):
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
        if not self._cfg.get("screensaver_enabled", True):
            self._idle_timer.stop()
            return
        seconds = max(0, self._cfg.get("idle_timeout", 120))
        if seconds == 0:
            self._idle_timer.stop()
            if not self.showing_password and not self.in_screensaver:
                self._on_idle()
            return
        ms = seconds * 1000
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
        if not self._cfg.get("screensaver_enabled", True):
            return
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
            # Keep an active slideshow and its transition timeline behind the prompt.
            if self._cfg.get('screensaver_type') != 'slideshow':
                self.in_screensaver = False
            self._cursor_timer.start()
            self.updated.emit()
            self.start_idle_timer()

    def hide_password_input(self):
        self._cursor_timer.stop()
        self.showing_password = False
        self.password_buffer = ""
        self._wrong = False
        self.shake_offset = 0
        self.cursor_visible = True
        self.updated.emit()
        self.start_idle_timer()

    def _blink_cursor(self):
        self.cursor_visible = not self.cursor_visible
        self.updated.emit()

    def _pick_drift_target(self):
        if not self._cfg.get('clock_moving', False):
            self._drift_timer.stop()
            return
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
        if self._unlock_emitted:
            return
        self.start_idle_timer()
        self.password_buffer += ch
        self.updated.emit()
        self._try_unlock()

    def set_password_text(self, text: str):
        """One committed editor value, never an appended IME preedit string."""
        if self._unlock_emitted or not self.showing_password:
            return
        self.password_buffer = text
        self._wrong = False
        self.start_idle_timer()
        self.updated.emit()
        self._try_unlock()

    def handle_backspace(self):
        if self._unlock_emitted:
            return
        self.start_idle_timer()
        if self.password_buffer:
            self.password_buffer = self.password_buffer[:-1]
            self.updated.emit()
            self._try_unlock()

    def _try_unlock(self) -> bool:
        """Check the complete buffer silently; a partial password is normal."""
        if self._unlock_emitted:
            return True
        if verify_password(self.password_buffer, self._cfg.get("password_hash", "")):
            self._unlock_emitted = True
            self.password_buffer = ""
            self.unlocked.emit()
            return True
        return False

    def attempt_unlock(self):
        self.start_idle_timer()
        if not self._try_unlock():
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
    def __init__(self, geo: QRect, state: BlindState, cfg: dict,
                 screen_name: str = '', slideshow=None):
        super().__init__(None)
        self._geo = geo          # Qt logical pixels — for setGeometry()
        self._phys = QRect(geo)  # physical pixels — for every Win32 call
        self._state = state
        self._cfg = cfg
        self._screen_name = screen_name
        self._animation: anim_module.BaseAnimation | None = None
        self._ss_active = False
        self._allow_close = False   # only the unlock flow may close us
        self._blur_key = None
        self._blur_pixmap = None

        self._setup_window()
        self._password_edit = PasswordEdit(self)
        self._password_edit.setPlaceholderText(tr('Enter password'))
        self._password_edit.setStyleSheet('QLineEdit { background: transparent; border: none; color: white; font-size: 22px; padding: 0; selection-background-color: #6366f1; }')
        self._password_edit.textEdited.connect(state.set_password_text)
        self._password_edit.returnPressed.connect(state.attempt_unlock)
        self._password_edit.cancelled.connect(state.hide_password_input)
        self._password_edit.hide()
        self._setup_animation(slideshow)
        self._setup_timers()

        state.updated.connect(self.update)
        state.updated.connect(self._sync_cursor)
        state.updated.connect(self._sync_password_edit)

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
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _setup_animation(self, slideshow=None):
        name = self._cfg.get("screensaver_type", "bubbles")
        if name == 'slideshow' and slideshow is not None:
            self._animation = slideshow
            slideshow.updated.connect(self.update)
        else:
            self._animation = anim_module.make_animation(name, self, self._cfg)

    def _setup_timers(self):
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self.update)
        self._clock_timer.start()

    # -- after show() call this to truly cover the taskbar ------------------

    def sync_native_geometry(self) -> QRect:
        """
        Re-read the physical bounds of the monitor this overlay lives on.

        self._geo is in Qt's logical pixels, which on a scaled display are
        smaller than the real ones — pushing those numbers through SetWindowPos
        would shrink the blind to a fraction of the monitor. Ask Windows for
        the monitor's true rect instead. Cheap enough to redo on every topmost
        tick, which also lets the blind heal itself if the resolution or
        scaling changes while locked.
        """
        rect = dpi.monitor_rect_for_hwnd(int(self.winId()))
        if rect is not None and rect.isValid():
            self._phys = rect
        return self._phys

    @property
    def native_rect(self) -> QRect:
        return QRect(self._phys)   # copy: callers keep it to detect changes

    def force_topmost(self):
        self.sync_native_geometry()
        _force_topmost(
            int(self.winId()),
            self._phys.x(), self._phys.y(),
            self._phys.width(), self._phys.height(),
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

    def _sync_password_edit(self):
        edit = self._password_edit
        if edit.text() != self._state.password_buffer:
            edit.blockSignals(True)
            edit.setText(self._state.password_buffer)
            edit.setCursorPosition(len(edit.text()))
            edit.blockSignals(False)
        width = min(380, max(100, self.width() - 32))
        edit.setGeometry((self.width() - width) // 2 + 18 + self._state.shake_offset,
                         int(self.height() * 0.60) + 22, width - 36, 52)
        edit.setVisible(self._state.showing_password)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_password_edit'):
            self._sync_password_edit()

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.rect()

            if self._state.showing_password:
                self._draw_blurred_background(painter, rect)
            else:
                self._draw_background(painter, rect)

            # Clock and input stay sharp above the blurred background.
            self._draw_clock(painter, rect)
            if self._screen_name:
                painter.setFont(QFont('Microsoft YaHei UI', 12))
                painter.setPen(QColor(235, 235, 255, 210))
                name = painter.fontMetrics().elidedText(self._screen_name, Qt.TextElideMode.ElideRight, max(0, rect.width() - 48))
                painter.drawText(rect.adjusted(24, 20, -24, -20),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)

            if self._state.showing_password:
                self._draw_password_prompt(painter, rect)
            elif not self._state.in_screensaver:
                self._draw_hint(painter, rect)
        finally:
            painter.end()

    def _draw_background(self, painter, rect):
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
            own_bg = self._animation.background_color()
            if own_bg is not None:
                painter.fillRect(rect, own_bg)
            self._animation.draw(painter, rect)
            dim = self._animation.DIM_OVERLAY
            if dim:
                painter.fillRect(rect, QColor(0, 0, 0, dim))

    def _draw_blurred_background(self, painter, rect):
        animation = self._animation if self._state.in_screensaver else None
        if isinstance(animation, anim_module.SlideshowAnimation):
            key = (rect.size(),
                   animation._current.cacheKey() if animation._current else None,
                   animation._next.cacheKey() if animation._next else None, animation._alpha)
        else:
            key = (rect.size(), self._state.bg_hue)
        if key != self._blur_key:
            # Blur a bounded working image, preserving live slideshow transitions.
            scale = min(1.0, 480 / max(1, rect.width(), rect.height()))
            source = QPixmap(max(1, round(rect.width() * scale)), max(1, round(rect.height() * scale)))
            source.fill(Qt.GlobalColor.black)
            background = QPainter(source)
            background.scale(source.width() / max(1, rect.width()), source.height() / max(1, rect.height()))
            self._draw_background(background, rect)
            background.end()
            scene = QGraphicsScene()
            item = scene.addPixmap(source)
            effect = QGraphicsBlurEffect()
            effect.setBlurRadius(18)
            effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
            item.setGraphicsEffect(effect)
            blurred = QPixmap(source.size())
            blurred.fill(Qt.GlobalColor.black)
            output = QPainter(blurred)
            area = QRectF(source.rect())
            scene.render(output, area, area)
            output.end()
            self._blur_pixmap = blurred
            self._blur_key = key
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(rect, self._blur_pixmap)

    def _draw_clock(self, painter: QPainter, rect: QRect):
        bounds = clock_bounds(rect, self._state.clock_rel_x, self._state.clock_rel_y)
        draw_clock(painter, bounds, self._cfg.get('clock_style', 'classic'))

    def _draw_password_prompt(self, painter: QPainter, rect: QRect):
        ox = self._state.shake_offset
        pw, ph = 380, 130
        px = (rect.width() - pw) // 2 + ox
        py = int(rect.height() * 0.60)

        # Panel background
        painter.setBrush(QColor(0, 0, 0, 190))
        border_color = (
            QColor(220, 80, 80, 200) if self._state.wrong
            else QColor(80, 100, 160, 180)
        )
        painter.setPen(QPen(border_color, 1.5))
        painter.drawRoundedRect(px, py, pw, ph, 14, 14)

        # Password editing is handled by the standard child QLineEdit.

        # Status/hint line
        font2 = QFont("Microsoft YaHei UI", 11)
        painter.setFont(font2)
        if self._state.wrong:
            painter.setPen(QColor(255, 100, 100, 220))
            painter.drawText(
                QRect(px, py + 88, pw, 30),
                Qt.AlignmentFlag.AlignCenter,
                tr('Incorrect password'),
            )
        else:
            painter.setPen(QColor(130, 130, 175, 190))
            painter.drawText(
                QRect(px, py + 88, pw, 30),
                Qt.AlignmentFlag.AlignCenter,
                tr('Correct password unlocks    Esc  Cancel'),
            )

    def _draw_hint(self, painter: QPainter, rect: QRect):
        font = QFont("Microsoft YaHei UI", 13)
        font.setWeight(QFont.Weight.Light)
        painter.setFont(font)
        painter.setPen(QColor(130, 130, 190, 160))
        painter.drawText(
            QRect(0, int(rect.height() * 0.84), rect.width(), 30),
            Qt.AlignmentFlag.AlignCenter,
            tr('Press any key or click to enter your password'),
        )

    # -- input ---------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() in _MODIFIER_KEYS:
            return
        if not self._state.showing_password:
            self._state.show_password_input()
            self._password_edit.wake_key = event.key()
            self._password_edit.setFocus()
            # The first key only dismisses the clock surface, regardless of text.
            return
        self._password_edit.keyPressEvent(event)

    def inputMethodEvent(self, event):
        if not self._state.showing_password:
            self._state.show_password_input()
            self._password_edit.setFocus()
            event.accept()
            return
        self._password_edit.inputMethodEvent(event)

    def mouseMoveEvent(self, _event):
        self._state.on_mouse_move()

    def mousePressEvent(self, _event):
        self.activateWindow()
        self.setFocus()
        self._state.show_password_input()
        self._password_edit.setFocus()

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
        self._overlays_by_key = {}
        self._shared_slideshow = None

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

    def lock(self, allow_empty=False):
        if self._state is not None:
            return True
        self._state = BlindState(self._cfg, self)
        self._state.unlocked.connect(self._on_unlocked)
        self._state.updated.connect(self._on_state_update)
        self.reconcile_screens()
        if not self._overlays and not allow_empty:
            self._state.deleteLater()
            self._state = None
            return False
        self._state.start_idle_timer()
        self._topmost_timer.start()
        self._cursor_guard.start()
        _install_kb_hook()
        if self._overlays:
            self._overlays[0].activateWindow()
            self._overlays[0].setFocus()
        return True

    def reconcile_screens(self):
        if self._state is None:
            return
        screens = QApplication.screens()
        targets = [(screen_key(screens[i]), i, screens[i])
                   for i in selected_screen_indices(self._cfg, screens)]
        current = {}
        # Add coverage before removing obsolete windows. The session survives zero screens.
        for key, idx, screen in targets:
            geo = screen.geometry()
            overlay = self._overlays_by_key.get(key)
            if overlay is None:
                overlay = BlindOverlay(geo, self._state, self._cfg,
                                       screen_name=display_name(screen, idx, self._cfg),
                                       slideshow=self._shared_slideshow)
                if self._cfg.get('screensaver_type') == 'slideshow' and self._cfg.get('slideshow_sync', True):
                    self._shared_slideshow = overlay._animation
                    self._shared_slideshow.setParent(self)
                overlay.show()
                overlay._sync_password_edit()
            else:
                overlay.setGeometry(geo)
                overlay._screen_name = display_name(screen, idx, self._cfg)
            overlay.sync_native_geometry()
            overlay.force_topmost()
            current[key] = overlay
        for key, overlay in self._overlays_by_key.items():
            if key not in current:
                if overlay._animation is not self._shared_slideshow and overlay._animation:
                    overlay._animation.stop()
                overlay._allow_close = True
                overlay.close()
                overlay.deleteLater()
        self._overlays_by_key = current
        self._overlays = list(current.values())
        self._locked_rects = [overlay.native_rect for overlay in self._overlays]
        if self._locked_rects:
            self._apply_cursor_clip()
        else:
            _release_cursor()
            if self._shared_slideshow:
                self._shared_slideshow.stop()
        self._on_state_update()

    def _apply_cursor_clip(self):
        if not self._locked_rects:
            return
        left = min(r.left() for r in self._locked_rects)
        top = min(r.top() for r in self._locked_rects)
        # QRect.right()/bottom() are inclusive, ClipCursor's are exclusive —
        # without the +1 the cursor can never reach the last row or column.
        right = max(r.right() for r in self._locked_rects) + 1
        bottom = max(r.bottom() for r in self._locked_rects) + 1
        _clip_cursor(left, top, right, bottom)

    def _enforce_topmost(self):
        for o in self._overlays:
            o.force_topmost()

        # force_topmost() re-reads each monitor's physical rect, so a
        # resolution or scaling change made while locked shows up here.
        # Re-clip only when something actually moved.
        current = [o.native_rect for o in self._overlays]
        if current != self._locked_rects:
            self._locked_rects = current
            self._apply_cursor_clip()

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
            # right()/bottom() are the last valid pixel, so clamp to them
            cx = max(r.left(), min(r.right(), x))
            cy = max(r.top(), min(r.bottom(), y))
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
            o.deleteLater()
        self._overlays.clear()
        self._overlays_by_key.clear()
        if self._shared_slideshow:
            self._shared_slideshow.stop()
            self._shared_slideshow.deleteLater()
            self._shared_slideshow = None
        if self._state:
            self._state.deleteLater()
        self._state = None
        self.unlocked.emit()
