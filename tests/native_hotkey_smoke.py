"""Windows-only integration smoke test; registers a hotkey without sending input.

Run separately from the offscreen tests: python tests/native_hotkey_smoke.py
"""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from hotkeys import GlobalHotkeys

app = QApplication([])
received = []


def activated():
    received.append(True)
    app.quit()


manager = GlobalHotkeys(app, {'lock': activated})
manager.configure({'lock': 'Ctrl+Alt+Shift+F10'})
identifier = next(iter(manager._actions))
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
thread_id = ctypes.windll.kernel32.GetCurrentThreadId()


def post():
    if not user32.PostThreadMessageW(thread_id, 0x0312, identifier, 0):
        raise ctypes.WinError(ctypes.get_last_error())


QTimer.singleShot(0, post)
QTimer.singleShot(3000, app.quit)
app.exec()
manager.close()
assert received == [True], 'Windows WM_HOTKEY did not reach the Qt callback'
print('PASS: native registration, Windows message dispatch, callback and cleanup')
