"""Settings inputs that let wheel events scroll the page instead of changing values."""
from PyQt6.QtWidgets import QComboBox, QSpinBox


class WheelSafeComboBox(QComboBox):
    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class WheelSafeSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()
