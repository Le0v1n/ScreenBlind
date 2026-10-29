"""Regression tests: run with python -m unittest discover -s tests -v."""
import ctypes
import ast
import os
from pathlib import Path
import tempfile
import unittest
import uuid
import winreg
import string
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QCoreApplication, QEvent, Qt, QRect
from PyQt6.QtGui import QKeySequence, QKeyEvent
from PyQt6.QtWidgets import QApplication

import auth
import blind
import hotkeys
import main
import settings
import startup
import i18n
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
        self.startup_patch = patch.object(startup, 'is_enabled', return_value=False)
        self.startup_patch.start()
        self.window = main.MainWindow()

    def tearDown(self):
        self.window._tray.hide()
        self.window.hide()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.hotkeys_patch.stop()
        self.startup_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_close_hides_and_tray_double_click_restores(self):
        self.window.show()
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.window._on_tray_activated(main.QSystemTrayIcon.ActivationReason.DoubleClick)
        self.assertTrue(self.window.isVisible())

    def test_startup_and_hotkeys_are_disabled_by_default(self):
        self.assertFalse(self.window._startup_cb.isChecked())
        for edit in self.window._shortcut_edits.values():
            self.assertTrue(edit.keySequence().isEmpty())
        self.window._hotkeys.configure.assert_called_once_with({'lock': '', 'settings': '', 'recovery': ''})

    def test_language_switch_updates_ui_and_tray_and_preserves_drafts(self):
        w = self.window
        w._security_tab._pw1.setText('draft-only')
        w._security_tab._pw2.setText('draft-only')
        w._security_tab._show_cb.setChecked(True)
        w._shortcut_edits['lock'].setKeySequence(QKeySequence('Ctrl+Alt+B'))
        w._monitors_tab._items[0][0].setCheckState(Qt.CheckState.Checked)
        with patch.object(startup, 'set_enabled') as startup_write:
            for language, tab, action in [('en', 'General', 'Open settings'), ('zh_CN', '通用', '打开设置'), ('en', 'General', 'Open settings')]:
                w._language_combo.setCurrentIndex(w._language_combo.findData(language))
                self.assertEqual(w._tabs.tabText(3).strip(), tab)
                self.assertEqual(w._settings_action.text(), action)
                self.assertEqual(w._security_tab._pw1.text(), 'draft-only')
                self.assertEqual(w._security_tab._pw2.text(), 'draft-only')
                self.assertTrue(w._security_tab._show_cb.isChecked())
                self.assertEqual(w._shortcut_edits['lock'].keySequence().toString(), 'Ctrl+Alt+B')
                self.assertEqual(w._monitors_tab.selected_indices(), [0])
                self.assertEqual(settings.load()['language'], language)
                self.assertEqual(w._cfg['lock_hotkey'], '')  # Unsaved drafts stay unsaved.
                self.assertEqual(w._language_combo.currentData(), language)
            startup_write.assert_not_called()

    def test_saved_language_restores_on_next_launch(self):
        self.window._language_combo.setCurrentIndex(self.window._language_combo.findData('en'))
        restored = main.MainWindow()
        try:
            self.assertEqual(restored._tabs.tabText(3).strip(), 'General')
            self.assertEqual(restored._language_combo.currentData(), 'en')
        finally:
            restored._tray.hide()
            restored.deleteLater()

    def test_warning_dialog_uses_selected_language(self):
        self.window._language_combo.setCurrentIndex(self.window._language_combo.findData('en'))
        with patch.object(main.QMessageBox, 'warning') as warning:
            self.window._on_lock_clicked()
            self.assertEqual(warning.call_args.args[1], 'No password')


    def test_startup_toggle_and_failure_restore_checkbox(self):
        with patch.object(startup, 'set_enabled') as write:
            self.window._startup_cb.setChecked(True)
            write.assert_called_once_with(True)
        with patch.object(startup, 'set_enabled', side_effect=PermissionError), \
             patch.object(main.QMessageBox, 'warning') as warning:
            self.window._startup_cb.setChecked(False)
            self.assertTrue(self.window._startup_cb.isChecked())
            warning.assert_called_once()

    def test_idle_screensaver_toggle_preserves_timeout_and_persists(self):
        tab = self.window._screensaver_tab
        tab._timeout_spin.setValue(300)
        tab._idle_enabled.setChecked(False)
        self.assertFalse(tab._timeout_spin.isEnabled())
        self.assertFalse(settings.load()['screensaver_enabled'])
        self.assertEqual(settings.load()['idle_timeout'], 300)
        restored = main.ScreensaverTab(settings.load())
        self.assertFalse(restored._idle_enabled.isChecked())
        self.assertFalse(restored._timeout_spin.isEnabled())
        tab._idle_enabled.setChecked(True)
        self.assertTrue(tab._timeout_spin.isEnabled())
        self.assertTrue(settings.load()['screensaver_enabled'])
        self.assertEqual(settings.load()['idle_timeout'], 300)
        restored.deleteLater()

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
        w.show()
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
            self.assertFalse(w.isVisible())
            self.assertTrue(w._tray.isVisible())
            self.assertIsNone(w._blind_manager)
            # A new lock can start from the tray without reopening settings.
            w._on_lock_clicked()
            self.assertEqual(manager.call_count, 2)
            w._on_unlocked()
            self.assertFalse(w.isVisible())
            w._on_tray_activated(main.QSystemTrayIcon.ActivationReason.DoubleClick)
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
    def test_typing_exact_password_unlocks_without_enter(self):
        state = blind.BlindState({'password_hash': auth.hash_password('1024')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        for char in '102':
            state.handle_char(char)
            unlocked.assert_not_called()
            self.assertFalse(state.wrong)
        state.handle_char('4')
        unlocked.assert_called_once()
        self.assertEqual(state.password_buffer, '')
        state.handle_char('4')
        state.attempt_unlock()
        unlocked.assert_called_once()
        state.deleteLater()

    def test_incorrect_input_can_be_corrected_without_enter(self):
        state = blind.BlindState({'password_hash': auth.hash_password('1024')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        for char in '1025':
            state.handle_char(char)
        self.assertEqual(state.password_buffer, '1025')
        self.assertFalse(state.wrong)
        unlocked.assert_not_called()
        state.handle_backspace()
        state.handle_char('4')
        unlocked.assert_called_once()
        state.deleteLater()

    def test_backspace_to_exact_match_unlocks(self):
        state = blind.BlindState({'password_hash': auth.hash_password('1024')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        state.handle_char('10240')  # A complete multi-character input event.
        unlocked.assert_not_called()
        state.handle_backspace()
        unlocked.assert_called_once()
        state.deleteLater()

    def test_first_printable_key_only_opens_prompt(self):
        state = blind.BlindState({'password_hash': auth.hash_password('1024')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        overlay = blind.BlindOverlay(QRect(0, 0, 800, 600), state, {'screensaver_type': 'none'})
        try:
            overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, ord('1'), Qt.KeyboardModifier.NoModifier, '1'))
            self.assertTrue(state.showing_password)
            self.assertEqual(state.password_buffer, '')
            unlocked.assert_not_called()
            for char in '1024':
                event = QKeyEvent(QEvent.Type.KeyPress, ord(char), Qt.KeyboardModifier.NoModifier, char)
                overlay.keyPressEvent(event)
                if char != '4':
                    unlocked.assert_not_called()
            unlocked.assert_called_once()
        finally:
            overlay.deleteLater()
            state.deleteLater()

    def test_wake_keys_open_empty_prompt_before_password_input(self):
        for key, text in ((Qt.Key.Key_Space, ' '), (Qt.Key.Key_Escape, '\x1b'),
                          (Qt.Key.Key_Return, '\r'), (Qt.Key.Key_Enter, '\r'),
                          (Qt.Key.Key_A, 'a'), (Qt.Key.Key_1, '1'), (Qt.Key.Key_Exclam, '!')):
            with self.subTest(key=key):
                state = blind.BlindState({'password_hash': auth.hash_password('1024')})
                unlocked = Mock()
                state.unlocked.connect(unlocked)
                overlay = blind.BlindOverlay(QRect(0, 0, 800, 600), state, {'screensaver_type': 'none'})
                try:
                    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))
                    self.assertTrue(state.showing_password)
                    self.assertEqual(state.password_buffer, '')
                    self.assertFalse(state.wrong)
                    unlocked.assert_not_called()
                    for char in '1024':
                        overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, ord(char), Qt.KeyboardModifier.NoModifier, char))
                    unlocked.assert_called_once()
                finally:
                    overlay.deleteLater()
                    state.deleteLater()

    def test_mouse_wake_keeps_the_first_password_character(self):
        state = blind.BlindState({'password_hash': auth.hash_password('1024')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        overlay = blind.BlindOverlay(QRect(0, 0, 800, 600), state, {'screensaver_type': 'none'})
        try:
            overlay.mousePressEvent(None)
            for char in '1024':
                overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, ord(char), Qt.KeyboardModifier.NoModifier, char))
                if char == '1':
                    self.assertEqual(state.password_buffer, '1')
            unlocked.assert_called_once()
        finally:
            overlay.deleteLater()
            state.deleteLater()

    def test_space_after_prompt_opens_is_a_valid_password_character(self):
        state = blind.BlindState({'password_hash': auth.hash_password(' 1024')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        overlay = blind.BlindOverlay(QRect(0, 0, 800, 600), state, {'screensaver_type': 'none'})
        try:
            overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, ' '))
            for char in ' 1024':
                overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, ord(char), Qt.KeyboardModifier.NoModifier, char))
            unlocked.assert_called_once()
        finally:
            overlay.deleteLater()
            state.deleteLater()

    def test_longer_password_does_not_unlock_on_prefix(self):
        state = blind.BlindState({'password_hash': auth.hash_password('10240')})
        unlocked = Mock()
        state.unlocked.connect(unlocked)
        for char in '1024':
            state.handle_char(char)
        unlocked.assert_not_called()
        state.handle_char('0')
        unlocked.assert_called_once()
        state.deleteLater()

    def test_disabled_screensaver_never_arms_timer_or_hides_password(self):
        state = blind.BlindState({'screensaver_enabled': False, 'idle_timeout': 10})
        state.show_password_input()
        state.start_idle_timer()
        self.assertFalse(state._idle_timer.isActive())
        state.on_mouse_move()
        self.assertFalse(state._idle_timer.isActive())
        state._on_idle()  # Even an already queued timeout must be harmless.
        self.assertFalse(state.in_screensaver)
        self.assertTrue(state.showing_password)
        state.deleteLater()

    def test_existing_settings_keep_idle_screensaver_enabled(self):
        state = blind.BlindState({'idle_timeout': 120})
        state.start_idle_timer()
        self.assertTrue(state._idle_timer.isActive())
        self.assertEqual(state._idle_timer.interval(), 120000)
        state.deleteLater()

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


