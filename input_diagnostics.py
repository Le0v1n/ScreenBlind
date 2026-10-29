"""Opt-in, in-memory comparison using test text, never the lock password."""
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt
from i18n import tr


class InputProbe(QLineEdit):
    def __init__(self, report, legacy=False):
        super().__init__()
        self._report, self._legacy = report, legacy
        self.setInputMethodHints(Qt.InputMethodHint.ImhNoPredictiveText)

    def keyPressEvent(self, event):
        self._report(f'key={event.key():x} scan={event.nativeScanCode()} native={event.nativeVirtualKey()} '
                     f'repeat={event.isAutoRepeat()} count={event.count()} units={len(event.text())}')
        if self._legacy:
            if event.key() == Qt.Key.Key_Backspace:
                self.setText(self.text()[:-1])
            elif event.text().isprintable():
                self.setText(self.text() + event.text())
            event.accept()
        else:
            super().keyPressEvent(event)

    def inputMethodEvent(self, event):
        self._report(f'ime preedit_units={len(event.preeditString())} commit_units={len(event.commitString())} '
                     f'replace_from={event.replacementStart()} replace_units={event.replacementLength()}')
        if self._legacy:
            event.ignore()
        else:
            super().inputMethodEvent(event)


class InputDiagnostics(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Remote input diagnostic'))
        self.resize(620, 460)
        layout = QVBoxLayout(self)
        note = QLabel(tr('Use test text only, such as aabb1122. Do not enter your password. Logs contain event metadata only and are not saved.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(200)
        layout.addWidget(QLabel(tr('Previous input path (comparison):')))
        self.legacy = InputProbe(lambda text: self.log.appendPlainText('legacy ' + text), legacy=True)
        layout.addWidget(self.legacy)
        layout.addWidget(QLabel(tr('Standard input path:')))
        self.standard = InputProbe(lambda text: self.log.appendPlainText('standard ' + text))
        layout.addWidget(self.standard)
        layout.addWidget(self.log)
        clear = QPushButton(tr('Clear'))
        clear.clicked.connect(self.clear)
        layout.addWidget(clear)

    def clear(self):
        self.legacy.clear()
        self.standard.clear()
        self.log.clear()

    def done(self, result):
        self.clear()
        super().done(result)
