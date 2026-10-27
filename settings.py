import json
import copy
import os
from pathlib import Path

DEFAULTS: dict = {
    "language": "system",       # "system" | "en" | "zh_CN"
    "theme": "dark",
    "lock_hotkey": "",
    "settings_hotkey": "",
    "password_hash": "",
    "locked_screens": [],
    "screen_names": {},          # Windows display identifier -> custom label
    "idle_timeout": 120,          # seconds before screensaver starts
    "screensaver_enabled": True,
    # "bubbles" | "matrix" | "flurry" | "slideshow" | "none"
    "screensaver_type": "bubbles",
    "slideshow_folder": "",
    "slideshow_folders": [],
    "slideshow_sync": True,
    "slideshow_interval": 5,      # seconds per image
}


def _path() -> Path:
    folder = Path(os.environ.get("APPDATA", str(Path.home()))) / "ScreenBlind"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def load() -> dict:
    p = _path()
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            merged = copy.deepcopy(DEFAULTS)
            merged.update(data)
            if 'slideshow_folders' not in data:
                merged['slideshow_folders'] = get_slideshow_folders(data)
            return merged
        except Exception:
            pass
    return copy.deepcopy(DEFAULTS)


def get_slideshow_folders(cfg: dict) -> list[str]:
    """Accept legacy single-folder settings without reviving explicitly removed folders."""
    folders = cfg.get('slideshow_folders')
    if folders is None:
        folders = [cfg.get('slideshow_folder', '')]
    unique = {}
    for folder in folders:
        if isinstance(folder, str) and folder.strip():
            key = os.path.normcase(os.path.abspath(os.path.expanduser(folder)))
            unique.setdefault(key, folder)
    return list(unique.values())


def save(s: dict) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
