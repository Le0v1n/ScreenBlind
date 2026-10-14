import math
import random
from collections import deque
from pathlib import Path

from i18n import tr
from PyQt6.QtCore import QLineF, QObject, QRect, QRectF, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtCore import Qt


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class BaseAnimation(QObject):
    FPS = 30

    # Alpha of the black veil the overlay lays over the animation, so the
    # clock stays readable. Bright, sparse animations want less of it.
    DIM_OVERLAY = 70

    def background_color(self) -> QColor | None:
        """Override to paint over the overlay's hue-shifting gradient."""
        return None

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
# Flurry
# ---------------------------------------------------------------------------

class FlurryAnimation(BaseAnimation):
    """
    Particle streamers in the style of the classic Flurry screensaver.

    Several emitters orbit a shared point that itself wanders the screen, so
    the streams stay tangled together as one bouquet instead of drifting off
    as separate sprays. Each emitter throws a fan of particles in its own
    slowly-rotating colour, and every particle curls around that shared centre
    — the curl is what turns a plain starburst into Flurry's silky ribbons.

    Rendered additively on black. Trails are drawn as batched line segments
    with flat caps rather than stroked paths: Qt has a fast path for exactly
    that shape, and it renders ~7x quicker, which is what makes trails this
    long affordable on several 1440p monitors at once.
    """

    FPS = 30
    DIM_OVERLAY = 20          # bright on black already; barely veil it

    STREAMS = 5
    TRAIL_LEN = 22
    PARTICLES_PER_STREAM = 52
    MAX_AGE = 420             # frames; a safety net, most exit the screen first
    SPRITE_PX = 20

    # (first index, last index, pen width, alpha) over the trail, newest first.
    # Bands share an endpoint so the ribbon tapers without seams.
    BANDS = (
        (0, 3, 3.0, 170),
        (3, 7, 2.2, 115),
        (7, 12, 1.6, 70),
        (12, 17, 1.1, 40),
        (17, 21, 0.8, 20),
    )

    def __init__(self, widget):
        super().__init__(widget)
        self._streams: list[dict] = []
        self._t = 0.0
        self._frame = 0
        self._scale = 1.0
        self._wx = 0.0        # shared wandering centre the streams orbit
        self._wy = 0.0

    def background_color(self) -> QColor:
        return QColor(4, 4, 10)

    # -- setup ---------------------------------------------------------------

    def reset(self):
        w = self.widget.width() or 1920
        h = self.widget.height() or 1080
        self._t = 0.0
        self._frame = 0
        # Keep motion looking the same regardless of monitor size
        self._scale = max(0.6, min(2.0, min(w, h) / 1080.0))
        self._wx, self._wy = w / 2.0, h / 2.0

        # Cost grows with screen area — a ribbon on a 4K panel is simply more
        # pixels to rasterise. Thin the particle count out on big displays so
        # one blind can't monopolise the GUI thread when several are locked.
        area_ratio = (w * h) / (1920.0 * 1080.0)
        density = 1.0 / max(1.0, area_ratio) ** 0.5
        count = max(18, int(self.PARTICLES_PER_STREAM * density))

        self._streams = []
        hue0 = random.uniform(0, 360)
        for i in range(self.STREAMS):
            hue = (hue0 + i * (360.0 / self.STREAMS)) % 360
            stream = {
                "hue": hue,
                "color": self._hue_color(hue),
                "sprite": None,
                "phase": random.uniform(0, math.tau),
                "orbit": random.uniform(0.55, 1.05) * random.choice((1, -1)),
                "angle": random.uniform(0, math.tau),
                "spin": random.uniform(0.030, 0.070) * random.choice((1, -1)),
                "curl": random.uniform(1.2, 2.2) * random.choice((1, -1)),
                "ex": w / 2.0,
                "ey": h / 2.0,
                "parts": [],
            }
            stream["sprite"] = self._make_sprite(stream["color"])
            for _ in range(count):
                stream["parts"].append(self._spawn(stream))
            self._streams.append(stream)

    @staticmethod
    def _hue_color(hue: float) -> QColor:
        return QColor.fromHslF((hue % 360) / 360.0, 0.85, 0.62)

    def _make_sprite(self, color: QColor) -> QPixmap:
        """Soft additive glow blob used for each particle head."""
        d = self.SPRITE_PX
        px = QPixmap(d, d)
        px.fill(Qt.GlobalColor.transparent)

        core = QColor(255, 255, 255, 205)
        mid = QColor(color)
        mid.setAlpha(150)
        outer = QColor(color)
        outer.setAlpha(0)

        grad = QRadialGradient(d / 2.0, d / 2.0, d / 2.0)
        grad.setColorAt(0.0, core)
        grad.setColorAt(0.28, mid)
        grad.setColorAt(1.0, outer)

        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(0, 0, d, d)
        p.end()
        return px

    def _spawn(self, stream: dict) -> dict:
        ang = stream["angle"] + random.gauss(0.0, 0.22)
        speed = random.uniform(1.3, 3.4) * self._scale
        x = stream["ex"] + random.gauss(0.0, 4.0)
        y = stream["ey"] + random.gauss(0.0, 4.0)
        trail = deque(maxlen=self.TRAIL_LEN)
        trail.append((x, y))
        return {
            "x": x, "y": y,
            "vx": math.cos(ang) * speed,
            "vy": math.sin(ang) * speed,
            "age": 0,
            "trail": trail,
        }

    # -- simulation ----------------------------------------------------------

    def advance(self):
        w = self.widget.width() or 1920
        h = self.widget.height() or 1080
        cx, cy = w / 2.0, h / 2.0
        self._t += 1.0 / self.FPS
        self._frame += 1

        # Recolour a few times a second — cheap, and the sprites must follow
        recolour = self._frame % 12 == 0
        margin = 90 * self._scale

        # The whole bouquet drifts on a Lissajous path...
        self._wx = wx = cx + (w * 0.13) * math.sin(self._t * 0.23) \
                                        * math.cos(self._t * 0.17)
        self._wy = wy = cy + (h * 0.13) * math.sin(self._t * 0.19 + 1.1)
        orbit_r = min(w, h) * 0.08

        for s in self._streams:
            # ...and each emitter circles it, so the streams stay interwoven
            ph = s["phase"] + self._t * s["orbit"]
            s["ex"] = wx + orbit_r * math.cos(ph)
            s["ey"] = wy + orbit_r * math.sin(ph)
            s["angle"] += s["spin"]

            if recolour:
                s["hue"] = (s["hue"] + 3.0) % 360
                s["color"] = self._hue_color(s["hue"])
                s["sprite"] = self._make_sprite(s["color"])

            curl = s["curl"]
            for i, p in enumerate(s["parts"]):
                dx = p["x"] - wx
                dy = p["y"] - wy
                d = math.hypot(dx, dy) or 1e-3

                # Tangential swirl around the bouquet, strongest near the
                # middle — this is what bends the streamers into ribbons
                nx, ny = dx / d, dy / d
                k = curl * 60.0 / d
                p["vx"] += -ny * k
                p["vy"] += nx * k

                # Gentle outward drift so streamers keep extending, plus drag
                p["vx"] = (p["vx"] + nx * 0.05) * 0.988
                p["vy"] = (p["vy"] + ny * 0.05) * 0.988

                p["x"] += p["vx"]
                p["y"] += p["vy"]
                p["age"] += 1
                p["trail"].appendleft((p["x"], p["y"]))

                off_screen = (
                    p["x"] < -margin or p["x"] > w + margin
                    or p["y"] < -margin or p["y"] > h + margin
                )
                if off_screen or p["age"] > self.MAX_AGE:
                    s["parts"][i] = self._spawn(s)

    # -- drawing -------------------------------------------------------------

    def draw(self, painter: QPainter, rect: QRect):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        for s in self._streams:
            base = s["color"]
            for lo, hi, width, alpha in self.BANDS:
                segments: list[QLineF] = []
                for p in s["parts"]:
                    t = p["trail"]
                    if len(t) <= lo + 1:
                        continue
                    end = min(len(t), hi + 1)
                    for i in range(lo, end - 1):
                        segments.append(QLineF(t[i][0], t[i][1],
                                               t[i + 1][0], t[i + 1][1]))
                if not segments:
                    continue
                c = QColor(base)
                c.setAlpha(alpha)
                # FlatCap is not just cosmetic: it is the shape Qt has a fast
                # antialiased path for. RoundCap costs ~7x more here.
                painter.setPen(QPen(
                    c, width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.FlatCap,
                    Qt.PenJoinStyle.BevelJoin,
                ))
                painter.drawLines(segments)

        # Particle heads (these also hide the flat cap at the tip),
        # then a soft bloom on each emitter
        for s in self._streams:
            spr = s["sprite"]
            off = spr.width() / 2.0
            for p in s["parts"]:
                painter.drawPixmap(int(p["x"] - off), int(p["y"] - off), spr)

            bloom = self.SPRITE_PX * 3.6
            painter.setOpacity(0.5)
            painter.drawPixmap(
                QRectF(s["ex"] - bloom / 2, s["ey"] - bloom / 2, bloom, bloom),
                spr, QRectF(spr.rect()),
            )
            painter.setOpacity(1.0)

        # Hand the painter back the way we found it — the overlay still has
        # the dim veil, clock and password prompt to draw on top.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


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
                             tr('No images found in the selected folder'))
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
    if name == "flurry":
        return FlurryAnimation(widget)
    if name == "slideshow":
        return SlideshowAnimation(
            widget,
            settings.get("slideshow_folder", ""),
            settings.get("slideshow_interval", 5),
        )
    return None
