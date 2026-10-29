"""
ScreenBlind – selective multi-monitor lock screen.
Entry point + settings UI.
"""

from __future__ import annotations

from i18n import tr

import sys
import copy
import weakref
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, QRectF
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QKeySequenceEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import auth
import dpi
import settings as cfg_mod
import startup
from blind import BlindManager
from hotkeys import GlobalHotkeys
from themes import apply_theme
from instance import InstanceGuard
from i18n import configure_language
from displays import display_name, screen_key, migrate_display_settings, selected_screen_indices
from clocks import CLOCK_STYLES, draw_clock
from widgets import WheelSafeComboBox, WheelSafeSpinBox
from remote import RemoteManager
from remote_ui import RemoteTab, RecoveryDialog
from input_diagnostics import InputDiagnostics
from mouse_diagnostics import MouseDiagnostics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sep() -> QFrame:
    f = QFrame()
    f.setProperty("role", "separator")
    f.setFrameShape(QFrame.Shape.HLine)
    return f


def _label(text: str, secondary: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    if secondary:
        lbl.setProperty("secondary", "true")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)
    return lbl


def _resource_path(*parts: str) -> Path:
    """
    Locate a bundled resource. Works in both dev mode and PyInstaller
    one-file builds (where assets live under sys._MEIPASS at runtime).
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def _resolution_text(screen) -> str:
    """
    Native resolution of a screen, plus its scaling when it isn't 100%.

    Qt's own geometry is in logical pixels, so a 2560x1440 display at 150%
    would otherwise be reported as 1707x960 — the wrong-resolution bug.
    """
    w, h = dpi.native_size(screen)
    scale = dpi.scale_percent(screen)
    text = f"{w} × {h}"
    if scale != 100:
        text += f"  @ {scale}%"
    return text


def _app_icon() -> QIcon:
    """Window + tray icon, sourced from the bundled icon.ico (multi-size)."""
    p = _resource_path("icon.ico")
    if p.exists():
        return QIcon(str(p))
    return QIcon()


# ---------------------------------------------------------------------------
# Screen identifier overlay (Windows-style "Identify" tool)
# ---------------------------------------------------------------------------

class _ScreenIdentifierOverlay(QWidget):
    """A frameless top-most card showing a big number on a single screen."""

    def __init__(self, screen, number: int, name: str = ''):
        super().__init__(None)
        self._screen = screen
        self._number = number
        self._name = name

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Centered on the target screen
        geo = screen.geometry()
        w, h = 280, 280
        x = geo.x() + (geo.width() - w) // 2
        y = geo.y() + (geo.height() - h) // 2
        self.setGeometry(x, y, w, h)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(6, 6, -6, -6)

        # Dark rounded panel with indigo border
        painter.setBrush(QColor(10, 10, 24, 230))
        painter.setPen(QPen(QColor(99, 102, 241, 210), 3))
        painter.drawRoundedRect(rect, 28, 28)

        # Big number
        font = QFont("Segoe UI", 150)
        font.setWeight(QFont.Weight.Light)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self._number))

        # Resolution label at the bottom
        sub_font = QFont("Segoe UI", 11)
        sub_font.setWeight(QFont.Weight.Medium)
        painter.setFont(sub_font)
        painter.setPen(QColor(165, 180, 252, 200))
        if self._name:
            label = painter.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideRight, rect.width() - 24)
            painter.drawText(rect.adjusted(0, 0, 0, -44),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, label)
        painter.drawText(
            rect.adjusted(0, 0, 0, -22),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            _resolution_text(self._screen),
        )

    def mousePressEvent(self, _event):
        # Click anywhere on the card to dismiss early
        self.close()


# ---------------------------------------------------------------------------
# Monitors tab
# ---------------------------------------------------------------------------

class MonitorsTab(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg
        self._items: list[tuple[QListWidgetItem, int]] = []
        self._identify_overlays: list[_ScreenIdentifierOverlay] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(_label(tr('Select displays to lock:')))
        self._lock_all = QCheckBox(tr('Lock all displays, including newly connected displays'))
        self._lock_all.setChecked(cfg.get('lock_all_screens', False))
        self._lock_all.toggled.connect(self._save_lock_all)
        layout.addWidget(self._lock_all)

        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.itemChanged.connect(self._on_change)
        layout.addWidget(self._list)

        row = QHBoxLayout()
        refresh_btn = QPushButton(tr('↻  Refresh displays'))
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)

        identify_btn = QPushButton(tr('🔢  Identify displays'))
        identify_btn.setToolTip(tr('Show a number on each connected display'))
        identify_btn.clicked.connect(self.identify_screens)
        row.addWidget(identify_btn)

        self._rename_btn = QPushButton(tr('Rename selected display…'))
        self._rename_btn.clicked.connect(self._rename_screen)
        row.addWidget(self._rename_btn)

        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(_label(
            tr('Tip: unlocked displays remain visible; while locked, mouse and keyboard input is used only for unlocking.'),
            secondary=True,
        ))

        self.refresh()

    def identify_screens(self):
        """Flash a big number on every connected screen for ~3 seconds."""
        self._dismiss_identifiers()
        for i, screen in enumerate(QApplication.screens()):
            ov = _ScreenIdentifierOverlay(screen, i + 1, display_name(screen, i, self._cfg))
            ov.show()
            self._identify_overlays.append(ov)
        QTimer.singleShot(3000, self._dismiss_identifiers)

    def _dismiss_identifiers(self):
        for o in self._identify_overlays:
            o.close()
        self._identify_overlays.clear()

    def refresh(self):
        screens = QApplication.screens()
        if migrate_display_settings(self._cfg, screens, QApplication.primaryScreen()):
            cfg_mod.save(self._cfg)
        self._list.blockSignals(True)
        self._list.clear()
        self._items.clear()
        locked = set(selected_screen_indices(self._cfg, screens))
        primary = QApplication.primaryScreen()

        for i, screen in enumerate(screens):
            native = dpi.native_geometry(screen)
            label = (
                display_name(screen, i, self._cfg)
                + (tr(' (Primary)') if screen is primary else "")
                + f"  —  {_resolution_text(screen)}"
                + tr("  at ({x}, {y})", x=native.x(), y=native.y())
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, screen_key(screen))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if self._cfg.get('lock_all_screens', False):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(
                Qt.CheckState.Checked if i in locked else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
            self._items.append((item, i))

        self._list.blockSignals(False)
        self._rename_btn.setEnabled(bool(self._items))
        if self._items:
            self._list.setCurrentRow(0)

    def _rename_screen(self):
        item = self._list.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        names = dict(self._cfg.get('screen_names', {}))
        name, accepted = QInputDialog.getText(self, tr('Rename display'),
                                            tr('Display name (leave empty to reset):'),
                                            text=names.get(key, ''))
        if not accepted:
            return
        if name.strip():
            names[key] = name.strip()
        else:
            names.pop(key, None)
            # Remove a migrated source-name alias as well as the stable key.
            for screen in QApplication.screens():
                if screen_key(screen) == key:
                    names.pop(screen.name(), None)
        self._cfg['screen_names'] = names
        cfg_mod.save(self._cfg)
        self.refresh()

    def _on_change(self, _item):
        if self._cfg.get('lock_all_screens', False):
            return
        present = {item.data(Qt.ItemDataRole.UserRole) for item, _ in self._items}
        offline = [key for key in self._cfg.get('locked_screen_ids', []) if key not in present]
        self._cfg['locked_screen_ids'] = offline + [item.data(Qt.ItemDataRole.UserRole)
            for item, _ in self._items if item.checkState() == Qt.CheckState.Checked]
        self._cfg["locked_screens"] = [
            idx for item, idx in self._items
            if item.checkState() == Qt.CheckState.Checked
        ]
        cfg_mod.save(self._cfg)

    def _save_lock_all(self, enabled):
        self._cfg['lock_all_screens'] = enabled
        cfg_mod.save(self._cfg)
        self.refresh()

    def selected_indices(self) -> list[int]:
        return [idx for item, idx in self._items
                if item.checkState() == Qt.CheckState.Checked]


# ---------------------------------------------------------------------------
# Security tab
# ---------------------------------------------------------------------------

class SecurityTab(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self._status_lbl = _label("", secondary=True)
        layout.addWidget(self._status_lbl)
        layout.addWidget(_sep())

        # Current password row (hidden when no password is set)
        self._old_pw_lbl = _label(tr('Current password:'))
        layout.addWidget(self._old_pw_lbl)
        self._old_pw = QLineEdit()
        self._old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._old_pw.setPlaceholderText(tr('Enter current password'))
        layout.addWidget(self._old_pw)

        layout.addWidget(_label(tr('New password:')))
        self._pw1 = QLineEdit()
        self._pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw1.setPlaceholderText(tr('Enter new password'))
        layout.addWidget(self._pw1)

        layout.addWidget(_label(tr('Confirm new password:')))
        self._pw2 = QLineEdit()
        self._pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw2.setPlaceholderText(tr('Repeat new password'))
        layout.addWidget(self._pw2)

        self._show_cb = QCheckBox(tr('Show passwords'))
        self._show_cb.toggled.connect(self._toggle_show)
        layout.addWidget(self._show_cb)

        layout.addWidget(_sep())

        self._set_btn = QPushButton(tr('Set password'))
        self._set_btn.clicked.connect(self._set_password)
        layout.addWidget(self._set_btn)

        layout.addWidget(_sep())
        self._forgot_note = _label("", secondary=True)
        self._forgot_note.setWordWrap(True)
        layout.addWidget(self._forgot_note)

        layout.addStretch()
        self._refresh_ui()

    # -- helpers -------------------------------------------------------------

    def _has_password(self) -> bool:
        return bool(self._cfg.get("password_hash"))

    def _refresh_ui(self):
        import os
        has = self._has_password()
        self._status_lbl.setText(
            tr('Password is set.') if has else tr('No password set yet.')
        )
        self._old_pw_lbl.setVisible(has)
        self._old_pw.setVisible(has)
        self._old_pw.clear()
        self._pw1.clear()
        self._pw2.clear()
        settings_path = os.path.join(
            os.environ.get("APPDATA", ""), "ScreenBlind", "settings.json"
        )
        self._forgot_note.setText(
            tr("Forgot your password? Exit the app and delete this settings file to reset:\n{path}", path=settings_path)
            if has else ""
        )

    def _toggle_show(self, checked: bool):
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._old_pw.setEchoMode(mode)
        self._pw1.setEchoMode(mode)
        self._pw2.setEchoMode(mode)

    # -- actions -------------------------------------------------------------

    def _set_password(self):
        # Verify current password first (if one is set)
        if self._has_password():
            old = self._old_pw.text()
            if not auth.verify_password(old, self._cfg["password_hash"]):
                QMessageBox.warning(
                    self, tr('Incorrect password'),
                    tr('The current password is incorrect.'),
                )
                self._old_pw.clear()
                self._old_pw.setFocus()
                return

        p1, p2 = self._pw1.text(), self._pw2.text()
        if not p1:
            QMessageBox.warning(self, tr('Empty password'), tr('New password cannot be empty.'))
            return
        if p1 != p2:
            QMessageBox.warning(self, tr('Passwords do not match'), tr('The new passwords do not match.'))
            return

        self._cfg["password_hash"] = auth.hash_password(p1)
        cfg_mod.save(self._cfg)
        self._refresh_ui()
        QMessageBox.information(self, tr('Done'), tr('Password updated successfully.'))



# ---------------------------------------------------------------------------
# Screensaver tab
# ---------------------------------------------------------------------------

class ClockPreview(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self.setMinimumHeight(180)
        self.setMaximumHeight(220)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#121a2b'))
        painter.drawRoundedRect(self.rect(), 14, 14)
        draw_clock(painter, QRectF(self.rect().adjusted(12, 8, -12, -8)),
                   self._cfg.get('clock_style', 'classic'))


class ScreensaverTab(QScrollArea):
    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(_label(tr('Lock-screen clock:')))
        self._clock_moving = QCheckBox(tr('Move the clock periodically'))
        self._clock_moving.setChecked(cfg.get('clock_moving', False))
        self._clock_moving.toggled.connect(self._save_clock_moving)
        layout.addWidget(self._clock_moving)
        layout.addWidget(_label(tr('Off by default. When enabled, the clock moves every 30–120 seconds.'), secondary=True))
        self._clock_style = WheelSafeComboBox()
        for name, key in zip((tr('Classic · time and seconds'), tr('Minimal · clean typography'), tr('Panel · soft indigo')), CLOCK_STYLES):
            self._clock_style.addItem(name, key)
        index = self._clock_style.findData(cfg.get('clock_style', 'classic'))
        self._clock_style.setCurrentIndex(max(0, index))
        self._clock_style.currentIndexChanged.connect(self._save_clock_style)
        layout.addWidget(self._clock_style)
        self._clock_preview = ClockPreview(cfg)
        layout.addWidget(self._clock_preview)
        layout.addWidget(_sep())

        # Idle timeout
        self._idle_enabled = QCheckBox(tr('Start the screensaver when idle'))
        self._idle_enabled.setChecked(cfg.get("screensaver_enabled", True))
        layout.addWidget(self._idle_enabled)
        layout.addWidget(_label(tr('Start screensaver after idle:')))
        row1 = QHBoxLayout()
        self._timeout_spin = WheelSafeSpinBox()
        self._timeout_spin.setRange(0, 3600)
        self._timeout_spin.setValue(cfg.get("idle_timeout", 120))
        self._timeout_spin.setSuffix(tr('  seconds'))
        self._timeout_spin.setFixedWidth(160)
        self._timeout_spin.setEnabled(self._idle_enabled.isChecked())
        self._idle_enabled.toggled.connect(self._save_idle_enabled)
        self._timeout_spin.valueChanged.connect(self._save_timeout)
        row1.addWidget(self._timeout_spin)
        row1.addStretch()
        layout.addLayout(row1)
        layout.addWidget(_label(tr('0 seconds starts the selected screensaver immediately after locking.'), secondary=True))

        layout.addWidget(_sep())

        # Animation type
        layout.addWidget(_label(tr('Animation style:')))
        self._anim_combo = WheelSafeComboBox()
        self._anim_combo.addItems([tr('Bubbles'), tr('Matrix'), tr('Flurry'), tr('Image slideshow'), tr('None')])
        type_map = {"bubbles": 0, "matrix": 1, "flurry": 2, "slideshow": 3, "none": 4}
        self._anim_combo.setCurrentIndex(type_map.get(cfg.get("screensaver_type", "bubbles"), 0))
        self._anim_combo.currentIndexChanged.connect(self._save_anim)
        layout.addWidget(self._anim_combo)

        layout.addWidget(_sep())

        # Slideshow options
        layout.addWidget(_label(tr('Slideshow options:')))
        self._sync_slideshow = QCheckBox(tr('Show the same image on all locked displays'))
        self._sync_slideshow.setChecked(cfg.get('slideshow_sync', True))
        self._sync_slideshow.toggled.connect(self._save_sync)
        layout.addWidget(self._sync_slideshow)
        layout.addWidget(_label(tr('Enabled by default: images and transitions are synchronized. Turn off for independent slideshows.'), secondary=True))
        self._recursive_slideshow = QCheckBox(tr('Include subfolders'))
        self._recursive_slideshow.setChecked(cfg.get('slideshow_recursive', False))
        self._recursive_slideshow.toggled.connect(self._save_recursive)
        layout.addWidget(self._recursive_slideshow)
        layout.addWidget(_label(tr('Off by default. Only images at least 1280 pixels wide and 720 pixels high are shown.'), secondary=True))
        self._folder_list = QListWidget()
        self._folder_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._folder_list.setMinimumHeight(100)
        self._folder_list.setMaximumHeight(160)
        self._folder_list.addItems(cfg_mod.get_slideshow_folders(cfg))
        layout.addWidget(self._folder_list)
        layout.addWidget(_label(tr('Add multiple folders one at a time. Images are combined into one playlist.'), secondary=True))

        row2 = QHBoxLayout()
        browse_btn = QPushButton(tr('Add folder…'))
        browse_btn.clicked.connect(self._browse_folder)
        row2.addWidget(browse_btn)
        remove_btn = QPushButton(tr('Remove selected folders'))
        remove_btn.clicked.connect(self._remove_folders)
        row2.addWidget(remove_btn)
        row2.addStretch()
        layout.addLayout(row2)

        layout.addWidget(_label(tr('Seconds per image:')))
        row3 = QHBoxLayout()
        self._interval_spin = WheelSafeSpinBox()
        self._interval_spin.setRange(1, 300)
        self._interval_spin.setValue(cfg.get("slideshow_interval", 5))
        self._interval_spin.setSuffix(tr('  seconds'))
        self._interval_spin.setFixedWidth(120)
        self._interval_spin.valueChanged.connect(self._save_interval)
        row3.addWidget(self._interval_spin)
        row3.addStretch()
        layout.addLayout(row3)

        layout.addStretch()
        self.setWidget(content)

    def _save_idle_enabled(self, enabled: bool):
        self._cfg["screensaver_enabled"] = enabled
        self._timeout_spin.setEnabled(enabled)
        cfg_mod.save(self._cfg)

    def _save_clock_moving(self, enabled):
        self._cfg['clock_moving'] = enabled
        cfg_mod.save(self._cfg)

    def _save_clock_style(self, index):
        self._cfg['clock_style'] = self._clock_style.itemData(index)
        cfg_mod.save(self._cfg)
        self._clock_preview.update()

    def _save_timeout(self, val: int):
        self._cfg["idle_timeout"] = val
        cfg_mod.save(self._cfg)

    def _save_anim(self, idx: int):
        types = ["bubbles", "matrix", "flurry", "slideshow", "none"]
        self._cfg["screensaver_type"] = types[idx]
        cfg_mod.save(self._cfg)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr('Select image folder'))
        if folder:
            folders = [self._folder_list.item(i).text() for i in range(self._folder_list.count())]
            folders = cfg_mod.get_slideshow_folders({'slideshow_folders': folders + [folder]})
            self._folder_list.clear()
            self._folder_list.addItems(folders)
            self._save_folders()

    def _remove_folders(self):
        for item in self._folder_list.selectedItems():
            self._folder_list.takeItem(self._folder_list.row(item))
        self._save_folders()

    def _save_folders(self):
        folders = [self._folder_list.item(i).text() for i in range(self._folder_list.count())]
        self._cfg['slideshow_folders'] = folders
        self._cfg['slideshow_folder'] = folders[0] if folders else ''
        cfg_mod.save(self._cfg)

    def _save_sync(self, enabled):
        self._cfg['slideshow_sync'] = enabled
        cfg_mod.save(self._cfg)

    def _save_interval(self, val: int):
        self._cfg["slideshow_interval"] = val
        cfg_mod.save(self._cfg)

    def _save_recursive(self, enabled):
        self._cfg['slideshow_recursive'] = enabled
        cfg_mod.save(self._cfg)


# ---------------------------------------------------------------------------
# About tab
# ---------------------------------------------------------------------------

APP_VERSION = "1.7.0-test4"
CONTRIBUTOR_NAME = "Lyle"
CONTRIBUTOR_EMAIL = "zjkljd@163.com"
WEBSITE_URL = "https://screenblind.cc"
DONATE_URL  = "https://www.paypal.com/donate/?hosted_button_id=ZXKFFGA7W6Y5E"


class AboutTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 24, 20, 20)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        # Logo — prefer the alpha-trimmed version so we don't get a white square
        logo_lbl = QLabel()
        logo_lbl.setFixedHeight(120)
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        for name in ("logo_screen_blind_transparent.png", "logo_screen_blind_highres.png"):
            p = _resource_path("media_assets", name)
            if p.exists():
                pix = QPixmap(str(p)).scaled(
                    120, 120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo_lbl.setPixmap(pix)
                break
        layout.addWidget(logo_lbl)

        # App name
        name = QLabel("ScreenBlind")
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name.setObjectName("brand")
        layout.addWidget(name)

        # Tagline
        tagline = QLabel(tr("Lock what others shouldn't see. Unlock what matters."))
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tagline.setFont(QFont("Microsoft YaHei UI", 10))
        layout.addWidget(tagline)

        # Version
        version = QLabel(tr("Version {version}", version=APP_VERSION))
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version)

        layout.addSpacing(14)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        site_btn = QPushButton(tr('  Visit website  '))
        site_btn.setObjectName("aboutBtn")
        site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        site_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE_URL)))
        btn_row.addWidget(site_btn)

        donate_btn = QPushButton(tr('  ❤  Donate  '))
        donate_btn.setObjectName("donateBtn")
        donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        btn_row.addWidget(donate_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addSpacing(10)

        # Description / credits block
        about_text = QLabel(
            tr('ScreenBlind selectively locks chosen displays while presentations, videos or dashboards remain visible on the others.\nMouse and keyboard input is captured until the correct password is entered.\n\nIncludes a system tray, global hotkeys, light/dark themes and English / Simplified Chinese.\nOriginal author: hemigapp · License: MIT')
        )
        about_text.setWordWrap(True)
        about_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(about_text)

        contributor = QLabel(tr("Enhancements: {name}\nContact: {email}",
                               name=CONTRIBUTOR_NAME, email=CONTRIBUTOR_EMAIL))
        contributor.setWordWrap(True)
        contributor.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        contributor.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(contributor)

        layout.addSpacing(12)

        # Disclaimer
        disclaimer = QLabel(
            tr('Usage and disclaimer\nScreenBlind is a privacy tool, not a replacement for the Windows lock screen. Win+L and Ctrl+Alt+Del are still handled by Windows. The software is provided as is, without warranty. Keep your password safe and have a recovery plan.')
        )
        disclaimer.setWordWrap(True)
        disclaimer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        disclaimer.setObjectName("aboutDisclaimer")
        layout.addWidget(disclaimer)

        layout.addStretch()

        # Footer with website URL as plain text
        footer = QLabel(f"<a href='{WEBSITE_URL}' style='color:#818cf8; text-decoration:none;'>screenblind.cc</a>")
        footer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        footer.setOpenExternalLinks(True)
        layout.addWidget(footer)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._cfg = cfg_mod.load()
        configure_language(QApplication.instance(), self._cfg.get("language", "system"))
        self._blind_manager: BlindManager | None = None
        self._remote_manager = None
        self._recovery_dialog = None
        self._watched_screens = weakref.WeakSet()
        self._screen_update_timer = QTimer(self)
        self._screen_update_timer.setSingleShot(True)
        self._screen_update_timer.timeout.connect(self._reconcile_screens)

        self.setWindowTitle(f"ScreenBlind v{APP_VERSION}")
        self.setMinimumSize(660, 640)
        self.setWindowIcon(_app_icon())

        self._build_ui()
        self._build_tray()
        self._hotkeys = GlobalHotkeys(QApplication.instance(), {
            "lock": self._on_lock_clicked, "settings": self.show_normal,
            "recovery": self._request_remote_recovery,
        })
        self._configure_hotkeys(initial=True)
        apply_theme(QApplication.instance(), self._cfg.get("theme", "dark"))
        app = QApplication.instance()
        app.screenAdded.connect(self._watch_screen)
        app.screenRemoved.connect(self._queue_screen_update)
        for screen in app.screens():
            self._watch_screen(screen)

    def _watch_screen(self, screen):
        if screen not in self._watched_screens:
            self._watched_screens.add(screen)
            for signal_name in ('geometryChanged', 'logicalDotsPerInchChanged', 'physicalDotsPerInchChanged'):
                signal = getattr(screen, signal_name, None)
                if signal is not None:
                    signal.connect(self._queue_screen_update)
        self._queue_screen_update()

    def _queue_screen_update(self, *args):
        self._screen_update_timer.start(0)

    def _reconcile_screens(self):
        self._monitors_tab.refresh()
        self._remote_tab.refresh()
        if self._blind_manager:
            self._blind_manager.reconcile_screens()
        if self._remote_manager:
            self._remote_manager.reconcile_screens()

    # -- UI ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header.setFixedHeight(64)
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        title = QLabel("ScreenBlind")
        title.setObjectName("brand")
        hl.addWidget(title)
        hl.addStretch()
        root.addWidget(header)

        # Tabs
        self._tabs = QTabWidget()
        self._monitors_tab = MonitorsTab(self._cfg)
        self._security_tab = SecurityTab(self._cfg)
        self._screensaver_tab = ScreensaverTab(self._cfg)
        self._about_tab = AboutTab()
        self._about_scroll = QScrollArea()
        self._about_scroll.setWidgetResizable(True)
        self._about_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._about_scroll.setWidget(self._about_tab)
        self._tabs.addTab(self._monitors_tab, tr('  Displays  '))
        self._tabs.addTab(self._security_tab, tr('  Security  '))
        self._tabs.addTab(self._screensaver_tab, tr('  Screensaver  '))
        self._general_tab = self._build_general_tab()
        self._tabs.addTab(self._general_tab, tr('  General  '))
        self._remote_tab = RemoteTab(self._cfg)
        self._remote_tab.toggleRequested.connect(self._toggle_remote)
        self._tabs.addTab(self._remote_tab, tr('  Remote  '))
        self._tabs.addTab(self._about_scroll, tr('  About  '))
        root.addWidget(self._tabs, 1)

        # Footer with lock button
        footer = QWidget()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 12, 18, 12)
        fl.addStretch()
        self._lock_btn = QPushButton(tr('  Lock now  '))
        self._lock_btn.setObjectName("lockBtn")
        self._lock_btn.setFixedHeight(48)
        self._lock_btn.clicked.connect(self._on_lock_clicked)
        fl.addWidget(self._lock_btn)
        fl.addStretch()
        root.addWidget(footer)

    def _build_tray(self):
        self._tray = QSystemTrayIcon(_app_icon(), self)
        self._refresh_tray_menu()
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _refresh_tray_menu(self):
        previous = self._tray.contextMenu()
        menu = QMenu(self)
        self._settings_action = menu.addAction(tr('Open settings'), self.show_normal)
        self._tray_lock_action = menu.addAction(tr('Lock now'), self._on_lock_clicked)
        self._remote_action = menu.addAction(tr('Exit remote mode (password required)') if self._remote_manager else tr('Enter remote mode'), self._toggle_remote)
        menu.addSeparator()
        self._exit_action = menu.addAction(tr('Exit'), self._exit_app)
        self._tray.setContextMenu(menu)
        self._set_locked_actions(bool(self._blind_manager))
        if previous:
            previous.deleteLater()

    # -- actions -------------------------------------------------------------

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_normal()

    def show_normal(self):
        if self._blind_manager:
            return
        if self._remote_manager and not self._request_remote_recovery():
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_lock_clicked(self):
        if self._remote_manager:
            self._remote_to_full_lock()
            return
        if self._blind_manager or getattr(self, "_lock_pending", False):
            return
        focus = QApplication.focusWidget()
        if QApplication.activeModalWidget() or (focus and any(
            edit is focus or edit.isAncestorOf(focus)
            for edit in self._shortcut_edits.values()
        )):
            return
        self._lock_pending = True
        try:
            self._start_lock()
        finally:
            self._lock_pending = False

    def _start_lock(self):
        if not self._cfg.get("password_hash"):
            self.show_normal()
            QMessageBox.warning(
                self, tr('No password'),
                tr('Set a password in the Security tab before locking.'),
            )
            self._tabs.setCurrentIndex(1)
            return

        # Refresh against connected displays so stale indices cannot create an empty lock.
        self._monitors_tab.refresh()
        locked = self._monitors_tab.selected_indices()
        if not locked:
            self.show_normal()
            QMessageBox.warning(
                self, tr('No displays selected'),
                tr('Select at least one display in the Displays tab.'),
            )
            self._tabs.setCurrentIndex(0)
            return

        self._cfg["locked_screens"] = locked
        cfg_mod.save(self._cfg)

        self._blind_manager = BlindManager(self._cfg, self)
        self._blind_manager.unlocked.connect(self._on_unlocked)
        if not self._blind_manager.lock():
            self._blind_manager.deleteLater()
            self._blind_manager = None
            self.show_normal()
            return
        self._set_locked_actions(True)
        self.hide()

    def _on_unlocked(self):
        if self._blind_manager:
            self._blind_manager.deleteLater()
            self._blind_manager = None
        self._set_locked_actions(False)
        self.hide()

    def _exit_app(self):
        if self._remote_manager and not self._request_remote_recovery():
            return
        if self._blind_manager:
            # Don't allow exit while locked — require password first
            QMessageBox.information(
                self, tr('Locked'),
                tr('Unlock the displays before exiting.'),
            )
            return
        self._hotkeys.close()
        self._tray.hide()
        QApplication.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if not getattr(self, "_tray_tip_shown", False) and not self._blind_manager:
            self._tray_tip_shown = True
            self._tray.showMessage(tr('ScreenBlind is still running'), tr('Minimized to the tray. Double-click the icon to open settings, or right-click to exit.'))

    def _set_locked_actions(self, locked):
        for action in (self._settings_action, self._tray_lock_action, self._exit_action):
            action.setEnabled(not locked)
        self._remote_action.setEnabled(not locked)
        self._remote_tab.set_active(bool(self._remote_manager))
        if self._remote_manager:
            self._tray.setToolTip(tr('Remote mode active · local screens covered'))
            return
        self._tray.setToolTip(tr('ScreenBlind · Locked; enter your password to unlock') if locked else tr("ScreenBlind v{version} · Running in the tray", version=APP_VERSION))

    def _toggle_remote(self):
        if self._blind_manager:
            return
        if self._remote_manager:
            self._request_remote_recovery()
            return
        if not self._cfg.get('password_hash'):
            self.show_normal()
            QMessageBox.warning(self, tr('No password'), tr('Set a password in the Security tab before locking.'))
            self._tabs.setCurrentIndex(1)
            return
        current = {screen_key(s) for s in QApplication.screens()}
        if not current.intersection(self._cfg.get('remote_allowed_screen_ids', [])):
            QMessageBox.warning(self, tr('No displays selected'), tr('Select at least one connected display for remote use.'))
            return
        manager = RemoteManager(self._cfg, self)
        self._remote_manager = manager
        manager.failed.connect(self._remote_failed)
        manager.fallbackRequested.connect(self._remote_to_full_lock)
        manager.recoveryRequested.connect(self._request_remote_recovery)
        if manager.start() and self._remote_manager is manager:
            self.hide()
            manager._guard_denied_foreground()
            self._refresh_tray_menu()
        elif self._remote_manager is manager:
            if manager.active:
                self._remote_to_full_lock()
            else:
                manager.deleteLater()
                self._remote_manager = None

    def _remote_failed(self, reason):
        self._remote_to_full_lock()
        self._tray.showMessage(tr('Remote mode unavailable'),
            tr('Remote protection could not be enabled. All displays remain password-locked.'))

    def _remote_to_full_lock(self):
        manager = self._remote_manager
        if manager is None:
            return
        if self._recovery_dialog:
            self._recovery_dialog.reject()
        cfg = copy.deepcopy(self._cfg)
        cfg['lock_all_screens'] = True
        normal = BlindManager(cfg, self)
        normal.unlocked.connect(self._on_unlocked)
        if normal.lock(allow_empty=True):
            self._blind_manager = normal
            manager.stop()
            manager.deleteLater()
            self._remote_manager = None
            self.hide()
            self._refresh_tray_menu()
        else:
            normal.deleteLater()  # Leave remote protection in place if fallback fails.

    def _request_remote_recovery(self):
        manager = self._remote_manager
        if manager is None:
            return False
        if self._recovery_dialog:
            self._recovery_dialog.raise_()
            self._recovery_dialog.activateWindow()
            return False
        dialog = RecoveryDialog(self._cfg, self)
        self._recovery_dialog = dialog
        screens = QApplication.screens()
        allowed = set(self._cfg.get('remote_allowed_screen_ids', []))
        screen = next((s for s in screens if screen_key(s) in allowed), QApplication.primaryScreen())
        if screen is not None:
            dialog.setGeometry(screen.geometry())
        # Masks remain installed throughout authentication.
        dialog.show()
        dialog.password.setFocus()
        manager.set_recovery_window(dialog)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self._recovery_dialog = None
        if self._remote_manager is manager:
            manager.set_recovery_window(None)
            if accepted:
                manager.stop()
                manager.deleteLater()
                self._remote_manager = None
                self._refresh_tray_menu()
        dialog.deleteLater()
        return accepted and self._remote_manager is None and self._blind_manager is None

    def _build_general_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(_label(tr('Language')))
        self._language_combo = WheelSafeComboBox()
        self._language_combo.addItem(tr('System default'), 'system')
        self._language_combo.addItem('English', 'en')
        self._language_combo.addItem('简体中文', 'zh_CN')
        self._language_combo.setCurrentIndex(max(0, self._language_combo.findData(self._cfg.get('language', 'system'))))
        self._language_combo.currentIndexChanged.connect(self._change_language)
        layout.addWidget(self._language_combo)
        layout.addWidget(_sep())
        self._startup_cb = QCheckBox(tr('Start with Windows (run in the tray after sign-in)'))
        self._startup_status = _label(tr('Off by default. Keep the executable in its current location after enabling.'), secondary=True)
        self._startup_status.setWordWrap(True)
        try:
            self._startup_cb.setChecked(startup.is_enabled())
        except OSError:
            self._startup_cb.setEnabled(False)
            self._startup_status.setText(tr('Cannot read startup settings. Check registry access for the current user.'))
        self._startup_cb.toggled.connect(self._change_startup)
        layout.addWidget(self._startup_cb)
        layout.addWidget(self._startup_status)
        layout.addWidget(_sep())
        layout.addWidget(_label(tr('Theme')))
        self._theme_combo = WheelSafeComboBox()
        self._theme_combo.addItem(tr('Dark'), "dark")
        self._theme_combo.addItem(tr('Light'), "light")
        self._theme_combo.setCurrentIndex(1 if self._cfg.get("theme") == "light" else 0)
        self._theme_combo.currentIndexChanged.connect(self._change_theme)
        layout.addWidget(self._theme_combo)
        layout.addWidget(_sep())
        layout.addWidget(_label(tr('Global hotkeys · Active while in the tray')))
        self._shortcut_edits = {}
        for action, label, key in (("lock", tr('Lock now'), "lock_hotkey"),
                                   ("settings", tr('Open settings'), "settings_hotkey"),
                                   ("recovery", tr('Restore local displays'), "remote_recovery_hotkey")):
            row = QHBoxLayout()
            row.addWidget(_label(label))
            edit = QKeySequenceEdit(QKeySequence(self._cfg[key]))
            edit.setAccessibleName(label + tr(' shortcut'))
            line_edit = edit.findChild(QLineEdit)
            if line_edit:
                line_edit.setPlaceholderText(tr('Not set; press a key combination'))
            row.addWidget(edit, 1)
            clear = QPushButton(tr('Clear'))
            clear.clicked.connect(edit.clear)
            row.addWidget(clear)
            layout.addLayout(row)
            self._shortcut_edits[action] = edit
        hint = _label(tr('Click a field and press a combination: Ctrl / Alt + a letter, digit or F1–F11; Shift is optional.\nClear and save to disable an action. Hotkeys cannot unlock displays.'), secondary=True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        save = QPushButton(tr('Save hotkeys'))
        save.clicked.connect(self._save_hotkeys)
        layout.addWidget(save)
        diagnostic = QPushButton(tr('Remote input diagnostic'))
        diagnostic.clicked.connect(self._show_input_diagnostic)
        layout.addWidget(diagnostic)
        mouse_diagnostic = QPushButton(tr('Mouse source diagnostic'))
        mouse_diagnostic.clicked.connect(self._show_mouse_diagnostic)
        layout.addWidget(mouse_diagnostic)
        self._hotkey_status = _label("", secondary=True)
        self._hotkey_status.setWordWrap(True)
        layout.addWidget(self._hotkey_status)
        layout.addWidget(_sep())
        note = _label(tr('Closing this window keeps ScreenBlind in the tray. Double-click the tray icon to open settings; right-click and choose Exit to quit.'), secondary=True)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        scroll.setWidget(tab)
        return scroll

    def _show_input_diagnostic(self):
        dialog = InputDiagnostics(self)
        dialog.exec()
        dialog.deleteLater()

    def _show_mouse_diagnostic(self):
        dialog = MouseDiagnostics(self)
        dialog.exec()
        dialog.deleteLater()

    def _change_language(self):
        if self._blind_manager:
            return
        choice = self._language_combo.currentData()
        if choice == self._cfg.get('language', 'system'):
            return
        self._cfg['language'] = choice
        cfg_mod.save(self._cfg)
        selected_tab = self._tabs.currentIndex()
        passwords = [edit.text() for edit in (
            self._security_tab._old_pw, self._security_tab._pw1, self._security_tab._pw2)]
        show_passwords = self._security_tab._show_cb.isChecked()
        shortcuts = {action: edit.keySequence() for action, edit in self._shortcut_edits.items()}
        self._monitors_tab._dismiss_identifiers()
        configure_language(QApplication.instance(), choice)
        previous = self.takeCentralWidget()
        self._build_ui()
        self._tabs.setCurrentIndex(selected_tab)
        for edit, text in zip((self._security_tab._old_pw, self._security_tab._pw1, self._security_tab._pw2), passwords):
            edit.setText(text)
        self._security_tab._show_cb.setChecked(show_passwords)
        for action, sequence in shortcuts.items():
            self._shortcut_edits[action].setKeySequence(sequence)
        self._refresh_tray_menu()
        self._configure_hotkeys()
        apply_theme(QApplication.instance(), self._cfg.get('theme', 'dark'))
        previous.deleteLater()

    def _change_startup(self, enabled):
        try:
            startup.set_enabled(enabled)
        except OSError:
            self._startup_cb.blockSignals(True)
            self._startup_cb.setChecked(not enabled)
            self._startup_cb.blockSignals(False)
            QMessageBox.warning(self, tr('Settings update failed'), tr('Cannot update startup settings. Check registry access for the current user.'))
            return
        self._startup_status.setText(tr('Enabled: ScreenBlind will run in the tray after your next Windows sign-in.') if enabled else tr('Windows startup is disabled.'))

    def _change_theme(self):
        theme = self._theme_combo.currentData()
        self._cfg["theme"] = theme
        cfg_mod.save(self._cfg)
        apply_theme(QApplication.instance(), theme)

    def _configure_hotkeys(self, initial=False):
        try:
            self._hotkeys.configure({"lock": self._cfg["lock_hotkey"],
                                     "settings": self._cfg["settings_hotkey"],
                                     "recovery": self._cfg['remote_recovery_hotkey']})
            self._hotkey_status.setText(tr('Hotkeys are active.') if any((self._cfg["lock_hotkey"], self._cfg["settings_hotkey"], self._cfg['remote_recovery_hotkey'])) else tr('All hotkeys are disabled.'))
        except ValueError as exc:
            self._hotkey_status.setText(str(exc) + tr(' Change the combination and save. The tray menu is still available.'))
            if initial:
                QTimer.singleShot(1600, lambda: self._tray.showMessage(tr('Hotkeys are unavailable'), self._hotkey_status.text()))

    def _save_hotkeys(self):
        shortcuts = {action: edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                     for action, edit in self._shortcut_edits.items()}
        try:
            self._hotkeys.configure(shortcuts)
        except ValueError as exc:
            QMessageBox.warning(self, tr('Hotkeys were not saved'), str(exc) + tr('\nYour previous hotkeys remain active.'))
            return
        self._cfg.update(lock_hotkey=shortcuts["lock"], settings_hotkey=shortcuts["settings"])
        self._cfg['remote_recovery_hotkey'] = shortcuts['recovery']
        cfg_mod.save(self._cfg)
        self._hotkey_status.setText(tr('Hotkeys saved and applied.'))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Before anything creates a window: tell Windows we handle scaling
    # ourselves, so monitor geometry is reported in real pixels instead of
    # being virtualised down. Without this, blinds on displays scaled above
    # 100% only cover part of the screen.
    dpi.enable_dpi_awareness()

    app = QApplication(sys.argv)
    app.setApplicationName("ScreenBlind")
    app.setQuitOnLastWindowClosed(False)

    configure_language(app, cfg_mod.load().get('language', 'system'))
    app.setStyle("Fusion")

    # App-wide icon
    app.setWindowIcon(_app_icon())

    guard = InstanceGuard(cfg_mod._path().parent, app)
    try:
        if not guard.acquire():
            return
    except RuntimeError as exc:
        QMessageBox.warning(None, tr('Unable to start'), str(exc))
        return
    app.aboutToQuit.connect(guard.close)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, tr('Error'), tr('The system tray is unavailable. ScreenBlind cannot start.'))
        sys.exit(1)

    win = MainWindow()

    guard.activated.connect(win.show_normal)
    if "--startup" not in sys.argv:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
