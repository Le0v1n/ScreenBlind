"""Persist display labels against Windows display identifiers, not list order."""
from i18n import tr


def screen_key(screen) -> str:
    return screen.name()


def display_name(screen, index: int, cfg: dict) -> str:
    return cfg.get('screen_names', {}).get(screen_key(screen)) or tr('Display {number}', number=index + 1)
