"""Block physical keys in remote mode, with a private recovery chord detector.

Local modifiers are swallowed too, so they cannot alter concurrent UU typing.
No key text, scan codes, history or passwords are recorded.
"""
import ctypes

from hotkeys import parse_hotkey
from mouse_hook import MouseHook


class KeyboardPacket(ctypes.Structure):
    _fields_ = [('vk', ctypes.c_uint32), ('scan', ctypes.c_uint32),
                ('flags', ctypes.c_uint32), ('time', ctypes.c_uint32),
                ('extra', ctypes.c_size_t)]


MODIFIERS = {0x10: 4, 0xA0: 4, 0xA1: 4,  # Shift
             0x11: 2, 0xA2: 2, 0xA3: 2,  # Ctrl
             0x12: 1, 0xA4: 1, 0xA5: 1,  # Alt
             0x5B: 8, 0x5C: 8}           # Win (never an allowed chord)


class LocalKeyboardBlocker(MouseHook):
    hook_id = 13

    def __init__(self, shortcuts, request_recovery, recovery_focused):
        super().__init__()
        self._shortcuts = list(shortcuts)
        self._bindings = set()
        self._request_recovery = request_recovery
        self._recovery_focused = recovery_focused
        self._down = set()
        self._blocked = set()
        self._forwarded = set()

    def start(self):
        self._bindings = {(binding[0] & 0xF, binding[1]) for text in self._shortcuts
                          if (binding := parse_hotkey(text)) is not None}
        if not self._bindings:
            raise ValueError('Configure a lock or recovery hotkey before blocking the local keyboard.')
        self._down.clear()
        self._blocked.clear()
        self._forwarded.clear()
        super().start()

    def _dispatch(self, code, message, address):
        try:
            if code >= 0 and self.active and message in (0x100, 0x101, 0x104, 0x105):
                packet = ctypes.cast(address, ctypes.POINTER(KeyboardPacket)).contents
                if self.handle_key(message, packet.vk, packet.flags):
                    return 1
        except Exception:
            pass
        return self._api.CallNextHookEx(self._handle, code, message, address)

    def handle_key(self, message, vk, flags):
        if flags & 0x10:  # LLKHF_INJECTED: distinct from mouse's bit 0.
            return False
        if message in (0x101, 0x105):
            self._down.discard(vk)
            self._blocked.discard(vk)
            if vk in self._forwarded:
                self._forwarded.discard(vk)
                return False  # Deliver releases even if recovery just closed.
            return True
        repeated = vk in self._down
        self._down.add(vk)
        if repeated and vk in self._blocked:
            return True  # Held recovery key must not repeat into the password.
        modifiers = 0
        for key in self._down:
            modifiers |= MODIFIERS.get(key, 0)
        if not repeated and (modifiers, vk) in self._bindings:
            self._blocked.add(vk)
            self._request_recovery()  # Caller queues this; never opens UI inside a hook.
            return True
        # Only focused black recovery UI receives local text, Shift, Enter,
        # Backspace, arrows and Esc. Ctrl/Alt/Win shortcuts remain swallowed.
        if not modifiers & ~4 and self._recovery_focused():
            self._forwarded.add(vk)
            return False
        self._blocked.add(vk)
        return True

    def stop(self):
        try:
            super().stop()
        finally:
            self._down.clear()
            self._blocked.clear()
            self._forwarded.clear()
