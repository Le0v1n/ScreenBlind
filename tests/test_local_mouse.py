"""Never install a real blocking hook in automated tests."""
import ctypes
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from mouse_hook import EVENTS, LocalMouseBlocker, MousePacket, _retained_hooks
import remote
from tests.test_remote_privacy import FakeScreen

APP = QApplication.instance() or QApplication([])


class LocalMouseTests(unittest.TestCase):
    def blocker(self):
        blocker = LocalMouseBlocker()
        blocker.active = True
        blocker._handle = 42
        blocker._api = MagicMock()
        blocker._api.CallNextHookEx.return_value = 123
        return blocker

    def test_blocks_every_physical_mouse_event_but_forwards_injected(self):
        blocker = self.blocker()
        for message in EVENTS:
            for flags in (0, 1, 2, 3):
                packet = MousePacket(0, 0, 0, flags, 0, 0)
                blocker._api.CallNextHookEx.reset_mock()
                result = blocker._dispatch(0, message, ctypes.addressof(packet))
                self.assertEqual(result, 123 if flags & 1 else 1)
                self.assertEqual(blocker._api.CallNextHookEx.call_count, 1 if flags & 1 else 0)

    def test_disabled_or_negative_hook_always_forwards(self):
        blocker = self.blocker()
        self.assertEqual(blocker._dispatch(-1, 0x200, 0), 123)
        blocker.active = False
        self.assertEqual(blocker._dispatch(0, 0x200, 0), 123)

    def test_unhook_failure_disables_filter_and_keeps_callback_alive(self):
        blocker = self.blocker()
        callback = object()
        blocker._callback = callback
        blocker._api.UnhookWindowsHookEx.return_value = 0
        try:
            with self.assertRaises(OSError):
                blocker.stop()
            self.assertFalse(blocker.active)
            self.assertIn(blocker, _retained_hooks)
            self.assertIs(blocker._callback, callback)
            self.assertEqual(blocker._dispatch(0, 0x200, 0), 123)
        finally:
            blocker._api.UnhookWindowsHookEx.return_value = 1
            blocker.stop()
        self.assertNotIn(blocker, _retained_hooks)

    def test_callback_exception_forwards(self):
        blocker = self.blocker()
        packet = MousePacket()
        with patch.object(blocker, 'handle_mouse', side_effect=ValueError()):
            self.assertEqual(blocker._dispatch(0, 0x200, ctypes.addressof(packet)), 123)

    def manager(self, enabled):
        return remote.RemoteManager({'remote_allowed_screen_ids': ['one'],
                                     'remote_block_local_mouse': enabled})

    def test_remote_lifecycle_and_default_off(self):
        for enabled in (False, True):
            with patch.object(remote.QApplication, 'screens', return_value=[FakeScreen('one')]), \
                    patch.object(remote, 'screen_key', side_effect=lambda screen: screen.name()), \
                    patch.object(remote.RemoteManager, '_replace_covers', return_value=True):
                manager = self.manager(enabled)
                try:
                    with patch.object(manager._mouse_blocker, 'start') as start, \
                            patch.object(manager._mouse_blocker, 'stop') as stop:
                        self.assertTrue(manager.start())
                        self.assertEqual(start.call_count, int(enabled))
                        manager.start()
                        self.assertEqual(start.call_count, int(enabled))
                        manager.stop()
                        stop.assert_called_once()
                finally:
                    manager.stop()
                    manager.deleteLater()

    def test_filter_install_failure_retains_remote_state_and_reports_failure(self):
        with patch.object(remote.QApplication, 'screens', return_value=[FakeScreen('one')]), \
                patch.object(remote, 'screen_key', side_effect=lambda screen: screen.name()), \
                patch.object(remote.RemoteManager, '_replace_covers', return_value=True):
            manager = self.manager(True)
            errors = []
            manager.failed.connect(errors.append)
            try:
                with patch.object(manager._mouse_blocker, 'start', side_effect=OSError('unavailable')):
                    self.assertFalse(manager.start())
                self.assertTrue(manager.active)
                self.assertEqual(len(errors), 1)
            finally:
                manager.stop()
                manager.deleteLater()
