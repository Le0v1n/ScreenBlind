"""Pointer-safe, message-loop-thread Windows mouse hooks with explicit lifetime."""
import ctypes
import sys


class MousePacket(ctypes.Structure):
    _fields_ = [('x', ctypes.c_int32), ('y', ctypes.c_int32),
                ('mouseData', ctypes.c_uint32), ('flags', ctypes.c_uint32),
                ('time', ctypes.c_uint32), ('extra', ctypes.c_size_t)]


EVENTS = {0x200: 'move', 0x201: 'left_down', 0x202: 'left_up',
          0x204: 'right_down', 0x205: 'right_up', 0x207: 'middle_down',
          0x208: 'middle_up', 0x20A: 'wheel', 0x20B: 'x_down',
          0x20C: 'x_up', 0x20E: 'horizontal_wheel'}
_retained_hooks = []


class MouseHook:
    hook_id = 14
    def __init__(self):
        self._handle = None
        self._callback = None
        self._api = None
        self.active = False

    def handle_mouse(self, message, flags):
        return False

    def _dispatch(self, code, message, address):
        try:
            if code >= 0 and self.active and message in EVENTS:
                flags = ctypes.cast(address, ctypes.POINTER(MousePacket)).contents.flags
                if self.handle_mouse(message, flags):
                    return 1
        except Exception:
            pass  # An unexpected Python error must not strand user input.
        return self._api.CallNextHookEx(self._handle, code, message, address)

    def start(self):
        if self._handle:
            raise RuntimeError('Mouse hook already installed')
        if sys.platform != 'win32':
            raise OSError('Windows required')
        api = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                          ctypes.c_size_t, ctypes.c_ssize_t)
        api.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, ctypes.c_void_p, ctypes.c_uint32]
        api.SetWindowsHookExW.restype = ctypes.c_void_p
        api.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
        api.CallNextHookEx.restype = ctypes.c_ssize_t
        api.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        api.UnhookWindowsHookEx.restype = ctypes.c_int
        self._api = api
        self._callback = callback_type(self._dispatch)
        self._handle = api.SetWindowsHookExW(self.hook_id, self._callback, None, 0)
        if not self._handle:
            self._callback = None
            raise ctypes.WinError(ctypes.get_last_error())
        self.active = True

    def stop(self):
        # Disable filtering before unhooking, even if Windows rejects the removal.
        self.active = False
        if self._handle:
            if not self._api.UnhookWindowsHookEx(self._handle):
                if self not in _retained_hooks:
                    _retained_hooks.append(self)
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = None
            self._callback = None
            if self in _retained_hooks:
                _retained_hooks.remove(self)


class LocalMouseBlocker(MouseHook):
    """Filter unmarked mouse events; injected is not an authenticated UU identity."""
    def handle_mouse(self, message, flags):
        return not bool(flags & 1)
