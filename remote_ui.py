"""Remote allowlist configuration and black-background password recovery."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QVBoxLayout, QWidget)
import auth
import settings
from displays import display_name, migrate_display_settings, screen_key
from i18n import tr
from widgets import PasswordEdit


class RemoteTab(QWidget):
    toggleRequested = pyqtSignal()

    def __init__(self, cfg):
        super().__init__()
        self._cfg, self._active = cfg, False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        explanation = QLabel(tr('Local displays are black. Only checked displays remain visible and usable to supported remote capture software.'))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.screen_list = QListWidget()
        self.screen_list.itemChanged.connect(self._save_selection)
        layout.addWidget(self.screen_list)
        note = QLabel(tr('UU compatibility awaits a live test. Newly connected displays are denied by default. Exit remote mode with your password before changing this list.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.block_local_mouse = QCheckBox(tr('Block local mouse during remote mode (experimental)'))
        self.block_local_mouse.setChecked(bool(cfg.get('remote_block_local_mouse', False)))
        self.block_local_mouse.toggled.connect(self._save_mouse_filter)
        layout.addWidget(self.block_local_mouse)
        mouse_note = QLabel(tr('Off by default. Blocks unmarked mouse movement, clicks and scrolling; allows injected input. Source flags were tested with this UU setup; filtering still needs a live test. Local keyboard recovery stays available; configure a recovery hotkey before testing. This is not a system security boundary.'))
        mouse_note.setWordWrap(True)
        layout.addWidget(mouse_note)
        self.block_local_keyboard = QCheckBox(tr('Block local keyboard during remote mode (experimental)'))
        self.block_local_keyboard.setChecked(bool(cfg.get('remote_block_local_keyboard', False)))
        self.block_local_keyboard.toggled.connect(self._save_keyboard_filter)
        layout.addWidget(self.block_local_keyboard)
        keyboard_note = QLabel(tr('Only your configured lock/restore hotkeys can open password recovery. Local typing is allowed only while the recovery box has focus; Ctrl/Alt/Win shortcuts remain blocked. Cancel to resume blocking. Injected remote input stays enabled. Ctrl+Alt+Delete cannot be blocked.'))
        keyboard_note.setWordWrap(True)
        layout.addWidget(keyboard_note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.button = QPushButton()
        self.button.clicked.connect(self.toggleRequested)
        layout.addWidget(self.button)
        self.refresh()
        self.set_active(False)

    def refresh(self):
        screens = QApplication.screens()
        if migrate_display_settings(self._cfg, screens, QApplication.primaryScreen()):
            settings.save(self._cfg)
        self.screen_list.blockSignals(True)
        self.screen_list.clear()
        selected = set(self._cfg.get('remote_allowed_screen_ids', []))
        for index, screen in enumerate(screens):
            item = QListWidgetItem(display_name(screen, index, self._cfg))
            item.setData(Qt.ItemDataRole.UserRole, screen_key(screen))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if screen_key(screen) in selected else Qt.CheckState.Unchecked)
            self.screen_list.addItem(item)
        self.screen_list.blockSignals(False)

    def _save_selection(self, item):
        if self._active:
            self.refresh()
            return
        present = {self.screen_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.screen_list.count())}
        offline = [key for key in self._cfg.get('remote_allowed_screen_ids', []) if key not in present]
        self._cfg['remote_allowed_screen_ids'] = offline + [self.screen_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.screen_list.count()) if self.screen_list.item(i).checkState() == Qt.CheckState.Checked]
        settings.save(self._cfg)

    def set_active(self, active):
        self._active = active
        self.screen_list.setEnabled(not active)
        self.block_local_mouse.setEnabled(not active)
        self.block_local_keyboard.setEnabled(not active)
        self.button.setText(tr('Exit remote mode (password required)') if active else tr('Enter remote mode'))
        self.status.setText(tr('Remote mode active · local screens covered') if active else tr('Remote mode is off. It does not start automatically.'))

    def _save_mouse_filter(self, checked):
        if self._active:
            self.block_local_mouse.blockSignals(True)
            self.block_local_mouse.setChecked(bool(self._cfg.get('remote_block_local_mouse', False)))
            self.block_local_mouse.blockSignals(False)
            return
        self._cfg['remote_block_local_mouse'] = checked
        settings.save(self._cfg)

    def _save_keyboard_filter(self, checked):
        if self._active:
            self.block_local_keyboard.blockSignals(True)
            self.block_local_keyboard.setChecked(bool(self._cfg.get('remote_block_local_keyboard', False)))
            self.block_local_keyboard.blockSignals(False)
            return
        self._cfg['remote_block_local_keyboard'] = checked
        settings.save(self._cfg)


class RecoveryDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self._cfg = cfg
        self.setWindowTitle(tr('Restore local displays'))
        self.setStyleSheet('QDialog { background: black; color: white; } QLabel { background: transparent; color: white; }')
        layout = QVBoxLayout(self)
        layout.addStretch()
        title = QLabel(tr('Enter your password to restore local displays'))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)
        self.password = PasswordEdit(self)
        self.password.setMaximumWidth(380)
        self.password.setPlaceholderText(tr('Enter password'))
        self.password.textEdited.connect(self._match)
        self.password.returnPressed.connect(self._submit)
        self.password.cancelled.connect(self.reject)
        layout.addWidget(self.password, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        cancel = QPushButton(tr('Cancel'))
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()

    def _match(self, text):
        if auth.verify_password(text, self._cfg.get('password_hash', '')):
            self.accept()

    def _submit(self):
        if auth.verify_password(self.password.text(), self._cfg.get('password_hash', '')):
            self.accept()
        else:
            self.password.clear()
            self.status.setText(tr('Incorrect password'))

    def done(self, result):
        self.password.clear()
        super().done(result)
