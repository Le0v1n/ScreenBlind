"""Opt-in mouse flag sampling. Never suppresses, records positions or writes files."""
import ctypes
import sys
from collections import Counter

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from i18n import tr


class MousePacket(ctypes.Structure):
    _fields_ = [('x', ctypes.c_int32), ('y', ctypes.c_int32),
                ('mouseData', ctypes.c_uint32), ('flags', ctypes.c_uint32),
                ('time', ctypes.c_uint32), ('extra', ctypes.c_size_t)]


EVENTS = {0x200: 'move', 0x201: 'left_down', 0x202: 'left_up',
          0x204: 'right_down', 0x205: 'right_up', 0x207: 'middle_down',
          0x208: 'middle_up', 0x20A: 'wheel', 0x20B: 'x_down',
          0x20C: 'x_up', 0x20E: 'horizontal_wheel'}
# If Windows refuses to unhook, retain the callback until process exit. It keeps
# forwarding events without collecting further data; never leave a dangling FFI pointer.
_retained_hooks = []


class MouseSampler:
    def __init__(self):
        self.counts = Counter()
        self._handle = None
        self._callback = None
        self._api = None
        self.collecting = False

    def _dispatch(self, code, message, address):
        try:
            if code >= 0 and self.collecting and message in EVENTS:
                flags = ctypes.cast(address, ctypes.POINTER(MousePacket)).contents.flags
                self.counts[(EVENTS[message], bool(flags & 1), bool(flags & 2))] += 1
        except Exception:
            pass  # Never interrupt the hook chain, including on malformed input.
        return self._api.CallNextHookEx(self._handle, code, message, address)

    def start(self):
        if self._handle:
            raise RuntimeError('Mouse diagnostic already running')
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
        self.counts.clear()
        self._handle = api.SetWindowsHookExW(14, self._callback, None, 0)
        if not self._handle:
            self._callback = None
            raise ctypes.WinError(ctypes.get_last_error())
        self.collecting = True

    def stop(self):
        self.collecting = False
        if self._handle:
            if not self._api.UnhookWindowsHookEx(self._handle):
                if self not in _retained_hooks:
                    _retained_hooks.append(self)
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = None
            self._callback = None
            if self in _retained_hooks:
                _retained_hooks.remove(self)

    def summary(self):
        lines = ['mouse events=' + str(sum(self.counts.values()))]
        for (kind, injected, lower), count in sorted(self.counts.items()):
            lines.append(f'{kind} injected={int(injected)} lower_integrity={int(lower)} count={count}')
        return '\n'.join(lines)


class MouseDiagnostics(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Mouse source diagnostic'))
        self.resize(650, 480)
        self.sampler = MouseSampler()
        self._phase = ''
        self._seconds = 0
        layout = QVBoxLayout(self)
        note = QLabel(tr('Run two separate samples: local mouse only, then phone UU only. Each sample lasts 15 seconds. Move, click and scroll over this window. Input is never blocked. Only event counts and injection flags are kept in memory; no coordinates or key text are collected. Injection flags do not prove the source is UU.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        self._buttons = []
        for label in ('Sample local mouse', 'Sample phone UU'):
            button = QPushButton(tr(label))
            button.clicked.connect(lambda checked=False, phase=label: self.start_sample(phase))
            layout.addWidget(button)
            self._buttons.append(button)
        self.status = QLabel(tr('Ready'))
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(200)
        layout.addWidget(self.log)
        self.stop_button = QPushButton(tr('Stop sample'))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_sample)
        layout.addWidget(self.stop_button)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)

    def start_sample(self, phase):
        try:
            self.sampler.start()
        except (OSError, RuntimeError) as error:
            self.status.setText(tr('Mouse diagnostic unavailable: {error}', error=str(error)))
            return
        self._phase = phase
        self._seconds = 15
        for button in self._buttons:
            button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.timer.start()
        self.refresh_status()

    def refresh_status(self):
        self.status.setText(tr('Sampling: {seconds}s remaining; {count} events',
                               seconds=self._seconds, count=sum(self.sampler.counts.values())))

    def tick(self):
        self._seconds -= 1
        if self._seconds <= 0:
            self.stop_sample()
        else:
            self.refresh_status()

    def stop_sample(self):
        self.timer.stop()
        was_collecting = self.sampler.collecting
        try:
            self.sampler.stop()
        except OSError as error:
            self.status.setText(tr('Mouse diagnostic unavailable: {error}', error=str(error)))
            return
        if was_collecting:
            self.log.appendPlainText(tr(self._phase) + '\n' + self.sampler.summary() + '\n')
        for button in self._buttons:
            button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status.setText(tr('Ready'))

    def done(self, result):
        self.stop_sample()
        self.sampler.counts.clear()
        self.log.clear()
        super().done(result)
