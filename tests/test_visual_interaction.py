"""Background-only blur and settings wheel regression checks."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox

import blind
from widgets import WheelSafeComboBox, WheelSafeSpinBox

APP = QApplication.instance() or QApplication([])


def wheel():
    return QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, -120),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


class WheelTests(unittest.TestCase):
    def tearDown(self):
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_closed_combo_ignores_wheel_even_when_focused_but_keyboard_works(self):
        combo = WheelSafeComboBox()
        combo.addItems(['one', 'two', 'three'])
        try:
            combo.setFocus()
            event = wheel()
            QApplication.sendEvent(combo, event)
            self.assertEqual(combo.currentIndex(), 0)
            self.assertFalse(event.isAccepted())
            QTest.keyClick(combo, Qt.Key.Key_Down)
            self.assertEqual(combo.currentIndex(), 1)
        finally:
            combo.deleteLater()

    def test_open_popup_keeps_normal_wheel_behavior(self):
        combo = WheelSafeComboBox()
        combo.addItems(['one', 'two'])
        try:
            with patch.object(combo.view(), 'isVisible', return_value=True), \
                 patch.object(QComboBox, 'wheelEvent') as normal:
                event = wheel()
                combo.wheelEvent(event)
                normal.assert_called_once_with(event)
        finally:
            combo.deleteLater()

    def test_spinbox_ignores_wheel_but_keeps_keys_and_explicit_values(self):
        spin = WheelSafeSpinBox()
        try:
            spin.setValue(10)
            event = wheel()
            QApplication.sendEvent(spin, event)
            self.assertEqual(spin.value(), 10)
            self.assertFalse(event.isAccepted())
            QTest.keyClick(spin, Qt.Key.Key_Up)
            self.assertEqual(spin.value(), 11)
            spin.setValue(20)
            self.assertEqual(spin.value(), 20)
        finally:
            spin.deleteLater()


class BlurTests(unittest.TestCase):
    def setUp(self):
        self.state = blind.BlindState({'screensaver_type': 'slideshow'})
        self.state.in_screensaver = True
        self.overlay = blind.BlindOverlay(QRect(0, 0, 800, 600), self.state,
                                          {'screensaver_type': 'slideshow'})
        pattern = QPixmap(800, 600)
        pattern.fill(Qt.GlobalColor.white)
        painter = QPainter(pattern)
        for x in range(0, 800, 32):
            painter.fillRect(x, 0, 16, 600, Qt.GlobalColor.black)
        painter.end()
        self.overlay._animation._current = pattern

    def tearDown(self):
        self.overlay.deleteLater()
        self.state.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def render_background(self, blur=False, width=800, height=600):
        image = QPixmap(width, height)
        painter = QPainter(image)
        try:
            if blur:
                self.overlay._draw_blurred_background(painter, image.rect())
            else:
                self.overlay._draw_background(painter, image.rect())
        finally:
            painter.end()
        return image.toImage()

    def test_blur_softens_image_detail_and_reuses_unchanged_frame(self):
        sharp = self.render_background()
        blurred = self.render_background(True)
        def contrast(image):
            return abs(image.pixelColor(296, 300).red() - image.pixelColor(312, 300).red())
        self.assertGreater(contrast(sharp), 150)
        self.assertLess(contrast(blurred), contrast(sharp) / 2)
        cached = self.overlay._blur_pixmap
        self.render_background(True)
        self.assertIs(self.overlay._blur_pixmap, cached)

    def test_blurred_image_follows_slideshow_fade_and_resize(self):
        self.render_background(True)
        first = self.overlay._blur_pixmap
        animation = self.overlay._animation
        animation._next = QPixmap(800, 600)
        animation._next.fill(QColor('green'))
        animation._alpha = 0.25
        self.render_background(True)
        self.assertIsNot(self.overlay._blur_pixmap, first)
        self.assertLessEqual(self.overlay._blur_pixmap.width(), 480)
        before_resize = self.overlay._blur_pixmap.size()
        self.render_background(True, 1200, 600)
        self.assertNotEqual(self.overlay._blur_pixmap.size(), before_resize)

    def test_blur_is_only_used_behind_the_password_prompt(self):
        with patch.object(self.overlay, '_draw_blurred_background') as blurred, \
             patch.object(self.overlay, '_draw_clock') as clock, \
             patch.object(self.overlay, '_draw_password_prompt') as prompt:
            self.overlay.grab()
            blurred.assert_not_called()
            self.state.show_password_input()
            self.overlay.grab()
            blurred.assert_called_once()
            clock.assert_called()
            prompt.assert_called_once()
            self.assertFalse(clock.call_args.args[0].isActive(),
                             'A paint frame must finish before retained arguments are collected')
            self.state.hide_password_input()
            self.overlay.grab()
            self.assertEqual(blurred.call_count, 1)
