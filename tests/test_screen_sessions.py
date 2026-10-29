import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QEvent, QRect
from PyQt6.QtWidgets import QApplication
import blind
import displays
import main

APP = QApplication.instance() or QApplication([])


class Screen:
    def __init__(self, name, x=0):
        self.label, self.x = name, x
    def name(self): return self.label
    def geometry(self): return QRect(self.x, 0, 800, 600)


class ScreenSessionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.a, self.b = Screen('a'), Screen('b', 800)
        self.screens = self.stack.enter_context(patch.object(QApplication, 'screens', return_value=[self.a]))
        self.stack.enter_context(patch.object(blind.dpi, 'monitor_rect_for_hwnd', return_value=None))
        for name in ('_force_topmost', '_clip_cursor', '_release_cursor', '_install_kb_hook', '_uninstall_kb_hook'):
            self.stack.enter_context(patch.object(blind, name))
        self.manager = None

    def tearDown(self):
        if self.manager:
            self.manager._on_unlocked()
            self.manager.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.stack.close()

    def test_lock_all_add_remove_reorder_and_zero_screens(self):
        self.manager = blind.BlindManager({'lock_all_screens': True, 'screensaver_type': 'none'})
        self.assertTrue(self.manager.lock())
        state = self.manager._state
        self.screens.return_value = [self.b, self.a]
        self.manager.reconcile_screens()
        self.assertEqual(len(self.manager._overlays), 2)
        self.screens.return_value = []
        self.manager.reconcile_screens()
        self.assertEqual(self.manager._overlays, [])
        self.assertIs(self.manager._state, state)
        self.screens.return_value = [self.a]
        self.manager.reconcile_screens()
        self.assertEqual(len(self.manager._overlays), 1)
        self.assertIs(self.manager._state, state)

    def test_manual_selection_follows_identity_not_position(self):
        self.manager = blind.BlindManager({'locked_screen_ids': [displays.screen_key(self.a)],
                                            'screensaver_type': 'none'})
        self.assertTrue(self.manager.lock())
        original = self.manager._overlays[0]
        self.screens.return_value = [self.b, self.a]
        self.manager.reconcile_screens()
        self.assertEqual(self.manager._overlays, [original])
        self.screens.return_value = [self.b]
        self.manager.reconcile_screens()
        self.assertFalse(self.manager._overlays)
        self.assertIsNotNone(self.manager._state)
        self.screens.return_value = [self.b, self.a]
        self.manager.reconcile_screens()
        self.assertEqual(len(self.manager._overlays), 1)


class DisplayUITests(unittest.TestCase):
    def test_migrated_name_can_be_reset_without_legacy_alias_returning(self):
        a = Screen('old-source')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder), \
             patch.object(displays, '_native_monitor_id', return_value='stable'), \
             patch.object(QApplication, 'screens', return_value=[a]), \
             patch.object(QApplication, 'primaryScreen', return_value=a), \
             patch.object(main.dpi, 'native_geometry', side_effect=lambda s: s.geometry()), \
             patch.object(main, '_resolution_text', return_value='800 × 600'):
            cfg = {'screen_names': {'old-source': 'Old name'}}
            tab = main.MonitorsTab(cfg)
            try:
                a.label = 'renumbered-source'
                tab.refresh()
                with patch.object(main.QInputDialog, 'getText', return_value=('', True)):
                    tab._rename_screen()
                a.label = 'old-source'
                tab.refresh()
                self.assertNotEqual(displays.display_name(a, 0, cfg), 'Old name')
            finally:
                tab.deleteLater()

    def test_all_switch_preserves_manual_selection_and_offline_ids(self):
        a, b = Screen('a'), Screen('b', 800)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder), \
             patch.object(QApplication, 'screens', return_value=[a, b]), \
             patch.object(QApplication, 'primaryScreen', return_value=a), \
             patch.object(main.dpi, 'native_geometry', side_effect=lambda s: s.geometry()), \
             patch.object(main, '_resolution_text', return_value='800 × 600'):
            cfg = {'locked_screens': [0]}
            tab = main.MonitorsTab(cfg)
            try:
                self.assertTrue(hasattr(tab, '_lock_all'), 'Expose the all-display policy switch')
                tab._lock_all.setChecked(True)
                self.assertEqual(tab.selected_indices(), [0, 1])
                self.assertEqual(cfg['locked_screen_ids'], [displays.screen_key(a)])
                tab._lock_all.setChecked(False)
                self.assertEqual(tab.selected_indices(), [0])
            finally:
                tab.deleteLater()

