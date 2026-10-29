import os
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtGui import QInputMethodEvent, QKeyEvent
from PyQt6.QtWidgets import QApplication, QLineEdit

import auth
import blind

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class PasswordEditorTests(unittest.TestCase):
    def setUp(self):
        self.state = blind.BlindState({'password_hash': auth.hash_password('1122')})
        self.overlay = blind.BlindOverlay(QRect(0, 0, 800, 600), self.state,
                                          {'screensaver_type': 'none'})

    def tearDown(self):
        self.overlay.deleteLater()
        self.state.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def editor(self):
        fields = self.overlay.findChildren(QLineEdit)
        self.assertEqual(len(fields), 1, 'Use one standard password editor per overlay')
        return fields[0]

    def commit(self, field, text, start=0, length=0):
        event = QInputMethodEvent()
        event.setCommitString(text, start, length)
        QApplication.sendEvent(field, event)

    def test_standard_editor_commits_repeated_digits_once_and_unlocks(self):
        edit = self.editor()
        unlocked = Mock()
        self.state.unlocked.connect(unlocked)
        self.state.show_password_input()
        for ch in '112':
            self.commit(edit, ch)
        self.assertEqual(self.state.password_buffer, '112')
        unlocked.assert_not_called()
        self.commit(edit, '2')
        unlocked.assert_called_once()
        self.assertEqual(edit.echoMode(), QLineEdit.EchoMode.Password)

    def test_preedit_is_not_a_password_and_replacement_is_not_appended(self):
        edit = self.editor()
        self.state.show_password_input()
        QApplication.sendEvent(edit, QInputMethodEvent('composing', []))
        self.assertEqual(self.state.password_buffer, '')
        self.commit(edit, 'ab')
        self.commit(edit, 'C', -1, 1)
        self.assertEqual(self.state.password_buffer, 'aC')

    def test_mirrors_do_not_emit_additional_commits(self):
        other = blind.BlindOverlay(QRect(800, 0, 800, 600), self.state,
                                   {'screensaver_type': 'none'})
        try:
            self.state.show_password_input()
            self.commit(self.editor(), 'Aa!!')
            self.assertEqual(self.state.password_buffer, 'Aa!!')
            self.assertEqual(other.findChild(QLineEdit).text(), 'Aa!!')
            self.commit(other.findChild(QLineEdit), 'x')
            self.assertEqual(self.state.password_buffer, 'Aa!!x')
        finally:
            other.deleteLater()

    def test_first_ime_commit_only_wakes_and_following_commit_counts(self):
        self.editor()
        self.commit(self.overlay, 'a')
        self.assertTrue(self.state.showing_password)
        self.assertEqual(self.state.password_buffer, '')
        self.commit(self.editor(), 'b')
        self.assertEqual(self.state.password_buffer, 'b')

    def test_held_wake_key_does_not_enter_auto_repeats(self):
        edit = self.editor()
        self.overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_1,
                                             Qt.KeyboardModifier.NoModifier, '1'))
        QApplication.sendEvent(edit, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_1,
                                               Qt.KeyboardModifier.NoModifier, '1', True))
        self.assertEqual(self.state.password_buffer, '')
        QApplication.sendEvent(edit, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_1,
                                               Qt.KeyboardModifier.NoModifier, '1'))
        QApplication.sendEvent(edit, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_1,
                                               Qt.KeyboardModifier.NoModifier, '1'))
        self.assertEqual(self.state.password_buffer, '1')

    def test_keyboard_backspace_enter_and_escape_keep_existing_behavior(self):
        edit = self.editor()
        self.state.show_password_input()
        self.commit(edit, 'aa!')
        for key, text in [(Qt.Key.Key_Backspace, ''), (Qt.Key.Key_Return, '\r')]:
            QApplication.sendEvent(edit, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))
        self.assertTrue(self.state.wrong)
        self.assertEqual(edit.text(), '')
        QApplication.sendEvent(edit, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(self.state.showing_password)
