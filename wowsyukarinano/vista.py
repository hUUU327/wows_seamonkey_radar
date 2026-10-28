"""The window look: a frameless Aero glass frame in sky blue and pink, and a framed picture.

GlassWindow  paints its own glass frame, title bar and caption buttons; content goes into .body
Picture      a still picture with rounded corners, a glass sheen and a caption bar
"""
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QRadialGradient)
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

FONT = "Segoe UI, Microsoft YaHei UI, Microsoft YaHei"
SHADOW = 14          # px of soft shadow around the window
RADIUS = 8
TITLE_H = 28         # the painted title bar
FRAME = 5            # the glass frame's width at the sides and the bottom

STYLE = f"""
QWidget {{ color: #2b3a4f; font-family: {FONT}; font-size: 10pt; }}
"""


def glass_gradient(rect, top, bottom):
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0.0, top)
    gradient.setColorAt(1.0, bottom)
    return gradient


class CaptionButton(QPushButton):
    """Sky-blue glass for minimize, pink glass for close."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(QSize(34 if kind == "close" else 24, 17))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QPushButton { border: none; background: transparent; min-height: 0; padding: 0; }")
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover, pressed = self.underMouse(), self.isDown()
        if self.kind == "close":
            top, mid, low = ((QColor(255, 175, 210), QColor(228, 110, 160), QColor(180, 60, 110)) if hover else
                             (QColor(246, 182, 210), QColor(214, 132, 172), QColor(168, 86, 126)))
        else:
            top, mid, low = ((QColor(175, 220, 250), QColor(110, 172, 220), QColor(64, 122, 176)) if hover else
                             (QColor(206, 226, 242), QColor(150, 180, 208), QColor(108, 140, 172)))
        if pressed:
            top, mid = mid, low
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(0.5, mid)
        gradient.setColorAt(0.51, low)
        gradient.setColorAt(1.0, mid)
        path = QPainterPath()
        path.addRoundedRect(rect, 3, 3)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(70, 95, 125, 190), 1))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 2, 2)
        painter.setPen(QPen(QColor(48, 66, 92), 1.8 if self.kind == "close" else 2.0,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        center = rect.center()
        if self.kind == "close":
            reach = 3.5
            painter.drawLine(QPointF(center.x() - reach, center.y() - reach),
                             QPointF(center.x() + reach, center.y() + reach))
            painter.drawLine(QPointF(center.x() - reach, center.y() + reach),
                             QPointF(center.x() + reach, center.y() - reach))
        else:
            painter.drawLine(QPointF(center.x() - 4, center.y() + 3), QPointF(center.x() + 4, center.y() + 3))


class GlassWindow(QWidget):
    """Frameless window with the glass frame. Put content into self.body."""

    def __init__(self, title, icon=None, caption=None):
        """title: the window title Windows shows; caption: the text painted in the title bar."""
        super().__init__()
        self.caption = caption
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setStyleSheet(STYLE)
        self.icon = icon
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW + FRAME, SHADOW + TITLE_H, SHADOW + FRAME, SHADOW + FRAME)
        outer.setSpacing(0)
        self.body = QWidget()
        self.body.setObjectName("body")
        outer.addWidget(self.body)
        self.btn_min = CaptionButton("min", self)
        self.btn_close = CaptionButton("close", self)
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_close.clicked.connect(self.close)

    def resizeEvent(self, event):
        width = self.width()
        self.btn_close.move(width - SHADOW - RADIUS - self.btn_close.width(), SHADOW + 1)
        self.btn_min.move(self.btn_close.x() - self.btn_min.width() + 1, SHADOW + 1)
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < SHADOW + TITLE_H:
            self.windowHandle().startSystemMove()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        for offset in range(SHADOW, 0, -1):             # soft shadow
            alpha = int(70 * (1 - offset / SHADOW) ** 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(20, 40, 70, alpha))
            painter.drawRoundedRect(frame.adjusted(-offset, -offset + 3, offset, offset + 3),
                                    RADIUS + offset, RADIUS + offset)
        path = QPainterPath()
        path.addRoundedRect(frame, RADIUS, RADIUS)
        painter.fillPath(path, glass_gradient(frame, QColor(176, 219, 244, 250), QColor(246, 194, 222, 252)))
        painter.save()
        painter.setClipPath(path)
        for x0, width_part, alpha in ((0.18, 0.10, 46), (0.33, 0.04, 34), (0.62, 0.14, 28)):
            streak = QPainterPath()                     # the diagonal light of Vista glass
            left = frame.left() + frame.width() * x0
            streak_width = frame.width() * width_part
            streak.moveTo(left, frame.top())
            streak.lineTo(left + streak_width, frame.top())
            streak.lineTo(left + streak_width - frame.height() * 0.5, frame.bottom())
            streak.lineTo(left - frame.height() * 0.5, frame.bottom())
            painter.fillPath(streak, QColor(255, 255, 255, alpha))
        title_bar = QRectF(frame.left(), frame.top(), frame.width(), TITLE_H)
        gloss = QLinearGradient(title_bar.topLeft(), title_bar.bottomLeft())
        gloss.setColorAt(0.0, QColor(255, 255, 255, 170))
        gloss.setColorAt(0.5, QColor(255, 255, 255, 90))
        gloss.setColorAt(0.51, QColor(255, 255, 255, 10))
        painter.fillRect(title_bar, gloss)
        glow = QRadialGradient(QPointF(frame.left() + 90, frame.top() + TITLE_H / 2), 160)
        glow.setColorAt(0.0, QColor(255, 160, 210, 70))
        glow.setColorAt(1.0, QColor(255, 160, 210, 0))
        painter.fillRect(title_bar, glow)
        painter.restore()
        painter.setPen(QPen(QColor(84, 118, 152, 200), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.setPen(QPen(QColor(255, 255, 255, 170), 1))
        painter.drawRoundedRect(frame.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS - 1, RADIUS - 1)
        body = QRectF(self.body.geometry()).adjusted(-1, -1, 1, 1)
        painter.setPen(QPen(QColor(126, 160, 194, 190), 1))
        painter.setBrush(QColor(250, 252, 255, 246))
        painter.drawRoundedRect(body, 4, 4)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
        painter.drawLine(body.bottomLeft() + QPointF(4, 1), body.bottomRight() + QPointF(-4, 1))
        x = frame.left() + 10
        if self.icon is not None:
            painter.drawPixmap(QRectF(x, frame.top() + (TITLE_H - 16) / 2 + 1, 16, 16).toRect(), self.icon)
            x += 22
        painter.setFont(QFont("Segoe UI", 9))
        title_rect = QRectF(x, frame.top() + 1, self.btn_min.x() - x - 6, TITLE_H)
        painter.setPen(QColor(255, 255, 255, 210))
        for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1)):
            painter.drawText(title_rect.translated(dx, dy), Qt.AlignmentFlag.AlignVCenter,
                             self.caption or self.windowTitle())
        painter.setPen(QColor(42, 62, 92))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter, self.caption or self.windowTitle())


def rounded(painter, rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class Picture(QWidget):
    """A picture with rounded corners, a glass sheen and a caption bar along the bottom."""

    def __init__(self, size=QSize(640, 360)):
        super().__init__()
        self.setFixedSize(size)
        self.pix = None
        self.caption = ""
        self.caption_color = QColor(235, 242, 250)

    def set_still(self, path):
        self.pix = QPixmap(str(path))
        self.update()

    def set_caption(self, text, color=None):
        """The caption bar: `text` in bold over a dark strip at the bottom of the picture."""
        shape = (text, color or QColor(235, 242, 250))
        if shape != (self.caption, self.caption_color):
            self.caption, self.caption_color = shape
            self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = rounded(painter, rect, 5)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, QColor(5, 8, 12))
        if self.pix is not None and not self.pix.isNull():
            painter.drawPixmap(rect.toRect(), self.pix)
        sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + rect.height() * 0.45))
        sheen.setColorAt(0.0, QColor(255, 255, 255, 34))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.45), sheen)
        if self.caption:
            small = rect.height() < 300
            bar = QRectF(rect.left(), rect.bottom() - (28 if small else 40), rect.width(), 28 if small else 40)
            strip = QLinearGradient(bar.topLeft(), bar.bottomLeft())
            strip.setColorAt(0.0, QColor(18, 42, 68, 170))
            strip.setColorAt(0.5, QColor(14, 34, 58, 205))
            strip.setColorAt(1.0, QColor(8, 22, 40, 230))
            painter.fillRect(bar, strip)
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
            painter.drawLine(bar.topLeft(), bar.topRight())
            painter.setFont(QFont("Microsoft YaHei UI", 9 if small else 12, QFont.Weight.Bold))
            room = bar.adjusted(8, 0, -8, 0)
            text = painter.fontMetrics().elidedText(self.caption, Qt.TextElideMode.ElideRight, int(room.width()))
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(room.translated(0, 1), Qt.AlignmentFlag.AlignCenter, text)
            painter.setPen(self.caption_color)
            painter.drawText(room, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
        painter.setPen(QPen(QColor(84, 118, 152, 190), 1))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
