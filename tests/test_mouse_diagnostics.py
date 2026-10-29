import ctypes
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from mouse_diagnostics import MouseDiagnostics, MousePacket, MouseSampler

APP = QApplication.instance() or QApplication([])


class MouseDiagnosticTests(unittest.TestCase):
    def sampler(self):
        sampler = MouseSampler()
        sampler._api = MagicMock()
        sampler._api.CallNextHookEx.return_value = 123
        sampler._handle = 42
        sampler.active = True
        return sampler

    def test_every_flag_combination_is_forwarded_unchanged(self):
        sampler = self.sampler()
        for flags in range(4):
            packet = MousePacket(12345, -678, 999, flags, 876, 123)
            address = ctypes.addressof(packet)
            self.assertEqual(sampler._dispatch(0, 0x201, address), 123)
            sampler._api.CallNextHookEx.assert_called_with(42, 0, 0x201, address)
        self.assertEqual(len(sampler.counts), 4)
        self.assertNotIn('12345', sampler.summary())
        self.assertNotIn('-678', sampler.summary())
        self.assertIn('left_down injected=1 lower_integrity=0 count=1', sampler.summary())

    def test_negative_code_and_stopped_sampler_do_not_read_pointer(self):
        sampler = self.sampler()
        self.assertEqual(sampler._dispatch(-1, 0x200, 0), 123)
        sampler.active = False
        self.assertEqual(sampler._dispatch(0, 0x200, 0), 123)
        self.assertFalse(sampler.counts)

    def test_native_stop_releases_handle_and_callback(self):
        sampler = self.sampler()
        sampler._callback = object()
        sampler._api.UnhookWindowsHookEx.return_value = 1
        sampler.stop()
        sampler._api.UnhookWindowsHookEx.assert_called_once_with(42)
        self.assertIsNone(sampler._handle)
        self.assertIsNone(sampler._callback)
        self.assertFalse(sampler.active)
        sampler.stop()
        sampler._api.UnhookWindowsHookEx.assert_called_once()

    def test_timeout_stops_hook_and_preserves_both_labeled_summaries(self):
        dialog = MouseDiagnostics()
        try:
            with patch.object(dialog.sampler, 'start', side_effect=lambda: setattr(dialog.sampler, 'active', True)), \
                    patch.object(dialog.sampler, 'stop', side_effect=lambda: setattr(dialog.sampler, 'active', False)) as stop:
                for phase in ('Sample local mouse', 'Sample phone UU'):
                    dialog.start_sample(phase)
                    self.assertTrue(dialog.timer.isActive())
                    self.assertFalse(dialog._buttons[0].isEnabled())
                    for _ in range(15):
                        dialog.tick()
                    self.assertFalse(dialog.timer.isActive())
                self.assertEqual(stop.call_count, 2)
                self.assertEqual(dialog.log.toPlainText().count('mouse events='), 2)
        finally:
            dialog.done(0)
            dialog.deleteLater()

    def test_close_stops_sampling_and_discards_metadata(self):
        dialog = MouseDiagnostics()
        try:
            dialog.sampler = self.sampler()
            dialog.sampler._api.UnhookWindowsHookEx.return_value = 1
            dialog.sampler.counts[('move', False, False)] = 10
            dialog.timer.start()
            dialog.done(0)
            self.assertFalse(dialog.timer.isActive())
            self.assertFalse(dialog.sampler.active)
            self.assertFalse(dialog.sampler.counts)
            self.assertEqual(dialog.log.toPlainText(), '')
        finally:
            dialog.deleteLater()

    def test_failed_install_keeps_controls_available(self):
        dialog = MouseDiagnostics()
        try:
            with patch.object(dialog.sampler, 'start', side_effect=OSError('test failure')):
                dialog.start_sample('Sample local mouse')
            self.assertFalse(dialog.timer.isActive())
            self.assertTrue(dialog._buttons[0].isEnabled())
            self.assertIn('test failure', dialog.status.text())
        finally:
            dialog.done(0)
            dialog.deleteLater()
