import os
import tempfile
import unittest
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QDialog
import main
import auth

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class RemoteControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APPDATA=self.temp.name)
        self.env.start()
        self.hk = patch.object(main, 'GlobalHotkeys')
        self.hk.start()
        self.startup = patch.object(main.startup, 'is_enabled', return_value=False)
        self.startup.start()
        self.window = main.MainWindow()
        self.window._cfg['password_hash'] = auth.hash_password('1122')

    def tearDown(self):
        self.window._tray.hide()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.startup.stop()
        self.hk.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_normal_startup_does_not_enter_remote_mode(self):
        self.assertTrue(hasattr(self.window, '_remote_manager'))
        self.assertIsNone(self.window._remote_manager)
        self.assertIn('recovery', self.window._shortcut_edits)
        self.assertTrue(self.window._shortcut_edits['recovery'].keySequence().isEmpty())

    def test_lock_hotkey_adapts_to_remote_mode_without_removing_masks(self):
        manager = Mock()
        self.window._remote_manager = manager
        with patch.object(self.window, '_request_remote_recovery') as recovery, \
                patch.object(self.window, '_on_lock_clicked') as lock:
            self.window._on_lock_hotkey()
            recovery.assert_called_once()
            lock.assert_not_called()
            manager.stop.assert_not_called()
            self.assertIs(self.window._remote_manager, manager)

    def test_lock_hotkey_normally_locks_and_does_not_unlock_existing_lock(self):
        with patch.object(self.window, '_start_lock') as lock:
            self.window._on_lock_hotkey()
            lock.assert_called_once()
            self.window._blind_manager = Mock()
            self.window._on_lock_hotkey()
            lock.assert_called_once()

    def test_rejected_recovery_keeps_masks_and_does_not_open_settings(self):
        self.assertTrue(hasattr(main, 'RecoveryDialog'))
        manager = Mock()
        self.window._remote_manager = manager
        with patch.object(main, 'RecoveryDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window.show_normal()
            manager.stop.assert_not_called()
            self.assertIs(self.window._remote_manager, manager)
            self.assertFalse(self.window.isVisible())

    def test_full_lock_is_installed_before_privacy_masks_are_removed(self):
        self.assertTrue(hasattr(self.window, '_remote_to_full_lock'))
        order = []
        remote = Mock()
        remote.stop.side_effect = lambda: order.append('remote-stop')
        self.window._remote_manager = remote
        with patch.object(main, 'BlindManager') as normal:
            normal.return_value.lock.side_effect = lambda **kw: order.append('normal-lock') or True
            self.window._remote_to_full_lock()
            self.assertEqual(order[:2], ['normal-lock', 'remote-stop'])
            self.assertTrue(normal.call_args.args[0]['lock_all_screens'])
            self.assertIsNone(self.window._remote_manager)
