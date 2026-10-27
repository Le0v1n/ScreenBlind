"""Clock preferences, movement and common rendering without locking the desktop."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QDateTime, QEvent, QRect, QRectF
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

import blind
import clocks
import main
import settings

APP = QApplication.instance() or QApplication([])


class ClockTests(unittest.TestCase):
    def tearDown(self):
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_old_settings_keep_clock_fixed_and_classic(self):
        state = blind.BlindState({})
        try:
            self.assertFalse(state._drift_timer.isActive())
            state._pick_drift_target()
            self.assertEqual((state.clock_rel_x, state.clock_rel_y), (0.5, 0.38))
        finally:
            state.deleteLater()

    def test_enabled_movement_repositions_and_rearms_then_respects_disable(self):
        cfg = {'clock_moving': True}
        state = blind.BlindState(cfg)
        try:
            self.assertTrue(state._drift_timer.isActive())
            with patch.object(blind.random, 'uniform', side_effect=[0.25, 0.20]):
                state._pick_drift_target()
            self.assertEqual((state.clock_rel_x, state.clock_rel_y), (0.25, 0.20))
            self.assertTrue(state._drift_timer.isActive())
            cfg['clock_moving'] = False
            state._pick_drift_target()
            self.assertFalse(state._drift_timer.isActive())
            self.assertEqual((state.clock_rel_x, state.clock_rel_y), (0.25, 0.20))
        finally:
            state.deleteLater()

    def test_style_and_movement_round_trip_in_settings(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder):
            tab = main.ScreensaverTab(settings.load())
            try:
                self.assertFalse(tab._clock_moving.isChecked())
                self.assertEqual(tab._clock_style.currentData(), 'classic')
                tab._clock_moving.setChecked(True)
                for style in clocks.CLOCK_STYLES:
                    tab._clock_style.setCurrentIndex(tab._clock_style.findData(style))
                    self.assertEqual(settings.load()['clock_style'], style)
                restored = main.ScreensaverTab(settings.load())
                try:
                    self.assertTrue(restored._clock_moving.isChecked())
                    self.assertEqual(restored._clock_style.currentData(), 'panel')
                    self.assertIs(restored._clock_preview._cfg, restored._cfg)
                finally:
                    restored.deleteLater()
            finally:
                tab.deleteLater()

    def test_moving_clock_stays_on_screen_and_above_password_prompt(self):
        for width, height in [(800, 600), (1920, 1080), (1080, 1920), (3840, 2160)]:
            rect = QRect(0, 0, width, height)
            for x in (0.2, 0.5, 0.8):
                for y in (0.15, 0.38, 0.58):
                    bounds = clocks.clock_bounds(rect, x, y)
                    self.assertGreaterEqual(bounds.left(), 20)
                    self.assertLessEqual(bounds.right(), width - 20)
                    self.assertGreaterEqual(bounds.top(), 52)
                    self.assertLessEqual(bounds.bottom(), height * 0.59)

    def test_styles_render_distinctly_and_unknown_style_falls_back(self):
        results = {}
        now = QDateTime.fromString('2026-10-27T20:24:16', 'yyyy-MM-ddTHH:mm:ss')
        for style in (*clocks.CLOCK_STYLES, 'unknown'):
            image = QImage(560, 240, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            try:
                clocks.draw_clock(painter, QRectF(20, 20, 520, 200), style, now)
            finally:
                painter.end()
            results[style] = bytes(image.constBits().asstring(image.sizeInBytes()))
        self.assertEqual(len(set(results[style] for style in clocks.CLOCK_STYLES)), 3)
        self.assertEqual(results['unknown'], results['classic'])

    def test_overlay_uses_selected_style_and_shared_renderer(self):
        state = blind.BlindState({})
        overlay = blind.BlindOverlay(QRect(0, 0, 800, 600), state,
                                     {'screensaver_type': 'none', 'clock_style': 'minimal'})
        try:
            with patch.object(blind, 'draw_clock') as render:
                overlay._draw_clock(None, QRect(0, 0, 800, 600))
            self.assertEqual(render.call_args.args[2], 'minimal')
        finally:
            overlay.deleteLater()
            state.deleteLater()
