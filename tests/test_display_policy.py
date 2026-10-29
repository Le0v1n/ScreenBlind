"""Display persistence policy without QApplication, windows, or input hooks."""
import ctypes
import unittest
from unittest.mock import Mock, patch

import displays


class FakeScreen:
    def __init__(self, name, serial=None):
        self._name = name
        if serial is not None:
            self.serialNumber = lambda: serial
            self.manufacturer = lambda: 'Maker'
            self.model = lambda: 'Model'

    def name(self):
        return self._name

    def geometry(self):
        return (0, 0, 1920, 1080)


class DisplayPolicyTests(unittest.TestCase):
    def setUp(self):
        self.native = patch.object(displays, '_native_monitor_id', return_value='', create=True)
        self.native.start()
        self.addCleanup(self.native.stop)
        self.screens = [FakeScreen('DISPLAY1'), FakeScreen('DISPLAY2')]

    def test_native_identity_survives_source_renumbering(self):
        with patch.object(displays, '_native_monitor_id', return_value='device-interface-123'):
            self.assertEqual(displays.screen_key(self.screens[0]), displays.screen_key(self.screens[1]))
            self.assertIn('device-interface-123', displays.screen_key(self.screens[0]))

    def test_friendly_qt_name_can_resolve_through_native_display_source(self):
        with patch.object(displays, '_native_source_name', return_value='native-source', create=True), \
             patch.object(displays, '_native_monitor_id', side_effect=lambda name: 'interface' if name == 'native-source' else ''):
            self.assertEqual(displays.screen_key(self.screens[0]), 'monitor:interface')

    def test_metadata_fallback_disambiguates_duplicate_serials(self):
        first = FakeScreen('DISPLAY1', '123')
        second = FakeScreen('DISPLAY2', '123')
        self.assertNotEqual(displays.screen_key(first), displays.screen_key(second))
        self.assertNotEqual(displays.screen_key(first), first.name())
        self.assertEqual(displays.screen_key(self.screens[0]), 'DISPLAY1')

    def test_legacy_selection_migrates_and_reordering_preserves_target(self):
        cfg = {'locked_screens': [1, -1, 99], 'screen_names': {'DISPLAY2': 'Desk'}}
        self.assertTrue(displays.migrate_display_settings(cfg, self.screens))
        self.assertEqual(cfg['locked_screen_ids'], ['DISPLAY2'])
        self.assertEqual(cfg['remote_allowed_screen_ids'], ['DISPLAY1'])
        self.assertEqual(displays.selected_screen_indices(cfg, list(reversed(self.screens))), [0])
        self.assertFalse(displays.migrate_display_settings(cfg, self.screens))

    def test_preserves_offline_ids_and_explicit_empty_allowlist(self):
        cfg = {'locked_screen_ids': ['offline', 'DISPLAY2'], 'remote_allowed_screen_ids': []}
        self.assertFalse(displays.migrate_display_settings(cfg, self.screens))
        self.assertEqual(displays.selected_screen_ids(cfg, self.screens), ['offline', 'DISPLAY2'])
        self.assertEqual(displays.selected_screen_indices(cfg, self.screens), [1])
        self.assertEqual(cfg['remote_allowed_screen_ids'], [])

    def test_lock_all_uses_current_displays_without_overwriting_saved_selection(self):
        cfg = {'lock_all_screens': True, 'locked_screen_ids': ['offline']}
        self.assertEqual(displays.selected_screen_ids(cfg, self.screens), ['DISPLAY1', 'DISPLAY2'])
        self.assertEqual(displays.selected_screen_indices(cfg, self.screens), [0, 1])
        self.assertEqual(cfg['locked_screen_ids'], ['offline'])

    def test_legacy_selection_is_readable_before_migration(self):
        self.assertEqual(displays.selected_screen_ids({'locked_screens': [1]}, self.screens), ['DISPLAY2'])
        self.assertEqual(displays.selected_screen_ids({'locked_screen_ids': [], 'locked_screens': [1]}, self.screens), [])

    def test_custom_names_migrate_once_without_overwriting_stable(self):
        with patch.object(displays, '_native_monitor_id', side_effect=lambda name: 'native-' + name):
            stable = displays.screen_key(self.screens[1])
            cfg = {'screen_names': {'DISPLAY2': 'Desk'}}
            self.assertEqual(displays.display_name(self.screens[1], 1, cfg), 'Desk')
            displays.migrate_display_settings(cfg, self.screens, primary=self.screens[1])
            self.assertEqual(cfg['screen_names'], {stable: 'Desk'})
            self.assertEqual(cfg['remote_allowed_screen_ids'], [stable])
            cfg['screen_names'][stable] = 'New desk'
            displays.migrate_display_settings(cfg, self.screens)
            self.assertEqual(displays.display_name(self.screens[1], 1, cfg), 'New desk')

    def test_empty_screen_list_can_initialize_safely(self):
        cfg = {}
        self.assertTrue(displays.migrate_display_settings(cfg, []))
        self.assertEqual(cfg['locked_screen_ids'], [])
        self.assertEqual(cfg['remote_allowed_screen_ids'], [])
        self.assertEqual(displays.selected_screen_indices(cfg, []), [])


class NativeIdentityTests(unittest.TestCase):
    def test_windows_enumeration_requests_monitor_interface_and_prefers_active(self):
        calls = []

        def enumerate_device(source, index, pointer, flags):
            calls.append((source, index, flags, pointer._obj.cb))
            if index == 2:
                return 0
            pointer._obj.DeviceID = ['inactive-interface', 'active-interface'][index]
            pointer._obj.StateFlags = index
            return 1

        enum = Mock(side_effect=enumerate_device)
        user32 = Mock(EnumDisplayDevicesW=enum)
        with patch.object(displays.sys, 'platform', 'win32'), patch.object(
                displays.ctypes, 'windll', Mock(user32=user32), create=True):
            self.assertEqual(displays._native_monitor_id('DISPLAY1'), 'active-interface')
        self.assertEqual(calls, [
            ('DISPLAY1', 0, 1, ctypes.sizeof(displays._DISPLAY_DEVICEW)),
            ('DISPLAY1', 1, 1, ctypes.sizeof(displays._DISPLAY_DEVICEW)),
        ])

    def test_missing_native_api_falls_back_safely(self):
        with patch.object(displays.sys, 'platform', 'win32'), patch.object(
                displays.ctypes, 'windll', None, create=True):
            self.assertEqual(displays._native_monitor_id('DISPLAY1'), '')

    def test_non_windows_does_not_load_native_api(self):
        with patch.object(displays.sys, 'platform', 'linux'):
            self.assertEqual(displays._native_monitor_id('DISPLAY1'), '')


if __name__ == '__main__':
    unittest.main()
