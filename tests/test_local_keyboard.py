"""Pure synthetic keyboard packets: automated tests never block the user's keyboard."""
import ctypes
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from mouse_hook import MouseHook
from keyboard_guard import KeyboardPacket, LocalKeyboardBlocker, MODIFIERS
import remote
from tests.test_remote_privacy import FakeScreen

APP = QApplication.instance() or QApplication([])


class LocalKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.recovery = Mock()
        self.focused = Mock(return_value=False)
        self.guard = LocalKeyboardBlocker(['Ctrl+Alt+L', ''], self.recovery, self.focused)
        with patch.object(MouseHook, 'start'):
            self.guard.start()

    def key(self, vk, up=False, injected=False):
        return self.guard.handle_key(0x101 if up else 0x100, vk, 0x10 if injected else 0)

    def chord(self):
        for vk in (0xA2, 0xA4, ord('L')):
            self.assertTrue(self.key(vk))

    def release_chord(self):
        for vk in (ord('L'), 0xA4, 0xA2):
            self.assertEqual(self.key(vk, up=True), vk not in MODIFIERS)

    def test_all_local_keys_and_releases_are_blocked(self):
        for vk in (ord('A'), 0x5B, 0x09, 0x0D, 0x1B, 0x73, 0xA0):
            self.assertTrue(self.key(vk))
            self.assertEqual(self.key(vk, up=True), vk not in MODIFIERS)
        self.recovery.assert_not_called()

    def test_local_recovery_chord_is_suppressed_and_notified_once_per_press(self):
        self.chord()
        self.recovery.assert_called_once()
        for _ in range(5):
            self.assertTrue(self.key(ord('L')))
        self.recovery.assert_called_once()
        self.release_chord()
        self.chord()
        self.assertEqual(self.recovery.call_count, 2)

    def test_right_modifiers_and_no_extra_modifiers(self):
        for vk in (0xA3, 0xA5, ord('L')):
            self.key(vk)
        self.recovery.assert_called_once()
        for vk in (ord('L'), 0xA5, 0xA3):
            self.key(vk, up=True)
        self.key(0x5B)
        self.chord()
        self.recovery.assert_called_once()

    def test_injected_events_pass_and_cannot_contaminate_local_modifier_state(self):
        for vk in (0x11, 0x12, ord('L'), 0xE7, ord('1')):
            self.assertFalse(self.key(vk, injected=True))
            self.assertFalse(self.key(vk, up=True, injected=True))
        self.assertFalse(self.guard._down)
        self.recovery.assert_not_called()
        self.assertTrue(self.key(ord('L')))
        self.recovery.assert_not_called()

    def test_held_recovery_key_cannot_type_into_password(self):
        self.chord()
        self.focused.return_value = True
        self.assertTrue(self.key(ord('L')))
        self.release_chord()
        self.assertFalse(self.key(ord('L')))
        self.assertFalse(self.key(ord('L'), up=True))

    def test_recovery_typing_only_when_focused_and_cancel_resumes_filter(self):
        self.focused.return_value = True
        for vk in (ord('A'), 0x10, ord('B'), 0x08, 0x0D, 0x1B):
            self.assertFalse(self.key(vk))
            self.assertFalse(self.key(vk, up=True))
        self.focused.return_value = False
        self.assertTrue(self.key(ord('A')))
        self.assertTrue(self.key(ord('A'), up=True))

    def test_recovery_still_blocks_system_shortcuts(self):
        self.focused.return_value = True
        for modifier in (0x11, 0x12, 0x5B):
            self.assertTrue(self.key(modifier))
            self.assertTrue(self.key(0x1B))
            self.assertTrue(self.key(0x1B, up=True))
            self.assertFalse(self.key(modifier, up=True))

    def test_forwarded_shift_release_is_delivered_after_recovery_closes(self):
        self.focused.return_value = True
        self.assertFalse(self.key(0xA0))
        self.focused.return_value = False
        self.assertFalse(self.key(0xA0, up=True))

    def test_no_recovery_shortcut_refuses_install(self):
        guard = LocalKeyboardBlocker(['', ''], self.recovery, self.focused)
        with patch.object(MouseHook, 'start') as install, self.assertRaises(ValueError):
            guard.start()
        install.assert_not_called()

    def test_modifier_pressed_before_hook_still_delivers_release(self):
        for vk in MODIFIERS:
            self.assertFalse(self.key(vk, up=True))

    def test_mixed_injected_down_physical_up_cannot_leave_alt_held(self):
        self.assertFalse(self.key(0xA4, injected=True))
        self.assertFalse(self.key(0xA4, up=True))
        self.assertFalse(self.guard._down)

    def test_injected_release_clears_stale_local_modifier_state(self):
        self.assertTrue(self.key(0xA2))
        self.assertTrue(self.key(0xA4))
        self.assertFalse(self.key(0x11, up=True, injected=True))
        self.assertFalse(self.key(0x12, up=True, injected=True))
        self.assertFalse(self.guard._down)
        self.chord()
        self.recovery.assert_called_once()

    def test_native_dispatch_forwarding_and_injection_flag(self):
        guard = self.guard
        guard.active = True
        guard._api = Mock()
        guard._api.CallNextHookEx.return_value = 123
        guard._handle = 42
        packet = KeyboardPacket(ord('A'), 0, 0, 0, 0)
        self.assertEqual(guard._dispatch(0, 0x100, ctypes.addressof(packet)), 1)
        packet.flags = 0x10
        self.assertEqual(guard._dispatch(0, 0x100, ctypes.addressof(packet)), 123)
        self.assertEqual(guard._dispatch(-1, 0x100, 0), 123)
        guard.active = False
        self.assertEqual(guard._dispatch(0, 0x100, 0), 123)

    def test_remote_lifecycle_queues_recovery_and_does_not_install_when_disabled(self):
        for enabled in (False, True):
            with patch.object(remote.QApplication, 'screens', return_value=[FakeScreen('one')]), \
                    patch.object(remote, 'screen_key', side_effect=lambda screen: screen.name()), \
                    patch.object(remote.RemoteManager, '_replace_covers', return_value=True):
                manager = remote.RemoteManager({'remote_allowed_screen_ids': ['one'],
                    'lock_hotkey': 'Ctrl+Alt+L', 'remote_block_local_keyboard': enabled})
                received = Mock()
                manager.recoveryRequested.connect(received)
                try:
                    with patch.object(manager._keyboard_blocker, 'start') as start, \
                            patch.object(manager._keyboard_blocker, 'stop') as stop:
                        self.assertTrue(manager.start())
                        self.assertEqual(start.call_count, int(enabled))
                        manager._localRecoveryRequested.emit()
                        received.assert_not_called()
                        APP.processEvents()
                        received.assert_called_once()
                        manager.stop()
                        stop.assert_called_once()
                finally:
                    manager.stop()
                    manager.deleteLater()

    def test_recovery_requires_visible_foreground_dialog(self):
        manager = remote.RemoteManager({})
        window = Mock()
        window.winId.return_value = 123
        window.isVisible.return_value = True
        manager._recovery_window = window
        try:
            with patch.object(remote, 'foreground_monitor', return_value=(456, 1)):
                self.assertFalse(manager._recovery_has_foreground())
            with patch.object(remote, 'foreground_monitor', return_value=(123, 1)):
                self.assertTrue(manager._recovery_has_foreground())
                window.isVisible.return_value = False
                self.assertFalse(manager._recovery_has_foreground())
        finally:
            manager.stop()
            manager.deleteLater()

    def test_keyboard_install_failure_requests_fallback_and_releases_mouse(self):
        with patch.object(remote.QApplication, 'screens', return_value=[FakeScreen('one')]), \
                patch.object(remote, 'screen_key', side_effect=lambda screen: screen.name()), \
                patch.object(remote.RemoteManager, '_replace_covers', return_value=True):
            manager = remote.RemoteManager({'remote_allowed_screen_ids': ['one'],
                'lock_hotkey': 'Ctrl+Alt+L', 'remote_block_local_keyboard': True,
                'remote_block_local_mouse': True})
            errors = []
            manager.failed.connect(lambda error: (errors.append(error), manager.stop()))
            try:
                with patch.object(manager._mouse_blocker, 'start'), \
                        patch.object(manager._mouse_blocker, 'stop') as mouse_stop, \
                        patch.object(manager._keyboard_blocker, 'start', side_effect=OSError('failed')), \
                        patch.object(manager._keyboard_blocker, 'stop') as keyboard_stop:
                    self.assertFalse(manager.start())
                    self.assertFalse(manager.active)
                    self.assertEqual(len(errors), 1)
                    mouse_stop.assert_called_once()
                    keyboard_stop.assert_called_once()
            finally:
                manager.stop()
                manager.deleteLater()
