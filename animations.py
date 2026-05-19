import math
import random
from pathlib import Path

from PyQt6.QtCore import QObject, QRect, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtCore import Qt


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class BaseAnimation(QObject):
    FPS = 30

    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // self.FPS)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self.advance()
        self.widget.update()

    def start(self):
        self.reset()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def reset(self):
        pass

    def advance(self):
        pass

    def draw(self, painter: QPainter, rect: QRect):
        pass


# ---------------------------------------------------------------------------
# Bubbles
# ---------------------------------------------------------------------------

class BubblesAnimation(BaseAnimation):
    MAX_BUBBLES = 25

    def __init__(self, widget):
        super().__init__(widget)
        self._bubbles: list[dict] = []

    def reset(self):
        self._bubbles.clear()
        w = self.widget.width() or 1920
        h = self.widget.height() or 1080
        for _ in range(self.MAX_BUBBLES):
            self._bubbles.append(self._new_bubble(w, h, random_y=True))

    def _new_bubble(self, w: int, h: int, random_y: bool = False) -> dict:
        r = random.randint(12, 65)
        return {
            "x": float(random.randint(r, max(r + 1, w - r))),
            "y": float(random.randint(0, h) if random_y else h + r + 10),
            "r": r,
            "speed": random.uniform(0.4, 1.8),
            "wobble": random.uniform(0, math.tau),
            "wobble_speed": random.uniform(0.015, 0.045),
            "color": QColor(
                random.randint(40, 120),
                random.randint(100, 200),
                random.randint(180, 255),
                random.randint(35, 90),
            ),
        }

    def advance(self):
        w = self.widget.width() or 1920
        h = self.widget.height() or 1080
        alive = []
        for b in self._bubbles:
            b["y"] -= b["speed"]
            b["wobble"] += b["wobble_speed"]
            b["x"] += math.sin(b["wobble"]) * 0.6
            if b["y"] + b["r"] > 0:
                alive.append(b)
        self._bubbles = alive
        while len(self._bubbles) < self.MAX_BUBBLES:
            self._bubbles.append(self._new_bubble(w, h))

    def draw(self, painter: QPainter, rect: QRect):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for b in self._bubbles:
            c = b["color"]
            rim = QColor(c.red(), c.green(), c.blue(), min(255, c.alpha() + 80))
            painter.setPen(QPen(rim, 1.5))
            painter.setBrush(QBrush(c))
            x, y, r = int(b["x"]), int(b["y"]), b["r"]
            painter.drawEllipse(x - r, y - r, r * 2, r * 2)
            # inner highlight
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 30))
            painter.drawEllipse(x - r // 2, y - r, r // 2, r // 2)


# ---------------------------------------------------------------------------
# Matrix rain
# ---------------------------------------------------------------------------

class MatrixAnimation(BaseAnimation):
    CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*アイウエオカキクケコサシスセソ"
    COL_W = 18
    FPS = 20

    def __init__(self, widget):
        super().__init__(widget)
        self._cols: list[dict] = []

    def reset(self):
        self._cols.clear()
        w = self.widget.width() or 1920
        h = self.widget.height() or 1080
        n = max(1, w // self.COL_W)
        for i in range(n):
            self._cols.append(self._new_col(i, h, random_y=True))

    def _new_col(self, idx: int, h: int, random_y: bool = False) -> dict:
        length = random.randint(6, 24)
        return {
            "x": idx * self.COL_W,
            "y": random.randint(-h, 0) if random_y else random.randint(-300, -20),
            "speed": random.randint(1, 3),
            "length": length,
            "chars": [random.choice(self.CHARS) for _ in range(length + 2)],
        }

    def advance(self):
        h = self.widget.height() or 1080
        for col in self._cols:
            col["y"] += col["speed"]
            if random.random() < 0.08:
                i = random.randint(0, len(col["chars"]) - 1)
                col["chars"][i] = random.choice(self.CHARS)
            if col["y"] - col["length"] * self.COL_W > h:
                idx = col["x"] // self.COL_W
                col.update(self._new_col(idx, h))

    def draw(self, painter: QPainter, rect: QRect):
        font = QFont("Courier New", self.COL_W - 4)
        font.setBold(True)
        painter.setFont(font)
        for col in self._cols:
            for i in range(col["length"]):
                y = col["y"] - i * self.COL_W
                if not (0 <= y <= rect.height()):
                    continue
                if i == 0:
                    color = QColor(210, 255, 210)
                else:
                    alpha = max(0, 255 - int(i * 255 / col["length"]))
                    color = QColor(0, 210, 70, alpha)
                painter.setPen(color)
                ci = (col["y"] // max(1, self.COL_W) + i) % len(col["chars"])
                painter.drawText(col["x"], y, col["chars"][ci])


# ---------------------------------------------------------------------------
# Slideshow
# ---------------------------------------------------------------------------

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class SlideshowAnimation(BaseAnimation):
    FPS = 30

    def __init__(self, widget, folder: str, interval_sec: int = 5):
        super().__init__(widget)
        self._folder = folder
        self._interval_ms = max(1, interval_sec) * 1000
        self._images: list[Path] = []
        self._idx = 0
        self._current: QPixmap | None = None
        self._next: QPixmap | None = None
        self._alpha = 1.0          # opacity of _current (fades out)
        self._transitioning = False

        self._slide_timer = QTimer(self)
        self._slide_timer.setSingleShot(False)
        self._slide_timer.timeout.connect(self._start_transition)

    def reset(self):
        self._images = []
        if self._folder:
            p = Path(self._folder)
            if p.is_dir():
                self._images = [f for f in p.iterdir()
                                if f.suffix.lower() in SUPPORTED_EXT]
                random.shuffle(self._images)
        self._idx = 0
        self._current = self._load(0)
        self._next = None
        self._alpha = 1.0
        self._transitioning = False

    def _load(self, idx: int) -> QPixmap | None:
        if not self._images:
            return None
        return QPixmap(str(self._images[idx % len(self._images)]))

    def start(self):
        super().start()
        if len(self._images) > 1:
            self._slide_timer.start(self._interval_ms)

    def stop(self):
        super().stop()
        self._slide_timer.stop()

    def _start_transition(self):
        if len(self._images) < 2:
            return
        self._idx = (self._idx + 1) % len(self._images)
        self._next = self._load(self._idx)
        self._alpha = 1.0
        self._transitioning = True

    def advance(self):
        if self._transitioning:
            self._alpha = max(0.0, self._alpha - 0.025)
            if self._alpha <= 0.0:
                self._current = self._next
                self._next = None
                self._alpha = 1.0
                self._transitioning = False

    def draw(self, painter: QPainter, rect: QRect):
        if not self._current:
            painter.setPen(QColor(100, 100, 120))
            font = QFont("Segoe UI", 16)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             "No images found in selected folder")
            return

        def blit(px: QPixmap, opacity: float):
            scaled = px.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.setOpacity(opacity)
            painter.drawPixmap(x, y, scaled)
            painter.setOpacity(1.0)

        if self._transitioning and self._next:
            blit(self._next, 1.0)
            blit(self._current, self._alpha)
        else:
            blit(self._current, 1.0)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_animation(name: str, widget, settings: dict) -> BaseAnimation | None:
    if name == "bubbles":
        return BubblesAnimation(widget)
    if name == "matrix":
        return MatrixAnimation(widget)
    if name == "slideshow":
        return SlideshowAnimation(
            widget,
            settings.get("slideshow_folder", ""),
            settings.get("slideshow_interval", 5),
        )
    return None
