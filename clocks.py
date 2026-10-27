"""Shared clock rendering for lock overlays and the settings preview."""
from PyQt6.QtCore import QDateTime, QLocale, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from i18n import tr


CLOCK_STYLES = ('classic', 'minimal', 'panel')


def clock_bounds(rect, rel_x=0.5, rel_y=0.38):
    """Keep every style within the display and above the password panel."""
    scale = min(1.25, rect.width() * 0.86 / 520, rect.height() * 0.30 / 200)
    width, height = 520 * scale, 200 * scale
    left, top = rect.left() + 20, rect.top() + 52
    right, bottom = rect.right() - 20, rect.top() + rect.height() * 0.59
    cx = max(left + width / 2, min(rect.left() + rect.width() * rel_x, right - width / 2))
    cy = max(top + height / 2, min(rect.top() + rect.height() * rel_y, bottom - height / 2))
    return QRectF(cx - width / 2, cy - height / 2, width, height)


def _font(size, weight=QFont.Weight.Light, family='Segoe UI'):
    font = QFont(family)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def draw_clock(painter: QPainter, bounds: QRectF, style='classic', now=None):
    now = now if now is not None else QDateTime.currentDateTime()
    date = QLocale().toString(now, tr('dddd, MMMM d'))
    center = Qt.AlignmentFlag.AlignCenter
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(bounds.center())
    scale = min(bounds.width() / 520, bounds.height() / 200)
    painter.scale(scale, scale)

    if style == 'panel':
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.setBrush(QColor(12, 18, 32, 190))
        painter.drawRoundedRect(QRectF(-250, -94, 500, 188), 24, 24)
        painter.setPen(QColor('#c7d2fe'))
        painter.setFont(_font(88, QFont.Weight.DemiBold))
        painter.drawText(QRectF(-224, -74, 360, 112), center, now.toString('HH:mm'))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(165, 180, 252, 30))
        painter.drawRoundedRect(QRectF(156, -44, 66, 60), 14, 14)
        painter.setPen(QColor('#e0e7ff'))
        painter.setFont(_font(32, QFont.Weight.Medium))
        painter.drawText(QRectF(156, -44, 66, 60), center, now.toString('ss'))
        painter.setPen(QColor(220, 226, 246, 215))
        painter.setFont(_font(22, QFont.Weight.Normal, 'Microsoft YaHei UI'))
        painter.drawText(QRectF(-224, 45, 448, 32), center, date)
    elif style == 'minimal':
        painter.setPen(QColor(255, 255, 255, 245))
        painter.setFont(_font(112))
        painter.drawText(QRectF(-250, -100, 500, 142), center, now.toString('HH:mm'))
        painter.setPen(QPen(QColor(255, 255, 255, 100), 1))
        painter.drawLine(-24, 47, 24, 47)
        painter.setFont(_font(21, QFont.Weight.Normal, 'Microsoft YaHei UI'))
        painter.setPen(QColor(255, 255, 255, 215))
        painter.drawText(QRectF(-250, 61, 500, 32), center, date)
    else:
        # Center the complete group, including seconds, rather than just HH:mm.
        time_font, sec_font = _font(108), _font(34)
        time = now.toString('HH:mm')
        time_width = QFontMetricsF(time_font).horizontalAdvance(time)
        sec_width = QFontMetricsF(sec_font).horizontalAdvance('00')
        x = -(time_width + 14 + sec_width) / 2
        painter.setFont(time_font)
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(QRectF(x, -96, time_width, 136), center, time)
        painter.setFont(sec_font)
        painter.setPen(QColor(199, 210, 254, 220))
        painter.drawText(QRectF(x + time_width + 14, -5, sec_width, 42), center, now.toString('ss'))
        painter.setFont(_font(23, QFont.Weight.Normal, 'Microsoft YaHei UI'))
        painter.setPen(QColor(214, 220, 246, 215))
        painter.drawText(QRectF(-250, 55, 500, 36), center, date)
    painter.restore()
