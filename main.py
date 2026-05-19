"""
ScreenBlind – selective multi-monitor lock screen.
Entry point + settings UI.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QTimer, QUrl
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplashScreen,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import auth
import settings as cfg_mod
from blind import BlindManager


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

STYLE = """
QMainWindow, QWidget {
    background-color: #0a0a12;
    color: #ededf5;
    font-family: 'Segoe UI';
    font-size: 13px;
}

/* --- Tabs --- */
QTabWidget::pane {
    border: none;
    border-top: 1px solid #1c1c28;
    background-color: #0a0a12;
}
QTabBar {
    background: #0d0d18;
}
QTabBar::tab {
    background: transparent;
    color: #55557a;
    padding: 11px 24px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
    font-size: 13px;
}
QTabBar::tab:selected {
    color: #ededf5;
    border-bottom: 2px solid #6366f1;
}
QTabBar::tab:hover:!selected {
    color: #9898c0;
    background: #12121e;
}

/* --- Buttons --- */
QPushButton {
    background-color: #16162a;
    color: #c8c8e8;
    border: 1px solid #222238;
    padding: 7px 18px;
    border-radius: 6px;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #1e1e38;
    border-color: #6366f1;
    color: #ededf5;
}
QPushButton:pressed {
    background-color: #101024;
}
QPushButton#lockBtn {
    background-color: #e11d48;
    color: #ffffff;
    font-size: 15px;
    font-weight: 600;
    padding: 14px 40px;
    border-radius: 8px;
    border: none;
    letter-spacing: 1px;
}
QPushButton#lockBtn:hover {
    background-color: #f43f5e;
}
QPushButton#lockBtn:pressed {
    background-color: #be123c;
}
QPushButton#lockBtn:disabled {
    background-color: #2d0a18;
    color: #553040;
    border: none;
}

QPushButton#aboutBtn {
    background-color: #1a1a2e;
    color: #c7d2fe;
    border: 1px solid #3730a3;
    padding: 10px 20px;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton#aboutBtn:hover {
    background-color: #20203a;
    border-color: #6366f1;
    color: #ffffff;
}

QPushButton#donateBtn {
    background-color: #be123c;
    color: #ffffff;
    border: none;
    padding: 10px 22px;
    border-radius: 6px;
    font-weight: 600;
}
QPushButton#donateBtn:hover {
    background-color: #e11d48;
}

QLabel#aboutDisclaimer {
    background-color: #1a160a;
    border: 1px solid #4a3a0a;
    border-radius: 8px;
    color: #d4c9a0;
    padding: 12px 16px;
    font-size: 11px;
    line-height: 1.55;
}

/* --- Inputs --- */
QLineEdit {
    background-color: #0d0d1a;
    color: #ededf5;
    border: 1px solid #1e1e32;
    padding: 8px 12px;
    border-radius: 6px;
    selection-background-color: #6366f1;
}
QLineEdit:focus {
    border-color: #6366f1;
    background-color: #0f0f1e;
}
QLineEdit:disabled {
    color: #44445a;
    border-color: #16161e;
}

QSpinBox {
    background-color: #0d0d1a;
    color: #ededf5;
    border: 1px solid #1e1e32;
    padding: 7px 10px;
    border-radius: 6px;
    selection-background-color: #6366f1;
}
QSpinBox:focus { border-color: #6366f1; }
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    border: none;
    background: #16162a;
    border-radius: 3px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #6366f1;
}

QComboBox {
    background-color: #0d0d1a;
    color: #ededf5;
    border: 1px solid #1e1e32;
    padding: 7px 10px;
    border-radius: 6px;
    selection-background-color: #6366f1;
}
QComboBox:focus { border-color: #6366f1; }
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #12121e;
    color: #ededf5;
    border: 1px solid #222238;
    selection-background-color: #25254a;
    outline: none;
}

/* --- List --- */
QListWidget {
    background-color: #0d0d1a;
    color: #ededf5;
    border: 1px solid #1e1e32;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 5px;
}
QListWidget::item:selected {
    background-color: #1e1e3c;
    color: #ededf5;
}
QListWidget::item:hover:!selected {
    background-color: #14141f;
}

/* --- Checkbox --- */
QCheckBox {
    color: #ededf5;
    spacing: 9px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #333358;
    border-radius: 4px;
    background: #0d0d1a;
}
QCheckBox::indicator:hover {
    border-color: #6366f1;
}
QCheckBox::indicator:checked {
    background: #6366f1;
    border-color: #6366f1;
}

