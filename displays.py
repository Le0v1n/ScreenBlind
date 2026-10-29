"""Stable display identity and selection policy, independent of Qt application state."""
import ctypes
import json
import sys

from i18n import tr


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ('cb', ctypes.c_uint32),
        ('DeviceName', ctypes.c_wchar * 32),
        ('DeviceString', ctypes.c_wchar * 128),
        ('StateFlags', ctypes.c_uint32),
        ('DeviceID', ctypes.c_wchar * 128),
        ('DeviceKey', ctypes.c_wchar * 128),
    ]


def _native_monitor_id(source_name: str) -> str:
    """Resolve a GDI source to its monitor device-interface path on Windows."""
    if sys.platform != 'win32':
        return ''
    try:
        enum_devices = ctypes.windll.user32.EnumDisplayDevicesW
        enum_devices.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                 ctypes.POINTER(_DISPLAY_DEVICEW), ctypes.c_uint32]
        enum_devices.restype = ctypes.c_int
        first_id = ''
        index = 0
        while True:
            device = _DISPLAY_DEVICEW()
            device.cb = ctypes.sizeof(device)
            if not enum_devices(source_name, index, ctypes.byref(device), 1):
                return first_id
            if device.DeviceID:
                first_id = first_id or device.DeviceID
                if device.StateFlags & 1:  # DISPLAY_DEVICE_ACTIVE
                    return device.DeviceID
            index += 1
    except (AttributeError, OSError, ValueError):
        return ''


def _native_source_name(screen):
    """Qt can expose a friendly product name rather than a Windows GDI source."""
    from PyQt6.QtGui import QScreen
    if not isinstance(screen, QScreen):
        return screen.name()
    from PyQt6.QtWidgets import QApplication
    import dpi
    qt_screens = sorted(QApplication.screens(), key=lambda s: (s.geometry().x(), s.geometry().y()))
    monitors = dpi.physical_monitors()
    if len(qt_screens) == len(monitors):
        pairs = list(zip(qt_screens, monitors))
        if all(abs(mon['rect'].width() / max(1, qs.geometry().width()) - qs.devicePixelRatio()) <= 0.05
               for qs, mon in pairs):
            for qs, mon in pairs:
                if qs is screen:
                    return mon['device']
    return screen.name()


def screen_key(screen) -> str:
    source = screen.name()
    native_id = _native_monitor_id(source)
    if not native_id:
        native_source = _native_source_name(screen)
        if native_source != source:
            native_id = _native_monitor_id(native_source)
    if native_id:
        return 'monitor:' + native_id
    metadata = []
    for field in ('serialNumber', 'manufacturer', 'model'):
        getter = getattr(screen, field, None)
        metadata.append(str(getter() or '').strip() if callable(getter) else '')
    if any(metadata):
        # Source name disambiguates monitors with absent or duplicated serials.
        return 'qt:' + json.dumps(metadata + [source], ensure_ascii=False, separators=(',', ':'))
    return source


def display_name(screen, index: int, cfg: dict) -> str:
    names = cfg.get('screen_names', {})
    return (names.get(screen_key(screen)) or names.get(screen.name())
            or tr('Display {number}', number=index + 1))


def _legacy_screen_ids(cfg: dict, screens) -> list[str]:
    return list(dict.fromkeys(
        screen_key(screens[index]) for index in cfg.get('locked_screens', [])
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(screens)
    ))


def selected_screen_ids(cfg: dict, screens) -> list[str]:
    """Return policy IDs, retaining saved IDs for temporarily offline displays."""
    screens = list(screens)
    if cfg.get('lock_all_screens', False):
        return list(dict.fromkeys(screen_key(screen) for screen in screens))
    if 'locked_screen_ids' in cfg:
        return list(cfg['locked_screen_ids'])
    return _legacy_screen_ids(cfg, screens)


def selected_screen_indices(cfg: dict, screens) -> list[int]:
    """Project saved identity policy onto the current enumeration for legacy callers."""
    screens = list(screens)
    selected = set(selected_screen_ids(cfg, screens))
    return [index for index, screen in enumerate(screens) if screen_key(screen) in selected]


def migrate_display_settings(cfg: dict, screens, primary=None) -> bool:
    """Add identity settings once; never remove names or IDs of offline displays.

    The caller can supply QApplication.primaryScreen(); absent that, the first
    current screen is the conservative initial remote allowlist.
    """
    screens = list(screens)
    changed = False
    if 'locked_screen_ids' not in cfg:
        cfg['locked_screen_ids'] = _legacy_screen_ids(cfg, screens)
        changed = True
    if 'remote_allowed_screen_ids' not in cfg:
        chosen = next((screen for screen in screens if screen is primary), None)
        if chosen is None and screens:
            chosen = screens[0]
        cfg['remote_allowed_screen_ids'] = [screen_key(chosen)] if chosen is not None else []
        changed = True
    names = cfg.get('screen_names', {})
    for screen in screens:
        old_key, new_key = screen.name(), screen_key(screen)
        if old_key in names and new_key not in names:
            names[new_key] = names[old_key]
            changed = True
        if old_key != new_key and old_key in names:
            # Consume migrated aliases once; a later source renumbering must not
            # resurrect a reset name or apply that name to another monitor.
            del names[old_key]
            changed = True
    return changed
