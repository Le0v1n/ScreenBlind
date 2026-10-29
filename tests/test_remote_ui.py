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
                tab.set_active(False)
                self.assertTrue(tab.screen_list.isEnabled())
            finally:
                tab.deleteLater()
