"""UU mobile text packets must not be interpreted as physical Ctrl shortcuts."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication
from widgets import PasswordEdit
from input_diagnostics import InputProbe

APP = QApplication.instance() or QApplication([])


def send(edit, char, modifiers=Qt.KeyboardModifier.NoModifier, native=0xE7):
    event = QKeyEvent(QEvent.Type.KeyPress, ord(char.upper()), modifiers,
                      0, native, 0, char, False, 1)
    QApplication.sendEvent(edit, event)


class UnicodePacketTests(unittest.TestCase):
    def test_ctrl_between_two_unicode_as_does_not_select_the_first(self):
        edit = PasswordEdit()
        try:
            send(edit, 'a')
            send(edit, 'a', Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(edit.text(), 'aa')
            self.assertFalse(edit.hasSelectedText())
        finally:
            edit.deleteLater()

    def test_diagnostic_standard_path_matches_password_packet_handling(self):
        records = []
        edit = InputProbe(records.append)
        try:
            send(edit, 'a')
            send(edit, 'a', Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(edit.text(), 'aa')
            self.assertIn('mods=', records[-1])
        finally:
            edit.deleteLater()

    def test_real_physical_ctrl_a_still_selects_all(self):
        edit = PasswordEdit()
        try:
            edit.setText('previous')
            send(edit, 'a', Qt.KeyboardModifier.ControlModifier, native=0x41)
            self.assertTrue(edit.hasSelectedText())
            send(edit, 'b')
            self.assertEqual(edit.text(), 'b')
        finally:
            edit.deleteLater()

    def test_normalized_packet_acceptance_is_returned_to_original_event(self):
        edit = PasswordEdit()
        try:
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier,
                              0, 0xE7, 0, 'a', False, 1)
            event.ignore()
            edit.keyPressEvent(event)
            self.assertTrue(event.isAccepted())
            self.assertEqual(edit.text(), 'a')
        finally:
            edit.deleteLater()

    def test_unicode_modifiers_do_not_change_case_spaces_or_repeated_digits(self):
        edit = PasswordEdit()
        try:
            for char in 'Aa 1122!':
                send(edit, char, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
            self.assertEqual(edit.text(), 'Aa 1122!')
        finally:
            edit.deleteLater()
