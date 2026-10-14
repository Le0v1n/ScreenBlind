import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "theme": "dark",
    "lock_hotkey": "Ctrl+Alt+L",
    "settings_hotkey": "Ctrl+Alt+S",
    "password_hash": "",
    "locked_screens": [],
    "idle_timeout": 120,          # seconds before screensaver starts
    # "bubbles" | "matrix" | "flurry" | "slideshow" | "none"
    "screensaver_type": "bubbles",
    "slideshow_folder": "",
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
            merged = DEFAULTS.copy()
            merged.update(data)
            return merged
        except Exception:
            pass
    return DEFAULTS.copy()


def save(s: dict) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
