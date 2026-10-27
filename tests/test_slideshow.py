"""Slideshow, display-label and immediate-start regressions without input hooks."""
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent, QRect
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QWidget

import animations
import blind
import displays
import main
import settings

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class TemporarySettings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APPDATA=self.temp.name)
        self.env.start()

    def tearDown(self):
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.env.stop()
        self.temp.cleanup()


class SettingsTests(TemporarySettings):
    def test_legacy_folder_is_migrated_and_explicit_empty_list_stays_empty(self):
        settings.save({'slideshow_folder': self.temp.name, 'idle_timeout': 0})
        self.assertEqual(settings.load()['slideshow_folders'], [self.temp.name])
        self.assertEqual(settings.load()['idle_timeout'], 0)
        settings.save({'slideshow_folder': self.temp.name, 'slideshow_folders': []})
        self.assertEqual(settings.load()['slideshow_folders'], [])

    def test_defaults_do_not_share_mutable_names_or_folders(self):
        first = settings.load()
        first['screen_names']['display-a'] = 'Desk'
        first['slideshow_folders'].append('not-saved')
        second = settings.load()
        self.assertEqual(second['screen_names'], {})
        self.assertEqual(second['slideshow_folders'], [])

    def test_add_multiple_folders_deduplicates_and_remove_persists(self):
        tab = main.ScreensaverTab(settings.load())
        try:
            folder_a = str(Path(self.temp.name) / 'a')
            folder_b = str(Path(self.temp.name) / 'b')
            with patch.object(main.QFileDialog, 'getExistingDirectory', side_effect=[folder_a, folder_b, folder_a]):
                for _ in range(3):
                    tab._browse_folder()
            self.assertEqual(tab._folder_list.count(), 2)
            self.assertEqual(settings.load()['slideshow_folders'], [folder_a, folder_b])
            tab._folder_list.selectAll()
            tab._remove_folders()
            self.assertEqual(settings.load()['slideshow_folders'], [])
            self.assertEqual(settings.load()['slideshow_folder'], '')
        finally:
            tab.deleteLater()

    def test_zero_timeout_and_sync_choice_restore(self):
        tab = main.ScreensaverTab(settings.load())
        try:
            self.assertEqual(tab._timeout_spin.minimum(), 0)
            self.assertTrue(tab._sync_slideshow.isChecked())
            tab._timeout_spin.setValue(0)
            tab._sync_slideshow.setChecked(False)
            restored = main.ScreensaverTab(settings.load())
            try:
                self.assertEqual(restored._timeout_spin.value(), 0)
                self.assertFalse(restored._sync_slideshow.isChecked())
            finally:
                restored.deleteLater()
        finally:
            tab.deleteLater()


class ImmediateTests(unittest.TestCase):
    def test_zero_starts_immediately_but_does_not_interrupt_password_entry(self):
        state = blind.BlindState({'idle_timeout': 0})
        try:
            state.start_idle_timer()
            self.assertTrue(state.in_screensaver)
            self.assertFalse(state._idle_timer.isActive())
            state.show_password_input()
            state.handle_char('x')
            state.on_mouse_move()
            self.assertTrue(state.showing_password)
            self.assertFalse(state.in_screensaver)
            self.assertEqual(state.password_buffer, 'x')
            state.hide_password_input()
            self.assertTrue(state.in_screensaver)
        finally:
            state.deleteLater()

    def test_master_switch_overrides_zero_timeout(self):
        state = blind.BlindState({'idle_timeout': 0, 'screensaver_enabled': False})
        state.start_idle_timer()
        self.assertFalse(state.in_screensaver)
        self.assertFalse(state._idle_timer.isActive())
        state.deleteLater()


class FakeScreen:
    def __init__(self, identifier, x=0):
        self.identifier = identifier
        self.x = x

    def name(self):
        return self.identifier

    def geometry(self):
        return QRect(self.x, 0, 800, 600)


class DisplayNameTests(TemporarySettings):
    def test_names_follow_display_identifiers_after_refresh_and_reordering(self):
        a, b = FakeScreen('display-a'), FakeScreen('display-b', 800)
        cfg = settings.load()
        with patch.object(QApplication, 'screens', return_value=[a, b]) as screens, \
             patch.object(QApplication, 'primaryScreen', return_value=a), \
             patch.object(main.dpi, 'native_geometry', side_effect=lambda screen: screen.geometry()), \
             patch.object(main, '_resolution_text', return_value='800 × 600'):
            tab = main.MonitorsTab(cfg)
            try:
                with patch.object(main.QInputDialog, 'getText', return_value=('Desk monitor', True)):
                    tab._rename_screen()
                self.assertEqual(settings.load()['screen_names']['display-a'], 'Desk monitor')
                screens.return_value = [b, a]
                tab.refresh()
                self.assertTrue(tab._items[1][0].text().startswith('Desk monitor'))
                self.assertEqual(displays.display_name(a, 1, settings.load()), 'Desk monitor')
                tab._list.setCurrentRow(1)
                with patch.object(main.QInputDialog, 'getText', return_value=('', True)):
                    tab._rename_screen()
                self.assertNotIn('display-a', settings.load()['screen_names'])
            finally:
                tab.deleteLater()


class SlideshowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder_a = Path(self.temp.name) / 'a'
        self.folder_b = Path(self.temp.name) / 'b'
        for folder, color in ((self.folder_a, 'red'), (self.folder_b, 'green')):
            folder.mkdir()
            image = QImage(16, 16, QImage.Format.Format_RGB32)
            image.fill(QColor(color))
            self.assertTrue(image.save(str(folder / 'picture.png')))

    def tearDown(self):
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def test_multiple_folders_merge_without_duplicates_and_missing_paths_are_safe(self):
        widget = QWidget()
        slideshow = animations.SlideshowAnimation(widget, [str(self.folder_a), str(self.folder_b),
                                                          str(self.folder_a / '..' / 'a'), 'missing-folder'])
        try:
            slideshow.start()
            self.assertEqual(len(slideshow._images), 2)
            first_color = slideshow._current.toImage().pixelColor(0, 0)
            slideshow._start_transition()
            for _ in range(41):
                slideshow.advance()
            self.assertNotEqual(slideshow._current.toImage().pixelColor(0, 0), first_color)
        finally:
            slideshow.stop()
            widget.deleteLater()

    def test_invalid_images_are_skipped(self):
        (self.folder_a / 'broken.png').write_text('not an image')
        widget = QWidget()
        slideshow = animations.SlideshowAnimation(widget, str(self.folder_a))
        try:
            with patch.object(animations.random, 'shuffle'):
                slideshow.start()
            self.assertIsNotNone(slideshow._current)
            self.assertFalse(slideshow._current.isNull())
        finally:
            slideshow.stop()
            widget.deleteLater()

    def test_one_second_interval_finishes_fade_before_the_next_slide(self):
        widget = QWidget()
        slideshow = animations.SlideshowAnimation(widget, [str(self.folder_a), str(self.folder_b)], 1)
        try:
            slideshow.start()
            first = slideshow._current.toImage().pixelColor(0, 0)
            slideshow._start_transition()
            for _ in range(slideshow.FPS):
                slideshow.advance()
            self.assertFalse(slideshow._transitioning)
            self.assertNotEqual(slideshow._current.toImage().pixelColor(0, 0), first)
        finally:
            slideshow.stop()
            widget.deleteLater()

    def _assert_two_display_mode(self, synchronized):
        a, b = FakeScreen('display-a'), FakeScreen('display-b', 800)
        cfg = {'locked_screens': [0, 1], 'screensaver_type': 'slideshow', 'idle_timeout': 0,
               'slideshow_folders': [str(self.folder_a), str(self.folder_b)],
               'screen_names': {'display-a': 'Desk', 'display-b': 'Presentation'}}
        if synchronized is not None:
            cfg['slideshow_sync'] = synchronized
        with ExitStack() as stack:
            stack.enter_context(patch.object(QApplication, 'screens', return_value=[a, b]))
            stack.enter_context(patch.object(blind.dpi, 'monitor_rect_for_hwnd', return_value=None))
            for name in ('_force_topmost', '_clip_cursor', '_release_cursor', '_install_kb_hook', '_uninstall_kb_hook'):
                stack.enter_context(patch.object(blind, name))
            manager = blind.BlindManager(cfg)
            try:
                self.assertTrue(manager.lock())
                left, right = manager._overlays
                self.assertTrue(manager._state.in_screensaver)
                self.assertTrue(left._ss_active and right._ss_active)
                self.assertEqual((left._screen_name, right._screen_name), ('Desk', 'Presentation'))
                if synchronized is not False:
                    self.assertIs(left._animation, right._animation)
                    with patch.object(left._animation, 'reset') as reset:
                        left._animation.start()
                        right._animation.start()
                        reset.assert_not_called()
                else:
                    self.assertIsNot(left._animation, right._animation)
                    left._animation._start_transition()
                    left._animation.advance()
                    self.assertLess(left._animation._alpha, right._animation._alpha)
            finally:
                for overlay in manager._overlays:
                    overlay.leave_screensaver()
                manager._on_unlocked()
                manager.deleteLater()

    def test_selected_displays_share_one_slideshow_by_default(self):
        self._assert_two_display_mode(None)

    def test_selected_displays_can_play_independently(self):
        self._assert_two_display_mode(False)
