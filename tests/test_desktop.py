"""Regression tests: run with python -m unittest discover -s tests -v."""
import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication

import auth
import blind
import hotkeys
import main
import settings
from instance import InstanceGuard

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class HotkeyTests(unittest.TestCase):
    def setUp(self):
        self.native = Mock()
        self.native.RegisterHotKey.return_value = True
        self.patch = patch.object(ctypes, 'WinDLL', return_value=self.native)
        self.patch.start()
        self.manager = hotkeys.GlobalHotkeys(APP, {'lock': Mock(), 'settings': Mock()})

    def tearDown(self):
        self.manager.close()
        self.patch.stop()

    def test_parse_and_reject_unsafe_combinations(self):
        self.assertEqual(hotkeys.parse_hotkey('Ctrl+Alt+L'), (0x4003, ord('L')))
        self.assertIsNone(hotkeys.parse_hotkey(''))
        for text in ('L', 'Shift+L', 'Meta+L', 'Ctrl+F12', 'Ctrl+A, Ctrl+B'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                hotkeys.parse_hotkey(text)

    def test_conflict_retains_previous_bindings_and_cleans_partial_registration(self):
        self.manager.configure({'lock': 'Ctrl+Alt+L', 'settings': 'Ctrl+Alt+S'})
        previous = dict(self.manager._bindings)
        self.native.RegisterHotKey.side_effect = [True, False]
        with self.assertRaises(ValueError):
            self.manager.configure({'lock': 'Ctrl+Alt+A', 'settings': 'Ctrl+Alt+B'})
        self.assertEqual(self.manager._bindings, previous)
        self.assertEqual(self.native.UnregisterHotKey.call_count, 1)

    def test_swap_reuses_registration_and_disable_releases_all(self):
        self.manager.configure({'lock': 'Ctrl+Alt+L', 'settings': 'Ctrl+Alt+S'})
        self.manager.configure({'lock': 'Ctrl+Alt+S', 'settings': 'Ctrl+Alt+L'})
        self.assertEqual(self.native.RegisterHotKey.call_count, 2)
        self.manager.configure({'lock': '', 'settings': ''})
        self.assertEqual(len(self.manager._bindings), 0)
        self.assertEqual(self.native.UnregisterHotKey.call_count, 2)

    def test_duplicate_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.configure({'lock': 'Ctrl+Alt+L', 'settings': 'Alt+Ctrl+L'})
        self.native.RegisterHotKey.assert_not_called()

    def test_native_message_defers_action_to_event_loop(self):
        self.manager.configure({'lock': 'Ctrl+Alt+L'})
        msg = ctypes.wintypes.MSG()
        msg.message = 0x0312
        msg.wParam = next(iter(self.manager._actions))
        self.assertEqual(self.manager.nativeEventFilter(b'windows_dispatcher_MSG', ctypes.addressof(msg)), (True, 0))
        self.manager._callbacks['lock'].assert_not_called()
        APP.processEvents()
        self.manager._callbacks['lock'].assert_called_once()


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APPDATA=self.temp.name)
        self.env.start()
        self.hotkeys_patch = patch.object(main, 'GlobalHotkeys')
        self.hotkeys_patch.start()
        self.window = main.MainWindow()

    def tearDown(self):
        self.window._tray.hide()
        self.window.hide()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.hotkeys_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_close_hides_and_tray_double_click_restores(self):
        self.window.show()
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.window._on_tray_activated(main.QSystemTrayIcon.ActivationReason.DoubleClick)
        self.assertTrue(self.window.isVisible())

    def test_theme_password_and_shortcut_changes_share_current_settings(self):
        w = self.window
        w._cfg['password_hash'] = auth.hash_password('test-only')
        w._theme_combo.setCurrentIndex(1)
        w._shortcut_edits['lock'].setKeySequence(QKeySequence('Ctrl+Alt+B'))
        w._save_hotkeys()
        self.assertEqual(settings.load()['theme'], 'light')
        self.assertEqual(settings.load()['lock_hotkey'], 'Ctrl+Alt+B')
        self.assertTrue(auth.verify_password('test-only', settings.load()['password_hash']))
        self.assertEqual(APP.palette().window().color().name(), '#f5f7fc')
        w._theme_combo.setCurrentIndex(0)
        self.assertEqual(APP.palette().window().color().name(), '#10121b')

    def test_refresh_does_not_lose_checked_monitors(self):
        tab = self.window._monitors_tab
        tab._items[0][0].setCheckState(Qt.CheckState.Checked)
        for _ in range(3):
            tab.refresh()
        self.assertEqual(tab.selected_indices(), [0])
        self.assertEqual(settings.load()['locked_screens'], [0])

    def test_lock_is_not_reentered_and_settings_cannot_cover_overlay(self):
        w = self.window
        w._cfg['password_hash'] = auth.hash_password('test-only')
        w._monitors_tab._items[0][0].setCheckState(Qt.CheckState.Checked)
        with patch.object(main, 'BlindManager') as manager:
            manager.return_value.lock.return_value = True
            w._on_lock_clicked()
            w._on_lock_clicked()
            manager.assert_called_once()
            w.show_normal()
            self.assertFalse(w.isVisible())
            self.assertFalse(w._exit_action.isEnabled())
            w._on_unlocked()
            self.assertTrue(w._exit_action.isEnabled())
            self.assertTrue(w.isVisible())

    def test_lock_preconditions_show_settings_instead_of_hiding_errors(self):
        with patch.object(main.QMessageBox, 'warning') as warning:
            self.window._on_lock_clicked()
            self.assertTrue(self.window.isVisible())
            self.assertEqual(self.window._tabs.currentIndex(), 1)
            warning.assert_called_once()

    def test_failed_empty_lock_does_not_leave_app_in_locked_state(self):
        w = self.window
        w._cfg['password_hash'] = auth.hash_password('test-only')
        w._monitors_tab._items[0][0].setCheckState(Qt.CheckState.Checked)
        with patch.object(main, 'BlindManager') as manager:
            manager.return_value.lock.return_value = False
            w._on_lock_clicked()
            self.assertIsNone(w._blind_manager)
            self.assertTrue(w.isVisible())

    def test_capturing_shortcut_does_not_lock(self):
        w = self.window
        w.show()
        w._tabs.setCurrentWidget(w._general_tab)
        w._shortcut_edits['lock'].setFocus()
        APP.processEvents()
        with patch.object(w, '_start_lock') as lock:
            w._on_lock_clicked()
            lock.assert_not_called()


class LockTests(unittest.TestCase):
    def test_wrong_password_stays_locked_correct_password_unlocks(self):
        state = blind.BlindState({'password_hash': auth.hash_password('test-only')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        state.password_buffer = 'wrong'
        state.attempt_unlock()
        self.assertTrue(state.wrong)
        unlocked.assert_not_called()
        state.password_buffer = 'test-only'
        state.attempt_unlock()
        unlocked.assert_called_once()
        state.deleteLater()

    def test_disconnected_monitor_does_not_install_input_hooks(self):
        manager = blind.BlindManager({'locked_screens': [999, -1]})
        with patch.object(blind, '_install_kb_hook') as hook:
            self.assertFalse(manager.lock())
            hook.assert_not_called()
        manager.deleteLater()


class InstanceTests(unittest.TestCase):
    def test_second_launch_activates_first_and_exit_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            first = InstanceGuard(Path(folder))
            second = InstanceGuard(Path(folder))
            activated = Mock()
            first.activated.connect(activated)
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                APP.processEvents()
                activated.assert_called_once()
            finally:
                first.close()
                second.close()
            third = InstanceGuard(Path(folder))
            self.assertTrue(third.acquire())
            third.close()


if __name__ == '__main__':
    unittest.main()
