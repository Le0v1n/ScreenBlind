"""Settings inputs that let wheel events scroll the page instead of changing values."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QSpinBox, QLineEdit


class WheelSafeComboBox(QComboBox):
    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class WheelSafeSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class PasswordEdit(QLineEdit):
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setInputMethodHints(Qt.InputMethodHint.ImhHiddenText |
                                 Qt.InputMethodHint.ImhSensitiveData |
                                 Qt.InputMethodHint.ImhNoPredictiveText)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wake_key = None

    def keyPressEvent(self, event):
        if event.isAutoRepeat() and event.key() == self.wake_key:
            event.accept()
            return
        self.wake_key = None
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat() and event.key() == self.wake_key:
            self.wake_key = None
        super().keyReleaseEvent(event)