/* --- Labels --- */
QLabel { color: #ededf5; }
QLabel[secondary="true"] { color: #44446a; font-size: 11px; }

/* --- Separator --- */
QFrame[role="separator"] {
    background-color: #181826;
    max-height: 1px;
    margin: 5px 0;
}

/* --- Scrollbar --- */
QScrollBar:vertical {
    background: transparent;
    width: 5px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a2a48;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #6366f1; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


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

    def __init__(self, screen, number: int):
        super().__init__(None)
        self._screen = screen
        self._number = number

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
        g = self._screen.geometry()
        painter.drawText(
            rect.adjusted(0, 0, 0, -22),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            f"{g.width()} × {g.height()}",
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

        layout.addWidget(_label("Select screens to lock:"))

        self._list = QListWidget()
        self._list.setSpacing(2)
        layout.addWidget(self._list)

        row = QHBoxLayout()
        refresh_btn = QPushButton("↻  Refresh Displays")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)

        identify_btn = QPushButton("🔢  Identify")
        identify_btn.setToolTip("Show a big number on each connected screen")
        identify_btn.clicked.connect(self.identify_screens)
        row.addWidget(identify_btn)

        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(_label(
            "Tip: the screens you do NOT lock remain fully usable.",
            secondary=True,
        ))

        self.refresh()

    def identify_screens(self):
        """Flash a big number on every connected screen for ~3 seconds."""
        self._dismiss_identifiers()
        for i, screen in enumerate(QApplication.screens()):
            ov = _ScreenIdentifierOverlay(screen, i + 1)
            ov.show()
            self._identify_overlays.append(ov)
        QTimer.singleShot(3000, self._dismiss_identifiers)

    def _dismiss_identifiers(self):
        for o in self._identify_overlays:
            o.close()
        self._identify_overlays.clear()

    def refresh(self):
        self._list.clear()
        self._items.clear()
        screens = QApplication.screens()
        locked = set(self._cfg.get("locked_screens", []))
        primary = QApplication.primaryScreen()

        for i, screen in enumerate(screens):
            geo = screen.geometry()
            label = (
                f"Screen {i + 1}"
                + (" (Primary)" if screen is primary else "")
                + f"  —  {geo.width()} × {geo.height()}"
                + f"  at ({geo.x()}, {geo.y()})"
            )
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if i in locked else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
            self._items.append((item, i))

        self._list.itemChanged.connect(self._on_change)

    def _on_change(self, _item):
        self._cfg["locked_screens"] = [
            idx for item, idx in self._items
            if item.checkState() == Qt.CheckState.Checked
        ]
        cfg_mod.save(self._cfg)

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
        self._old_pw_lbl = _label("Current password:")
        layout.addWidget(self._old_pw_lbl)
        self._old_pw = QLineEdit()
        self._old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._old_pw.setPlaceholderText("Enter current password")
        layout.addWidget(self._old_pw)

        layout.addWidget(_label("New password:"))
        self._pw1 = QLineEdit()
        self._pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw1.setPlaceholderText("Enter new password")
        layout.addWidget(self._pw1)

        layout.addWidget(_label("Confirm new password:"))
        self._pw2 = QLineEdit()
        self._pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw2.setPlaceholderText("Repeat new password")
        layout.addWidget(self._pw2)

        show_cb = QCheckBox("Show passwords")
        show_cb.toggled.connect(self._toggle_show)
        layout.addWidget(show_cb)

        layout.addWidget(_sep())

        self._set_btn = QPushButton("Set Password")
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
            "Password is set." if has else "No password set yet."
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
            f"Forgot your password? Delete the settings file to reset:\n{settings_path}"
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
                    self, "Wrong Password",
                    "The current password you entered is incorrect.",
                )
                self._old_pw.clear()
                self._old_pw.setFocus()
                return

        p1, p2 = self._pw1.text(), self._pw2.text()
        if not p1:
            QMessageBox.warning(self, "Empty Password", "New password cannot be empty.")
            return
        if p1 != p2:
            QMessageBox.warning(self, "Mismatch", "New passwords do not match.")
            return

        self._cfg["password_hash"] = auth.hash_password(p1)
        cfg_mod.save(self._cfg)
        self._refresh_ui()
        QMessageBox.information(self, "Done", "Password updated successfully.")



# ---------------------------------------------------------------------------
# Screensaver tab
# ---------------------------------------------------------------------------

class ScreensaverTab(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Idle timeout
        layout.addWidget(_label("Start screensaver after idle:"))
        row1 = QHBoxLayout()
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 3600)
        self._timeout_spin.setValue(cfg.get("idle_timeout", 120))
        self._timeout_spin.setSuffix("  seconds")
        self._timeout_spin.setFixedWidth(160)
        self._timeout_spin.valueChanged.connect(self._save_timeout)
        row1.addWidget(self._timeout_spin)
        row1.addStretch()
        layout.addLayout(row1)

        layout.addWidget(_sep())

        # Animation type
        layout.addWidget(_label("Animation style:"))
        self._anim_combo = QComboBox()
        self._anim_combo.addItems(["Bubbles", "Matrix", "Image Slideshow", "None"])
        type_map = {"bubbles": 0, "matrix": 1, "slideshow": 2, "none": 3}
        self._anim_combo.setCurrentIndex(type_map.get(cfg.get("screensaver_type", "bubbles"), 0))
        self._anim_combo.currentIndexChanged.connect(self._save_anim)
        layout.addWidget(self._anim_combo)

        layout.addWidget(_sep())

        # Slideshow options
        layout.addWidget(_label("Slideshow options:"))
        self._folder_lbl = _label(cfg.get("slideshow_folder") or "No folder selected", secondary=True)
        layout.addWidget(self._folder_lbl)

        row2 = QHBoxLayout()
        browse_btn = QPushButton("Browse Folder…")
        browse_btn.clicked.connect(self._browse_folder)
        row2.addWidget(browse_btn)
        row2.addStretch()
        layout.addLayout(row2)

        layout.addWidget(_label("Seconds per image:"))
        row3 = QHBoxLayout()
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 300)
        self._interval_spin.setValue(cfg.get("slideshow_interval", 5))
        self._interval_spin.setSuffix("  sec")
        self._interval_spin.setFixedWidth(120)
        self._interval_spin.valueChanged.connect(self._save_interval)
        row3.addWidget(self._interval_spin)
        row3.addStretch()
        layout.addLayout(row3)

        layout.addStretch()

    def _save_timeout(self, val: int):
        self._cfg["idle_timeout"] = val
        cfg_mod.save(self._cfg)

    def _save_anim(self, idx: int):
        types = ["bubbles", "matrix", "slideshow", "none"]
        self._cfg["screensaver_type"] = types[idx]
        cfg_mod.save(self._cfg)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            self._cfg["slideshow_folder"] = folder
            self._folder_lbl.setText(folder)
            cfg_mod.save(self._cfg)

    def _save_interval(self, val: int):
        self._cfg["slideshow_interval"] = val
        cfg_mod.save(self._cfg)


# ---------------------------------------------------------------------------
# About tab
# ---------------------------------------------------------------------------

APP_VERSION = "1.0.0"
WEBSITE_URL = "https://screenblind.cc"
DONATE_URL  = "https://screenblind.cc/donate"   # placeholder — replace with direct donation link


class AboutTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 24, 20, 20)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Logo — prefer the alpha-trimmed version so we don't get a white square
        logo_lbl = QLabel()
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
        name.setFont(QFont("Segoe UI Semibold", 22))
        name.setStyleSheet("color: #a5b4fc; letter-spacing: 1px;")
        layout.addWidget(name)

        # Tagline
        tagline = QLabel("Lock what others shouldn't see. Unlock what matters.")
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tagline.setFont(QFont("Segoe UI", 10))
        tagline.setStyleSheet("color: #8b8ba8; font-style: italic;")
        layout.addWidget(tagline)

        # Version
        version = QLabel(f"Version {APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        version.setStyleSheet("color: #6b6b85; font-size: 11px;")
        layout.addWidget(version)

        layout.addSpacing(14)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        site_btn = QPushButton("  Visit Website  ")
        site_btn.setObjectName("aboutBtn")
        site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        site_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE_URL)))
        btn_row.addWidget(site_btn)

        donate_btn = QPushButton("  ❤  Donate  ")
        donate_btn.setObjectName("donateBtn")
        donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        btn_row.addWidget(donate_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addSpacing(10)

        # Description / credits block
        about_text = QLabel(
            "ScreenBlind selectively locks chosen monitors while the others\n"
            "stay visible and keep displaying their content — perfect for\n"
            "leaving a presentation, video, or dashboard on screen while\n"
            "you step away from your desk. Mouse and keyboard input stays\n"
            "captured by the lock until the correct password is entered.\n\n"
            "If you find ScreenBlind useful, consider supporting development\n"
            "via the donate button above. Thank you!"
        )
        about_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        about_text.setStyleSheet("color: #c8c8d8; font-size: 12px; line-height: 1.5;")
        layout.addWidget(about_text)

        layout.addSpacing(12)

        # Disclaimer
        disclaimer = QLabel(
            "⚖  USE AT YOUR OWN RISK\n"
            "ScreenBlind is provided “as is”, without warranty of any kind. "
            "The authors and contributors are not liable for any damages or "
            "loss arising from use of this software — including being unable "
            "to access a locked screen due to a forgotten password. Keep a "
            "recovery plan in place before relying on it."
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
        footer.setStyleSheet("font-size: 11px;")
        layout.addWidget(footer)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._cfg = cfg_mod.load()
        self._blind_manager: BlindManager | None = None

        self.setWindowTitle(f"ScreenBlind v{APP_VERSION}")
        self.setMinimumSize(520, 480)
        self.setWindowIcon(_app_icon())

        self._build_ui()
        self._build_tray()

    # -- UI ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header.setFixedHeight(54)
        header.setStyleSheet("background-color: #07070f; border-bottom: 1px solid #141420;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        title = QLabel("ScreenBlind")
        title.setFont(QFont("Segoe UI Semibold", 14))
        title.setStyleSheet("color: #a5b4fc; letter-spacing: 1px;")
        hl.addWidget(title)
        hl.addStretch()
        root.addWidget(header)

        # Tabs
        self._tabs = QTabWidget()
        self._monitors_tab = MonitorsTab(self._cfg)
        self._security_tab = SecurityTab(self._cfg)
        self._screensaver_tab = ScreensaverTab(self._cfg)
        self._about_tab = AboutTab()
        self._tabs.addTab(self._monitors_tab, "  Monitors  ")
        self._tabs.addTab(self._security_tab, "  Security  ")
        self._tabs.addTab(self._screensaver_tab, "  Screensaver  ")
        self._tabs.addTab(self._about_tab, "  About  ")
        root.addWidget(self._tabs, 1)

        # Footer with lock button
        footer = QWidget()
        footer.setStyleSheet("background-color: #07070f; border-top: 1px solid #141420;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 12, 18, 12)
        fl.addStretch()
        self._lock_btn = QPushButton("  LOCK NOW  ")
        self._lock_btn.setObjectName("lockBtn")
        self._lock_btn.setFixedHeight(48)
        self._lock_btn.clicked.connect(self._on_lock_clicked)
        fl.addWidget(self._lock_btn)
        fl.addStretch()
        root.addWidget(footer)

    def _build_tray(self):
        self._tray = QSystemTrayIcon(_app_icon(), self)
        menu = QMenu()
        menu.setStyleSheet("background:#1a1a38; color:#dde0f0; padding:4px;")
        menu.addAction("Open Settings", self.show_normal)
        menu.addAction("Lock Now", self._on_lock_clicked)
        menu.addSeparator()
        menu.addAction("Exit", self._exit_app)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip(f"ScreenBlind v{APP_VERSION}")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    # -- actions -------------------------------------------------------------

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_normal()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_lock_clicked(self):
        self._cfg = cfg_mod.load()  # pick up any changes

        if not self._cfg.get("password_hash"):
            QMessageBox.warning(
                self, "No Password",
                "Please set a password in the Security tab before locking.",
            )
            self._tabs.setCurrentIndex(1)
            return

        locked = self._monitors_tab.selected_indices()
        if not locked:
            QMessageBox.warning(
                self, "No Screens Selected",
                "Please select at least one screen to lock in the Monitors tab.",
            )
            self._tabs.setCurrentIndex(0)
            return

        self._cfg["locked_screens"] = locked
        cfg_mod.save(self._cfg)

        self._blind_manager = BlindManager(self._cfg, self)
        self._blind_manager.unlocked.connect(self._on_unlocked)
        self._blind_manager.lock()
        self.hide()

    def _on_unlocked(self):
        if self._blind_manager:
            self._blind_manager.deleteLater()
            self._blind_manager = None
        self.show_normal()

    def _exit_app(self):
        if self._blind_manager:
            # Don't allow exit while locked — require password first
            QMessageBox.information(
                self, "Locked",
                "Please unlock the screen before exiting.",
            )
            return
        QApplication.quit()

    def closeEvent(self, event):
        if self._blind_manager:
            event.ignore()
            QMessageBox.information(
                self, "Locked",
                "Please unlock the screen before exiting.",
            )
            return
        self._tray.hide()
        event.accept()
        QApplication.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _show_splash(app: QApplication) -> QSplashScreen | None:
    """Show a branded splash while the app boots. Returns None if no image found."""
    # First match wins — drop a splash.png to override the default artwork
    for name in ("splash.png", "splashscreen_screenblind.png", "screenblind_header.png"):
        path = _resource_path("media_assets", name)
        if path.exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                pix = pix.scaledToWidth(
                    720,
                    Qt.TransformationMode.SmoothTransformation,
                )
                splash = QSplashScreen(
                    pix,
                    Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.FramelessWindowHint,
                )
                splash.show()
                app.processEvents()
                return splash
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ScreenBlind")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)

    # App-wide icon
    app.setWindowIcon(_app_icon())

    splash = _show_splash(app)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        if splash:
            splash.close()
        QMessageBox.critical(None, "Error", "System tray not available on this system.")
        sys.exit(1)

    win = MainWindow()

    def _reveal():
        win.show()
        if splash:
            splash.finish(win)

    # Hold the splash for ~1.4s so users actually see it, then reveal the window
    QTimer.singleShot(1400, _reveal)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