class StartupTests(unittest.TestCase):
    def test_enable_disable_in_isolated_registry_key(self):
        # Exercise the real registry API without modifying the user's Run key.
        key_path = r'Software\ScreenBlind-Test-' + uuid.uuid4().hex
        with patch.object(startup, 'RUN_KEY', key_path):
            try:
                self.assertFalse(startup.is_enabled())
                startup.set_enabled(True)
                self.assertTrue(startup.is_enabled())
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    command, value_type = winreg.QueryValueEx(key, startup.VALUE_NAME)
                self.assertEqual(value_type, winreg.REG_SZ)
                self.assertEqual(command, startup.startup_command())
                self.assertTrue(command.endswith(' --startup'))
                startup.set_enabled(False)
                self.assertFalse(startup.is_enabled())
                startup.set_enabled(False)  # Already disabled is harmless.
            finally:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)

    def test_packaged_command_quotes_executable_with_spaces(self):
        with patch.object(startup.sys, 'frozen', True, create=True), \
             patch.object(startup.sys, 'executable', r'C:\My Apps\ScreenBlind.exe'):
            self.assertEqual(startup.startup_command(), '"C:\\My Apps\\ScreenBlind.exe" --startup')


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        i18n.configure_language(APP, 'system')

    def test_translation_placeholders_match_english_sources(self):
        formatter = string.Formatter()
        for english, chinese in i18n.ZH_CN.items():
            source_fields = {field for _, field, _, _ in formatter.parse(english) if field is not None}
            translated_fields = {field for _, field, _, _ in formatter.parse(chinese) if field is not None}
            self.assertEqual(source_fields, translated_fields, english)

    def test_all_application_strings_have_a_chinese_translation(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ('main.py', 'blind.py', 'animations.py', 'hotkeys.py', 'instance.py', 'displays.py', 'clocks.py', 'remote_ui.py', 'input_diagnostics.py'):
            for node in ast.walk(ast.parse((root / filename).read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr':
                    self.assertIsInstance(node.args[0], ast.Constant)
                    self.assertIn(node.args[0].value, i18n.ZH_CN, f'{filename}:{node.lineno}')

    def test_system_language_falls_back_to_english_outside_chinese(self):
        from PyQt6.QtCore import QLocale
        with patch.object(i18n.QLocale, 'system', return_value=QLocale('de_DE')):
            self.assertEqual(i18n.resolve_language('system'), 'en')
        with patch.object(i18n.QLocale, 'system', return_value=QLocale('zh_CN')):
            self.assertEqual(i18n.resolve_language('system'), 'zh_CN')

    def test_dynamic_errors_dates_and_formatting_follow_language(self):
        for language, expected in [('en', 'Display 2'), ('zh_CN', '显示器 2')]:
            i18n.configure_language(APP, language)
            self.assertEqual(i18n.tr('Display {number}', number=2), expected)
        i18n.configure_language(APP, 'en')
        with self.assertRaisesRegex(ValueError, 'Include Ctrl or Alt'):
            hotkeys.parse_hotkey('L')
        i18n.configure_language(APP, 'zh_CN')
        with self.assertRaisesRegex(ValueError, 'Ctrl 或 Alt'):
            hotkeys.parse_hotkey('L')


if __name__ == '__main__':
    unittest.main()
