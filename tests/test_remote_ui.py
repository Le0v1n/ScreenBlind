import os
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QDialog
import auth

APP = QApplication.instance() or QApplication([])


class RemoteUITests(unittest.TestCase):
    def test_mouse_filter_opt_in_persists_and_cannot_change_while_active(self):
        from remote_ui import RemoteTab
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder):
            cfg = {}
            tab = RemoteTab(cfg)
            try:
                self.assertFalse(tab.block_local_mouse.isChecked())
                self.assertFalse(tab.block_local_keyboard.isChecked())
                tab.block_local_mouse.setChecked(True)
                self.assertTrue(cfg['remote_block_local_mouse'])
                import settings
                self.assertTrue(settings.load()['remote_block_local_mouse'])
                tab.block_local_keyboard.setChecked(True)
                self.assertTrue(settings.load()['remote_block_local_keyboard'])
                tab.set_active(True)
                tab.block_local_mouse.setChecked(False)
                self.assertTrue(cfg['remote_block_local_mouse'])
                self.assertTrue(tab.block_local_mouse.isChecked())
                tab.block_local_keyboard.setChecked(False)
                self.assertTrue(cfg['remote_block_local_keyboard'])
                self.assertTrue(tab.block_local_keyboard.isChecked())
            finally:
                tab.deleteLater()

    def test_recovery_requires_password_and_clears_input(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('remote_ui'), 'Provide authenticated remote recovery UI')
        from remote_ui import RecoveryDialog
        dialog = RecoveryDialog({'password_hash': auth.hash_password('1122')})
        try:
            dialog.password.setText('wrong')
            QApplication.sendEvent(dialog.password, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                               Qt.KeyboardModifier.NoModifier, '\r'))
            self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.password.text(), '')
            dialog.password.setText('1122')
            QApplication.sendEvent(dialog.password, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                               Qt.KeyboardModifier.NoModifier, '\r'))
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.password.text(), '')
        finally:
            dialog.deleteLater()

    def test_active_mode_prevents_unauthenticated_allowlist_changes(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('remote_ui'))
        from remote_ui import RemoteTab
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder):
            tab = RemoteTab({})
            try:
                tab.set_active(True)
                self.assertFalse(tab.screen_list.isEnabled())
                self.assertFalse(tab.block_local_mouse.isEnabled())
                self.assertFalse(tab.block_local_keyboard.isEnabled())
                tab.set_active(False)
                self.assertTrue(tab.screen_list.isEnabled())
                self.assertTrue(tab.block_local_mouse.isEnabled())
                self.assertTrue(tab.block_local_keyboard.isEnabled())
            finally:
                tab.deleteLater()
