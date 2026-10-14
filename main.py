"""
ScreenBlind – selective multi-monitor lock screen.
Entry point + settings UI.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, QLocale, QTranslator, QLibraryInfo
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
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QKeySequenceEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import auth
import dpi
import settings as cfg_mod
from blind import BlindManager
from hotkeys import GlobalHotkeys
from themes import apply_theme
from instance import InstanceGuard


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

        layout.addWidget(_label("选择需要锁定的显示器："))

        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.itemChanged.connect(self._on_change)
        layout.addWidget(self._list)

        row = QHBoxLayout()
        refresh_btn = QPushButton("↻  刷新显示器")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)

        identify_btn = QPushButton("🔢  识别显示器")
        identify_btn.setToolTip("在每个已连接的显示器上显示编号")
        identify_btn.clicked.connect(self.identify_screens)
        row.addWidget(identify_btn)

        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(_label(
            "提示：未锁定的显示器继续显示内容；锁定期间鼠标和键盘仅用于解锁。",
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
        self._list.blockSignals(True)
        self._list.clear()
        self._items.clear()
        screens = QApplication.screens()
        locked = set(self._cfg.get("locked_screens", []))
        primary = QApplication.primaryScreen()

        for i, screen in enumerate(screens):
            native = dpi.native_geometry(screen)
            label = (
                f"显示器 {i + 1}"
                + ("（主显示器）" if screen is primary else "")
                + f"  —  {_resolution_text(screen)}"
                + f"  位置（{native.x()}, {native.y()}）"
            )
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if i in locked else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
            self._items.append((item, i))

        self._list.blockSignals(False)

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
        self._old_pw_lbl = _label("当前密码：")
        layout.addWidget(self._old_pw_lbl)
        self._old_pw = QLineEdit()
        self._old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._old_pw.setPlaceholderText("输入当前密码")
        layout.addWidget(self._old_pw)

        layout.addWidget(_label("新密码："))
        self._pw1 = QLineEdit()
        self._pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw1.setPlaceholderText("输入新密码")
        layout.addWidget(self._pw1)

        layout.addWidget(_label("确认新密码："))
        self._pw2 = QLineEdit()
        self._pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw2.setPlaceholderText("再次输入新密码")
        layout.addWidget(self._pw2)

        show_cb = QCheckBox("显示密码")
        show_cb.toggled.connect(self._toggle_show)
        layout.addWidget(show_cb)

        layout.addWidget(_sep())

        self._set_btn = QPushButton("设置密码")
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
            "已设置密码。" if has else "尚未设置密码。"
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
            f"忘记密码？退出软件后，删除以下设置文件可重置：\n{settings_path}"
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
                    self, "密码错误",
                    "当前密码不正确。",
                )
                self._old_pw.clear()
                self._old_pw.setFocus()
                return

        p1, p2 = self._pw1.text(), self._pw2.text()
        if not p1:
            QMessageBox.warning(self, "密码为空", "新密码不能为空。")
            return
        if p1 != p2:
            QMessageBox.warning(self, "密码不一致", "两次输入的新密码不一致。")
            return

        self._cfg["password_hash"] = auth.hash_password(p1)
        cfg_mod.save(self._cfg)
        self._refresh_ui()
        QMessageBox.information(self, "完成", "密码已更新。")



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
        layout.addWidget(_label("空闲多久后启动屏保："))
        row1 = QHBoxLayout()
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 3600)
        self._timeout_spin.setValue(cfg.get("idle_timeout", 120))
        self._timeout_spin.setSuffix("  秒")
        self._timeout_spin.setFixedWidth(160)
        self._timeout_spin.valueChanged.connect(self._save_timeout)
        row1.addWidget(self._timeout_spin)
        row1.addStretch()
        layout.addLayout(row1)

        layout.addWidget(_sep())

        # Animation type
        layout.addWidget(_label("屏保样式："))
        self._anim_combo = QComboBox()
        self._anim_combo.addItems(["气泡", "数字雨", "流光", "图片幻灯片", "无"])
        type_map = {"bubbles": 0, "matrix": 1, "flurry": 2, "slideshow": 3, "none": 4}
        self._anim_combo.setCurrentIndex(type_map.get(cfg.get("screensaver_type", "bubbles"), 0))
        self._anim_combo.currentIndexChanged.connect(self._save_anim)
        layout.addWidget(self._anim_combo)

        layout.addWidget(_sep())

        # Slideshow options
        layout.addWidget(_label("幻灯片选项："))
        self._folder_lbl = _label(cfg.get("slideshow_folder") or "未选择文件夹", secondary=True)
        layout.addWidget(self._folder_lbl)

        row2 = QHBoxLayout()
        browse_btn = QPushButton("选择文件夹…")
        browse_btn.clicked.connect(self._browse_folder)
        row2.addWidget(browse_btn)
        row2.addStretch()
        layout.addLayout(row2)

        layout.addWidget(_label("每张图片的显示时长："))
        row3 = QHBoxLayout()
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 300)
        self._interval_spin.setValue(cfg.get("slideshow_interval", 5))
        self._interval_spin.setSuffix("  秒")
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
        types = ["bubbles", "matrix", "flurry", "slideshow", "none"]
        self._cfg["screensaver_type"] = types[idx]
        cfg_mod.save(self._cfg)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
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

APP_VERSION = "1.2.0"
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
        tagline = QLabel("遮住私密内容，让需要展示的画面继续显示。")
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tagline.setFont(QFont("Microsoft YaHei UI", 10))
        layout.addWidget(tagline)

        # Version
        version = QLabel(f"版本 {APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version)

        layout.addSpacing(14)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        site_btn = QPushButton("  访问原项目网站  ")
        site_btn.setObjectName("aboutBtn")
        site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        site_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE_URL)))
        btn_row.addWidget(site_btn)

        donate_btn = QPushButton("  ❤  支持原作者  ")
        donate_btn.setObjectName("donateBtn")
        donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        btn_row.addWidget(donate_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addSpacing(10)

        # Description / credits block
        about_text = QLabel(
            "ScreenBlind 可选择性地锁定显示器，其他显示器继续显示演示、视频或看板。\n"
            "锁定期间鼠标和键盘由锁屏接管，输入正确密码后统一解锁。\n\n"
            "本分支增加中文界面、托盘驻留、全局快捷键与浅色 / 深色主题。\n"
            "原项目作者：hemigapp · 开源许可：MIT"
        )
        about_text.setWordWrap(True)
        about_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(about_text)

        layout.addSpacing(12)

        # Disclaimer
        disclaimer = QLabel(
            "使用说明与免责声明\n"
            "本软件是隐私遮挡工具，不能替代 Windows 系统锁屏。"
            "Win+L 和 Ctrl+Alt+Del 仍由系统处理。"
            "软件按现状提供，不作任何担保；请妥善保管密码，并保留恢复方式。"
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
        self._blind_manager: BlindManager | None = None

        self.setWindowTitle(f"ScreenBlind v{APP_VERSION}")
        self.setMinimumSize(660, 640)
        self.setWindowIcon(_app_icon())

        self._build_ui()
        self._build_tray()
        self._hotkeys = GlobalHotkeys(QApplication.instance(), {
            "lock": self._on_lock_clicked, "settings": self.show_normal,
        })
        self._configure_hotkeys(initial=True)
        apply_theme(QApplication.instance(), self._cfg.get("theme", "dark"))

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
        self._tabs.addTab(self._monitors_tab, "  显示器  ")
        self._tabs.addTab(self._security_tab, "  安全  ")
        self._tabs.addTab(self._screensaver_tab, "  屏保  ")
        self._general_tab = self._build_general_tab()
        self._tabs.addTab(self._general_tab, "  通用  ")
        self._tabs.addTab(self._about_scroll, "  关于  ")
        root.addWidget(self._tabs, 1)

        # Footer with lock button
        footer = QWidget()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 12, 18, 12)
        fl.addStretch()
        self._lock_btn = QPushButton("  立即锁定  ")
        self._lock_btn.setObjectName("lockBtn")
        self._lock_btn.setFixedHeight(48)
        self._lock_btn.clicked.connect(self._on_lock_clicked)
        fl.addWidget(self._lock_btn)
        fl.addStretch()
        root.addWidget(footer)

    def _build_tray(self):
        self._tray = QSystemTrayIcon(_app_icon(), self)
        menu = QMenu()
        self._settings_action = menu.addAction("打开设置", self.show_normal)
        self._tray_lock_action = menu.addAction("立即锁定", self._on_lock_clicked)
        menu.addSeparator()
        self._exit_action = menu.addAction("退出软件", self._exit_app)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip(f"ScreenBlind v{APP_VERSION}")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    # -- actions -------------------------------------------------------------

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_normal()

    def show_normal(self):
        if self._blind_manager:
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_lock_clicked(self):
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
                self, "尚未设置密码",
                "请先在“安全”页面设置密码，再锁定显示器。",
            )
            self._tabs.setCurrentIndex(1)
            return

        # Refresh against connected displays so stale indices cannot create an empty lock.
        self._monitors_tab.refresh()
        locked = self._monitors_tab.selected_indices()
        if not locked:
            self.show_normal()
            QMessageBox.warning(
                self, "尚未选择显示器",
                "请先在“显示器”页面选择至少一个显示器。",
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
        self.show_normal()

    def _exit_app(self):
        if self._blind_manager:
            # Don't allow exit while locked — require password first
            QMessageBox.information(
                self, "已锁定",
                "请先输入密码解锁，再退出软件。",
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
            self._tray.showMessage("ScreenBlind 仍在运行", "已收起到托盘。双击图标恢复设置，右键菜单可退出软件。")

    def _set_locked_actions(self, locked):
        for action in (self._settings_action, self._tray_lock_action, self._exit_action):
            action.setEnabled(not locked)
        self._tray.setToolTip("ScreenBlind · 已锁定，请输入密码解锁" if locked else f"ScreenBlind v{APP_VERSION} · 后台运行")

    def _build_general_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(_label("界面主题"))
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("深色", "dark")
        self._theme_combo.addItem("浅色", "light")
        self._theme_combo.setCurrentIndex(1 if self._cfg.get("theme") == "light" else 0)
        self._theme_combo.currentIndexChanged.connect(self._change_theme)
        layout.addWidget(self._theme_combo)
        layout.addWidget(_sep())
        layout.addWidget(_label("全局快捷键 · 收起到托盘后仍然有效"))
        self._shortcut_edits = {}
        for action, label, key in (("lock", "立即锁定", "lock_hotkey"),
                                   ("settings", "打开设置", "settings_hotkey")):
            row = QHBoxLayout()
            row.addWidget(_label(label))
            edit = QKeySequenceEdit(QKeySequence(self._cfg[key]))
            edit.setAccessibleName(label + "快捷键")
            row.addWidget(edit, 1)
            clear = QPushButton("清除")
            clear.clicked.connect(edit.clear)
            row.addWidget(clear)
            layout.addLayout(row)
            self._shortcut_edits[action] = edit
        hint = _label("点击输入框后按下组合键。支持 Ctrl / Alt + 字母、数字或 F1–F11，可加 Shift。\n清空后保存可禁用该操作；快捷键无法直接解锁。", secondary=True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        save = QPushButton("保存快捷键")
        save.clicked.connect(self._save_hotkeys)
        layout.addWidget(save)
        self._hotkey_status = _label("", secondary=True)
        self._hotkey_status.setWordWrap(True)
        layout.addWidget(self._hotkey_status)
        layout.addWidget(_sep())
        note = _label("关闭窗口后继续驻留托盘。双击托盘图标打开设置，右键选择“退出软件”可完全退出。", secondary=True)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return tab

    def _change_theme(self):
        theme = self._theme_combo.currentData()
        self._cfg["theme"] = theme
        cfg_mod.save(self._cfg)
        apply_theme(QApplication.instance(), theme)

    def _configure_hotkeys(self, initial=False):
        try:
            self._hotkeys.configure({"lock": self._cfg["lock_hotkey"],
                                     "settings": self._cfg["settings_hotkey"]})
            self._hotkey_status.setText("快捷键设置已生效。" if any((self._cfg["lock_hotkey"], self._cfg["settings_hotkey"])) else "已禁用全部快捷键。")
        except ValueError as exc:
            self._hotkey_status.setText(str(exc) + " 请修改后保存；托盘菜单仍可使用。")
            if initial:
                QTimer.singleShot(1600, lambda: self._tray.showMessage("快捷键未启用", self._hotkey_status.text()))

    def _save_hotkeys(self):
        shortcuts = {action: edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                     for action, edit in self._shortcut_edits.items()}
        try:
            self._hotkeys.configure(shortcuts)
        except ValueError as exc:
            QMessageBox.warning(self, "快捷键未保存", str(exc) + "\n原有快捷键保持不变。")
            return
        self._cfg.update(lock_hotkey=shortcuts["lock"], settings_hotkey=shortcuts["settings"])
        cfg_mod.save(self._cfg)
        self._hotkey_status.setText("快捷键已保存并生效。")


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

    QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    translator = QTranslator(app)
    translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    app.installTranslator(translator)
    app.setStyle("Fusion")

    # App-wide icon
    app.setWindowIcon(_app_icon())

    guard = InstanceGuard(cfg_mod._path().parent, app)
    try:
        if not guard.acquire():
            return
    except RuntimeError as exc:
        QMessageBox.warning(None, "无法启动", str(exc))
        return
    app.aboutToQuit.connect(guard.close)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "错误", "当前系统不支持托盘图标，无法启动。")
        sys.exit(1)

    win = MainWindow()

    guard.activated.connect(win.show_normal)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
