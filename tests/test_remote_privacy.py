"""Offscreen privacy lifecycle tests; native capture and positioning are mocked."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtGui import QInputMethodEvent, QKeyEvent
from PyQt6.QtWidgets import QApplication

import remote

APP = QApplication.instance() or QApplication([])


class FakeScreen:
    def __init__(self, name, x=0):
        self._name = name
        self.rect = QRect(x, 0, 640, 480)

    def name(self):
        return self._name

    def geometry(self):
        return self.rect


class RemotePrivacyTests(unittest.TestCase):
    def setUp(self):
        self.screens = [FakeScreen('one'), FakeScreen('two', 640)]
        self.patches = [
            patch.object(remote.QApplication, 'screens', side_effect=lambda: self.screens),
            patch.object(remote, 'screen_key', side_effect=lambda screen: screen.name()),
            patch.object(remote, 'set_capture_exclusion', return_value=True),
            patch.object(remote.dpi, 'monitor_rect_for_hwnd', return_value=None),
            patch.object(remote, '_force_topmost'),
            patch.object(remote, 'foreground_monitor', return_value=(0, 0), create=True),
            patch.object(remote, 'window_monitor', return_value=0, create=True),
        ]
        self.mocks = [item.start() for item in self.patches]
        self.manager = remote.RemoteManager({'remote_allowed_screen_ids': ['one']})
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.manager.stop()
        for item in reversed(self.patches):
            item.stop()
        APP.processEvents()

    def test_active_cover_cannot_be_closed_by_native_close_request(self):
        self.manager.start()
        denied = next(overlay for overlay in self.manager._overlays if not overlay.allowed)
        self.assertTrue(denied.isVisible())
        denied.close()
        self.assertTrue(denied.isVisible())
        self.manager.stop()
        self.assertFalse(denied.isVisible())

    def test_foreground_guard_has_independent_short_interval_and_stops(self):
        self.manager.start()
        self.assertTrue(hasattr(self.manager, '_focus_timer'))
        self.assertTrue(self.manager._focus_timer.isActive())
        self.assertLessEqual(self.manager._focus_timer.interval(), 20)
        self.manager.stop()
        self.assertFalse(self.manager._focus_timer.isActive())

    def test_success_uses_plain_black_masks_and_allowlist_input_flags(self):
        self.assertTrue(self.manager.start())
        self.assertTrue(self.manager.active)
        overlays = self.manager._overlays
        self.assertEqual(len(overlays), 2)
        allowed, denied = overlays
        self.assertTrue(allowed.allowed)
        self.assertFalse(denied.allowed)
        self.assertTrue(allowed.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(allowed.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertFalse(denied.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(allowed.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertFalse(denied.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertEqual(denied.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        for overlay in overlays:
            self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
            self.assertEqual(overlay.grab().toImage().pixelColor(10, 10).name(), '#000000')
        self.assertEqual([call.args[1] for call in self.mocks[2].call_args_list], [True, False])
        recovered = Mock()
        self.manager.recoveryRequested.connect(recovered)
        denied.mousePressEvent(None)
        recovered.assert_called_once()

    def test_capture_failure_retains_all_black_covers_for_root_fallback(self):
        self.mocks[2].return_value = False
        errors = []
        self.manager.failed.connect(errors.append)
        self.assertFalse(self.manager.start())
        self.assertTrue(self.manager.active)
        self.assertEqual(len(self.manager._overlays), 2)
        self.assertTrue(all(overlay.isVisible() for overlay in self.manager._overlays))
        self.assertEqual(len(errors), 1)

    def test_reconcile_failure_retains_old_and_new_covers(self):
        self.manager.start()
        old = list(self.manager._overlays)
        self.mocks[2].return_value = False
        self.manager.reconcile_screens()
        self.assertEqual(len(self.manager._overlays), 4)
        self.assertTrue(all(overlay.isVisible() for overlay in self.manager._overlays))
        self.assertTrue(all(overlay in self.manager._overlays for overlay in old))

    def test_reconcile_shows_all_new_covers_before_disposing_old(self):
        self.manager.start()
        old = list(self.manager._overlays)
        original_dispose = self.manager._dispose

        def dispose(overlays):
            self.assertEqual(overlays, old)
            self.assertTrue(all(overlay.isVisible() for overlay in old))
            self.assertTrue(all(overlay.isVisible() for overlay in self.manager._overlays))
            self.assertTrue(all(overlay not in old for overlay in self.manager._overlays))
            original_dispose(overlays)

        with patch.object(self.manager, '_dispose', side_effect=dispose):
            self.manager.reconcile_screens()

    def test_hotplug_defaults_to_denied_and_updates_geometry(self):
        self.manager.start()
        self.screens.append(FakeScreen('unknown', 1280))
        self.screens[0].rect = QRect(0, 0, 800, 600)
        self.manager.reconcile_screens()
        self.assertEqual(len(self.manager._overlays), 3)
        self.assertFalse(self.manager._overlays[-1].allowed)
        self.assertEqual(self.manager._overlays[0].geometry(), QRect(0, 0, 800, 600))

    def test_missing_allowed_and_zero_display_keep_old_covers_until_fallback(self):
        self.manager.start()
        previous = list(self.manager._overlays)
        fallback = Mock()
        self.manager.fallbackRequested.connect(fallback)
        self.screens[:] = [self.screens[1]]
        self.manager.reconcile_screens()
        self.assertTrue(all(overlay.isVisible() for overlay in previous))
        self.assertTrue(self.manager.active)
        fallback.assert_called_once()
        self.screens.clear()
        self.manager.reconcile_screens()
        self.assertEqual(fallback.call_count, 2)
        self.assertTrue(all(overlay.isVisible() for overlay in previous))

    def test_no_current_allowed_screen_refuses_start(self):
        self.manager._cfg['remote_allowed_screen_ids'] = ['offline']
        self.assertFalse(self.manager.start())
        self.assertFalse(self.manager.active)
        self.assertEqual(self.manager._overlays, [])

    def test_update_allowlist_resets_affinity_and_stop_is_idempotent(self):
        self.manager.start()
        previous = list(self.manager._overlays)
        self.mocks[2].reset_mock()
        self.manager.update_allowed(['two'])
        self.assertEqual(self.manager._cfg['remote_allowed_screen_ids'], ['two'])
        self.assertEqual([overlay.allowed for overlay in self.manager._overlays], [False, True])
        self.assertEqual([call.args[1] for call in self.mocks[2].call_args_list], [False, True])
        self.assertTrue(all(not overlay.isVisible() for overlay in previous))
        current = list(self.manager._overlays)
        self.manager.stop()
        self.manager.stop()
        self.assertFalse(self.manager.active)
        self.assertTrue(all(not overlay.isVisible() for overlay in current))
        self.assertFalse(self.manager._topmost_timer.isActive())

    def test_recovery_window_stays_above_covers_without_periodic_focus_stealing(self):
        self.manager.start()
        dialog = Mock()
        dialog.isVisible.return_value = True
        self.manager.set_recovery_window(dialog)
        dialog.activateWindow.assert_called_once()
        dialog.reset_mock()
        self.manager._enforce_topmost()
        dialog.raise_.assert_called_once()
        dialog.activateWindow.assert_not_called()
        self.manager.set_recovery_window(None)
        dialog.reset_mock()
        self.manager._enforce_topmost()
        dialog.raise_.assert_not_called()

    def test_repeated_start_does_not_claim_failed_capture_is_ready(self):
        self.mocks[2].return_value = False
        self.assertFalse(self.manager.start())
        self.assertFalse(self.manager.start())

    def test_denied_cover_consumes_keyboard_and_ime(self):
        self.manager.start()
        denied = self.manager._overlays[1]
        key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, 'a')
        key.ignore()
        denied.keyPressEvent(key)
        self.assertTrue(key.isAccepted())
        ime = QInputMethodEvent()
        ime.setCommitString('secret')
        ime.ignore()
        denied.inputMethodEvent(ime)
        self.assertTrue(ime.isAccepted())

    def test_denied_foreground_is_guarded_immediately_on_start_and_reconcile(self):
        self.mocks[5].return_value = (999, 2)
        self.mocks[6].side_effect = lambda hwnd: 2
        with patch.object(remote.PrivacyOverlay, 'activateWindow') as activate, patch.object(
                remote.PrivacyOverlay, 'setFocus') as focus:
            self.assertTrue(self.manager.start())
            activate.assert_called_once()
            focus.assert_called_once()
            activate.reset_mock()
            focus.reset_mock()
            self.manager.reconcile_screens()
            activate.assert_called_once()
            focus.assert_called_once()

    def test_allowed_foreground_and_already_focused_mask_do_not_steal_focus(self):
        self.manager.start()
        self.mocks[5].return_value = (999, 1)
        self.mocks[6].return_value = 2
        denied = self.manager._overlays[1]
        with patch.object(denied, 'activateWindow') as activate, patch.object(denied, 'setFocus') as focus:
            self.manager._enforce_topmost()
            activate.assert_not_called()
            focus.assert_not_called()
            self.mocks[5].return_value = (int(denied.winId()), 2)
            self.manager._enforce_topmost()
            activate.assert_not_called()

    def test_visible_recovery_is_exempt_from_denied_foreground_guard(self):
        self.manager.start()
        dialog = Mock()
        dialog.isVisible.return_value = True
        self.manager.set_recovery_window(dialog)
        self.mocks[5].return_value = (999, 2)
        self.mocks[6].return_value = 2
        with patch.object(remote.PrivacyOverlay, 'activateWindow') as activate:
            self.manager._enforce_topmost()
            activate.assert_not_called()

    def test_unknown_foreground_does_not_activate_denied_cover(self):
        self.manager.start()
        self.mocks[5].return_value = (999, 0)
        with patch.object(remote.PrivacyOverlay, 'activateWindow') as activate:
            self.manager._enforce_topmost()
            activate.assert_not_called()

    def test_already_focused_retained_mask_does_not_switch_to_another_cover(self):
        self.manager.start()
        self.mocks[2].return_value = False
        self.manager.reconcile_screens()
        focused = self.manager._overlays[-1]
        self.mocks[5].return_value = (int(focused.winId()), 2)
        self.mocks[6].return_value = 2
        with patch.object(remote.PrivacyOverlay, 'activateWindow') as activate:
            self.manager._enforce_topmost()
            activate.assert_not_called()


class NativeAffinityTests(unittest.TestCase):
    def test_foreground_monitor_helpers_preserve_pointer_sized_handles(self):
        foreground = Mock(return_value=0x123456789)
        monitor = Mock(return_value=0x234567891)
        user32 = Mock(GetForegroundWindow=foreground, MonitorFromWindow=monitor)
        with patch.object(remote.sys, 'platform', 'win32'), patch.object(
                remote.ctypes, 'windll', Mock(user32=user32), create=True):
            self.assertEqual(remote.foreground_monitor(), (0x123456789, 0x234567891))
        self.assertEqual(foreground.restype, remote.ctypes.c_void_p)
        self.assertEqual(monitor.restype, remote.ctypes.c_void_p)
        self.assertEqual(monitor.argtypes[0], remote.ctypes.c_void_p)
        self.assertEqual(monitor.call_args.args[0].value, 0x123456789)
        self.assertEqual(monitor.call_args.args[1], 0)

    def test_unknown_native_foreground_does_not_query_a_monitor(self):
        foreground = Mock(return_value=0)
        monitor = Mock()
        user32 = Mock(GetForegroundWindow=foreground, MonitorFromWindow=monitor)
        with patch.object(remote.sys, 'platform', 'win32'), patch.object(
                remote.ctypes, 'windll', Mock(user32=user32), create=True):
            self.assertEqual(remote.foreground_monitor(), (0, 0))
        monitor.assert_not_called()

    def test_supported_windows_uses_exclusion_and_reset_with_pointer_safe_signature(self):
        native = Mock(return_value=1)
        with patch.object(remote.sys, 'platform', 'win32'), patch.object(
                remote.sys, 'getwindowsversion', return_value=Mock(build=19041), create=True), patch.object(
                remote.ctypes, 'windll', Mock(user32=Mock(SetWindowDisplayAffinity=native)), create=True):
            self.assertTrue(remote.set_capture_exclusion(0x123456789, True))
            self.assertTrue(remote.set_capture_exclusion(0x123456789, False))
        self.assertEqual([call.args[1] for call in native.call_args_list], [0x11, 0])
        self.assertEqual(native.call_args_list[0].args[0].value, 0x123456789)
        self.assertEqual(native.argtypes[0], remote.ctypes.c_void_p)

    def test_old_windows_never_uses_monitor_affinity_fallback(self):
        native = Mock()
        with patch.object(remote.sys, 'platform', 'win32'), patch.object(
                remote.sys, 'getwindowsversion', return_value=Mock(build=18363), create=True), patch.object(
                remote.ctypes, 'windll', Mock(user32=Mock(SetWindowDisplayAffinity=native)), create=True):
            self.assertFalse(remote.set_capture_exclusion(10, True))
        native.assert_not_called()

    def test_failed_native_call_is_not_reported_as_success(self):
        native = Mock(return_value=0)
        with patch.object(remote.sys, 'platform', 'win32'), patch.object(
                remote.sys, 'getwindowsversion', return_value=Mock(build=19041), create=True), patch.object(
                remote.ctypes, 'windll', Mock(user32=Mock(SetWindowDisplayAffinity=native)), create=True):
            self.assertFalse(remote.set_capture_exclusion(10, True))


if __name__ == '__main__':
    unittest.main()
