"""Main window: the picture, its caption bar and one line of text under it.

The win rates themselves are drawn by the overlay (overlay.py) while Tab is held in the game.
"""
import time

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from . import brand, settings
from .paths import ASSETS
from .vista import SHADOW, GlassWindow, Picture

UI = ASSETS / "ui"
NOTICE_H = 34          # the notice line's height: two lines of text
NOTICE_S = 8.0         # how long a notice stays (a sticky one: until the battle changes)
PAD = 6                # the notice's dot and text: this far in from the edges


class Notice(QWidget):
    """One short line for the user (two at most) behind a dot whose colour says what kind it is."""

    COLORS = {"idle": QColor(120, 155, 190), "ok": QColor(70, 175, 120), "info": QColor(70, 145, 215),
              "warn": QColor(225, 150, 60)}

    def __init__(self, width, height):
        super().__init__()
        self.setFixedSize(max(width, 60), height)
        self.text, self.level = "", "idle"

    def set(self, text, level="info"):
        if (text, level) != (self.text, self.level):
            self.text, self.level = text, level
            self.setToolTip(text)
            self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.COLORS.get(self.level, self.COLORS["info"])
        middle = self.height() / 2
        glow = QColor(color)
        glow.setAlpha(60)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(PAD, middle - 6, 12, 12))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(PAD + 3, middle - 3, 6, 6))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        metrics = painter.fontMetrics()
        room = QRectF(PAD + 20, 0, self.width() - PAD * 2 - 20, self.height())
        # two lines at most, broken where it fits, the rest cut with "…" (the tooltip has it all)
        lines, current = [], ""
        head, comma, tail = self.text.partition("，")      # a natural break first: after the comma
        if metrics.horizontalAdvance(self.text) <= room.width():
            text = self.text
        elif comma and metrics.horizontalAdvance(head + comma) <= room.width() \
                and metrics.horizontalAdvance(tail) <= room.width():
            lines, text = [head + comma], tail
        else:
            text = self.text
        for character in text:
            if metrics.horizontalAdvance(current + character) > room.width() and current:
                lines.append(current)
                current = character.lstrip()
            else:
                current += character
        lines.append(current)
        if len(lines) > 2:
            lines = [lines[0], metrics.elidedText(lines[1] + lines[2], Qt.TextElideMode.ElideRight,
                                                  int(room.width()))]
        painter.setPen(QColor(52, 70, 92) if self.level != "idle" else QColor(110, 130, 152))
        painter.drawText(room, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "\n".join(lines))


class MainWindow(GlassWindow):
    def __init__(self, worker):
        super().__init__(brand.TASKBAR, QPixmap(str(ASSETS / "icon.png")), caption=brand.TITLE)
        self.worker = worker
        self._info = None
        self._asked_game_dir = False
        self._running = False
        self._battle = None
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._page())
        self._fit()

    def _page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(5, 5, 5, 3)       # the picture fills the panel, the notice sits under it
        layout.setSpacing(3)
        self.pic = Picture(QSize(250, 250))
        self.pic.set_still(UI / "idle.jpg")
        layout.addWidget(self.pic, 0, Qt.AlignmentFlag.AlignHCenter)
        self.notice = Notice(self.pic.width(), NOTICE_H)
        layout.addWidget(self.notice, 0, Qt.AlignmentFlag.AlignHCenter)
        self._said = None               # (text, level, until perf time or None = until the battle changes)
        self._said_timer = QTimer(self, singleShot=True, timeout=self._refresh)
        return page

    def _fit(self, *_):
        """The window takes the page's size (the picture and the line under it)."""
        for widget in [self.body] + self.body.findChildren(QWidget):
            widget.ensurePolished()     # the style's fonts must be in before the size is asked
        self.body.layout().activate()
        hint = self.body.sizeHint().expandedTo(self.body.minimumSizeHint())
        margins = self.layout().contentsMargins()
        position = self.pos()
        self.setFixedSize(hint.width() + margins.left() + margins.right(),
                          hint.height() + margins.top() + margins.bottom())
        if self.isVisible():
            self._keep_on_screen(position)

    def _keep_on_screen(self, top_left):
        """Keep the window on screen when its new size would put it past an edge."""
        screen = QApplication.screenAt(top_left + QPoint(self.width() // 2, 40)) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left() - SHADOW, min(top_left.x(), area.right() + 1 + SHADOW - self.width()))
        y = max(area.top() - SHADOW, min(top_left.y(), area.bottom() + 1 + SHADOW - self.height()))
        self.move(x, y)

    def start(self):
        """Called once the models are loaded."""
        self._running = True
        self._show_state(battle=False)
        self.show()
        QTimer.singleShot(0, self._fit)         # once shown, with the real font metrics
        self.raise_()
        self.activateWindow()

    def tell(self, text, level="info", sticky=False):
        """A line under the picture, for a few seconds or (sticky) until the battle changes."""
        self._said = (text, level, None if sticky else time.perf_counter() + NOTICE_S)
        if not sticky:
            self._said_timer.start(int(NOTICE_S * 1000))
        self._refresh()

    def _refresh(self):
        self._show_state((self._info or {}).get("battle"))

    def ask_game_dir(self):
        """The game was not found automatically: ask once for its folder."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from .gamedir import is_game_dir
        self._asked_game_dir = True
        QMessageBox.information(self, brand.TITLE, "没有自动找到《战舰世界》的安装目录。\n"
                                "请选择游戏目录（包含 WorldOfWarships.exe 的文件夹）。")
        while True:
            path = QFileDialog.getExistingDirectory(self, "选择游戏目录")
            if not path:
                return
            if is_game_dir(path):
                settings.save(game_dir=path)
                self.worker.set_game_dir(path)
                return
            QMessageBox.warning(self, brand.TITLE, "这个文件夹里没有 WorldOfWarships.exe，请重新选择。")

    def set_info(self, info):
        if not self._running:
            return
        self._info = info
        if not info.get("game_dir") and not self._asked_game_dir:
            QTimer.singleShot(0, self.ask_game_dir)
        battle = bool(info.get("battle"))
        if self._battle is not None and battle != self._battle:
            if self._said is not None and self._said[2] is None:
                self._said = None       # a lasting notice was about the battle that is over
        self._battle = battle
        self._show_state(battle)

    def _show_state(self, battle):
        """The caption bar says whether a battle is running; the line under it says what to do."""
        if battle:
            self.pic.set_caption("对局中", QColor(255, 198, 226))
        else:
            self.pic.set_caption("等待对局…")
        said = self._said
        if said is not None and said[2] is not None and time.perf_counter() > said[2]:
            said = self._said = None
        if said is not None:
            self.notice.set(said[0], said[1])
        elif battle:
            self.notice.set("按住 Tab 显示双方胜率", "ok")
        else:
            self.notice.set("客户端须设置为窗口化全屏幕", "idle")

    def closeEvent(self, event):
        QApplication.quit()
        event.accept()
