"""Opt-in mouse flag sampling. Never suppresses, records positions or writes files."""
from collections import Counter

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from i18n import tr
from mouse_hook import MouseHook, MousePacket, EVENTS


class MouseSampler(MouseHook):
    def __init__(self):
        super().__init__()
        self.counts = Counter()

    def start(self):
        super().start()
        self.counts.clear()

    def handle_mouse(self, message, flags):
        self.counts[(EVENTS[message], bool(flags & 1), bool(flags & 2))] += 1
        return False

    def summary(self):
        lines = ['mouse events=' + str(sum(self.counts.values()))]
        for (kind, injected, lower), count in sorted(self.counts.items()):
            lines.append(f'{kind} injected={int(injected)} lower_integrity={int(lower)} count={count}')
        return '\n'.join(lines)


class MouseDiagnostics(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Mouse source diagnostic'))
        self.resize(650, 480)
        self.sampler = MouseSampler()
        self._phase = ''
        self._seconds = 0
        layout = QVBoxLayout(self)
        note = QLabel(tr('Run two separate samples: local mouse only, then phone UU only. Each sample lasts 15 seconds. Move, click and scroll over this window. Input is never blocked. Only event counts and injection flags are kept in memory; no coordinates or key text are collected. Injection flags do not prove the source is UU.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        self._buttons = []
        for label in ('Sample local mouse', 'Sample phone UU'):
            button = QPushButton(tr(label))
            button.clicked.connect(lambda checked=False, phase=label: self.start_sample(phase))
            layout.addWidget(button)
            self._buttons.append(button)
        self.status = QLabel(tr('Ready'))
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(200)
        layout.addWidget(self.log)
        self.stop_button = QPushButton(tr('Stop sample'))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_sample)
        layout.addWidget(self.stop_button)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)

    def start_sample(self, phase):
        try:
            self.sampler.start()
        except (OSError, RuntimeError) as error:
            self.status.setText(tr('Mouse diagnostic unavailable: {error}', error=str(error)))
            return
        self._phase = phase
        self._seconds = 15
        for button in self._buttons:
            button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.timer.start()
        self.refresh_status()

    def refresh_status(self):
        self.status.setText(tr('Sampling: {seconds}s remaining; {count} events',
                               seconds=self._seconds, count=sum(self.sampler.counts.values())))

    def tick(self):
        self._seconds -= 1
        if self._seconds <= 0:
            self.stop_sample()
        else:
            self.refresh_status()

    def stop_sample(self):
        self.timer.stop()
        was_collecting = self.sampler.active
        try:
            self.sampler.stop()
        except OSError as error:
            self.status.setText(tr('Mouse diagnostic unavailable: {error}', error=str(error)))
            return
        if was_collecting:
            self.log.appendPlainText(tr(self._phase) + '\n' + self.sampler.summary() + '\n')
        for button in self._buttons:
            button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status.setText(tr('Ready'))

    def done(self, result):
        self.stop_sample()
        self.sampler.counts.clear()
        self.log.clear()
        super().done(result)
