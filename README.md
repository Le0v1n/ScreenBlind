<div align="center">

<img src="media_assets/logo_screen_blind_highres.png" alt="ScreenBlind" width="160" />

# ScreenBlind

**Lock what others shouldn't see. Unlock what matters.**

Selective multi-monitor lock screen for Windows.
Cover the screens you choose — let the others keep showing what's on them.

[Website](https://screenblind.cc) · [Download](#installation) · [Donate ❤](#support)

</div>

---

## What it does

ScreenBlind lets you lock **individual monitors** on a multi-display Windows
setup. The locked screens go dark and require a password to wake — the
unlocked ones stay **visible** and keep displaying their content, so a
presentation, video, or dashboard can carry on while you step away. Mouse
and keyboard input stays captured by the lock; the unlocked monitor is for
**viewing only**, not interacting with.

## Features

- 🖥️ **Selective locking** — pick exactly which monitors to lock
- 🔒 **Password-protected** — single password unlocks every locked screen at once
- 🐭 **Cursor trapping** — mouse can't escape onto unlocked monitors
- 🎨 **Built-in screensavers** — Bubbles, Matrix rain, or your own image slideshow
- 🕐 **Roaming clock** — clock and date drift to random positions to keep the lock surface alive
- 🌌 **Animated background** — dark hues slowly shift across the color wheel
- 🪶 **Lightweight** — single `.exe`, no installer, no background services, no telemetry
- 📦 **System tray** — runs quietly until you need it

## Screenshots

> *Coming soon. If you'd like to contribute screenshots, see [Contributing](#contributing).*

## Installation

### From release (recommended)

Grab the latest `ScreenBlind.exe` from the [Releases](https://github.com/) page
and run it. No installer, no admin rights required.

### From source

```bash
git clone https://github.com/<your-fork>/ScreenBlind.git
cd ScreenBlind
pip install -r requirements.txt
python main.py
```

Tested on Python 3.11+ and Windows 10/11.

### Build your own executable

```bash
.\build.bat
```

The standalone `ScreenBlind.exe` lands in `dist/`.

## How it works

1. **Monitors tab** — check the screens you want to lock
2. **Security tab** — set a password (PBKDF2-SHA256, hashed locally)
3. **Hit "Lock Now"** — selected screens are covered by an overlay that:
   - Sits above the taskbar via `SetWindowPos(HWND_TOPMOST)`
   - Traps the cursor with `ClipCursor` so it can't reach unlocked screens
   - Blocks the Windows key from opening the Start menu via `WH_KEYBOARD_LL`
   - Shows a clock, date, and password prompt on key/mouse activity
   - Transitions to a screensaver after idle timeout
4. **Unlock once** — every locked screen wakes up simultaneously

Settings persist to `%APPDATA%\ScreenBlind\settings.json`. Passwords are
stored as a base64-encoded `salt + PBKDF2 key` and never leave your machine.

## Limitations — please read

ScreenBlind is a **focus and privacy tool**, not a replacement for the Windows
lock screen. Two Windows shortcuts cannot be intercepted by any user-mode
application:

### `Win`+`L` still works

The `Win`+`L` shortcut is processed by `win32k.sys` at the kernel level,
*before* it ever reaches user-mode keyboard hooks. No regular application
can reliably block it (this includes ScreenBlind, AutoHotkey, and similar
tools). Pressing it will show the standard Windows lock screen.

### `Ctrl`+`Alt`+`Del` still works

`Ctrl`+`Alt`+`Del` is a hardware-level Secure Attention Sequence built into
Windows specifically so no software can ever intercept it. This is intentional
OS security and applies to every third-party lock tool.

### What this means in practice

If someone presses `Win`+`L` or `Ctrl`+`Alt`+`Del` on a locked machine:

1. The Windows lock screen appears on top
2. Your Windows password is required to dismiss it
3. ScreenBlind's overlay is **still active** underneath
4. Your ScreenBlind password is then required to reveal the screens

So a bypass attempt actually *adds* a layer rather than removing one —
the attacker now needs both passwords.

### Other limitations

- **Windows-only** — built on Win32-specific APIs (cursor clipping, top-most
  enforcement, low-level keyboard hooks). macOS / Linux ports are wishlist.

## Configuration

| Setting              | Where                                | Default       |
| -------------------- | ------------------------------------ | ------------- |
| Locked screens       | Monitors tab                         | (none)        |
| Password             | Security tab                         | (unset)       |
| Idle → screensaver   | Screensaver tab                      | 120 seconds   |
| Animation style      | Screensaver tab                      | Bubbles       |
| Slideshow folder     | Screensaver tab                      | (none)        |
| Slideshow interval   | Screensaver tab                      | 5 seconds     |

Stored as JSON in `%APPDATA%\ScreenBlind\settings.json`.

## Project structure

```
ScreenBlind/
├── main.py              # Entry point + settings UI (Qt)
├── blind.py             # Per-screen overlay widget + BlindManager + Win32 helpers
├── animations.py        # Bubbles / Matrix / Slideshow screensavers
├── auth.py              # PBKDF2 password hash + verify
├── settings.py          # JSON load/save under %APPDATA%
├── generate_icon.py     # Programmatic icon generator
├── icon.ico             # App icon
├── media_assets/        # Logo + header artwork
├── build.bat            # PyInstaller build script
└── requirements.txt     # PyQt6
```

## Support

ScreenBlind is free and will stay free. If it saves you from someone peeking
at your monitor during a coffee run, consider supporting development.

> 💛 **Donation links coming soon** — payment provider details will be added
> here and on the [website](https://screenblind.cc/donate) shortly.

In the meantime:

- ⭐ Star this repo
- 🐛 Open issues for bugs you find
- 🔁 Share it with anyone who uses multi-monitor setups

## Contributing

Pull requests welcome — especially for:

- Screenshots / demo recordings for the README and landing page
- Additional screensaver animations
- macOS / Linux ports (probably a larger undertaking)
- Bug reports with reproduction steps

## License

[MIT](LICENSE) © Hemi G

Free to use, modify, and distribute — including commercially. The only
requirement is keeping the copyright notice. See [LICENSE](LICENSE) for the
full text.

---

<div align="center">

[screenblind.cc](https://screenblind.cc) · Lock what others shouldn't see.

</div>
