"""Windows global hotkeys, owned by the Qt GUI thread."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer, Qt
from PyQt6.QtGui import QKeySequence


def parse_hotkey(text: str) -> tuple[int, int] | None:
    if not text:
        return None
    sequence = QKeySequence(text, QKeySequence.SequenceFormat.PortableText)
    if sequence.count() != 1:
        raise ValueError("快捷键只能包含一组按键。")
    combo = sequence[0]
    mods = combo.keyboardModifiers()
    if mods & Qt.KeyboardModifier.MetaModifier or not mods & (
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    ):
        raise ValueError("请使用 Ctrl 或 Alt 作为组合键；不支持 Windows 键。")
    key = combo.key().value
    if ord('A') <= key <= ord('Z') or ord('0') <= key <= ord('9'):
        vk = key
    elif Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F11.value:
        vk = 0x70 + key - Qt.Key.Key_F1.value
    else:
        raise ValueError("主键支持 A–Z、0–9 或 F1–F11。")
    native_mods = 0x4000  # MOD_NOREPEAT
    for qt_mod, native in ((Qt.KeyboardModifier.ControlModifier, 2),
                           (Qt.KeyboardModifier.AltModifier, 1),
                           (Qt.KeyboardModifier.ShiftModifier, 4)):
        if mods & qt_mod:
            native_mods |= native
    return native_mods, vk


class GlobalHotkeys(QAbstractNativeEventFilter):
    def __init__(self, app, callbacks: dict):
        super().__init__()
        self._app = app
        self._callbacks = callbacks
        self._bindings: dict[tuple[int, int], int] = {}
        self._actions: dict[int, str] = {}
        self._user32 = ctypes.WinDLL('user32', use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        app.installNativeEventFilter(self)
        app.aboutToQuit.connect(self.close)

    def configure(self, shortcuts: dict[str, str]) -> None:
        desired = {}
        for action, text in shortcuts.items():
            binding = parse_hotkey(text)
            if binding is None:
                continue
            if binding in desired:
                raise ValueError("两个操作不能使用相同的快捷键。")
            desired[binding] = action
        # Acquire new combinations first. On conflict the old set remains active.
        added = {}
        try:
            for binding in desired:
                if binding in self._bindings:
                    continue
                used = set(self._bindings.values()) | set(added.values())
                identifier = next(i for i in range(0x1000, 0x1100) if i not in used)
                if not self._user32.RegisterHotKey(None, identifier, *binding):
                    action = desired[binding]
                    raise ValueError(f"快捷键 {shortcuts[action]} 已被占用或无法注册，请换一组按键。")
                added[binding] = identifier
        except Exception:
            for identifier in added.values():
                self._user32.UnregisterHotKey(None, identifier)
            raise
        for binding, identifier in self._bindings.items():
            if binding not in desired:
                self._user32.UnregisterHotKey(None, identifier)
        self._bindings = {binding: self._bindings.get(binding, added.get(binding)) for binding in desired}
        self._actions = {identifier: desired[binding] for binding, identifier in self._bindings.items()}

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self._actions:
                QTimer.singleShot(0, self._callbacks[self._actions[msg.wParam]])
                return True, 0
        return False, 0

    def close(self):
        for identifier in self._bindings.values():
            self._user32.UnregisterHotKey(None, identifier)
        self._bindings.clear()
        self._actions.clear()
        self._app.removeNativeEventFilter(self)
