"""Transparent, click-through, always-on-top overlay that draws the win rates beside the Tab team list.

Four columns go on each outer side of the list: the ship's win rate and battles next to the list, the
account's outside it. They are drawn as more of the list, in its header bar's colour, its rows' colours and
the client's own letters, so they read as part of it.

The window stays in screenshots and streams (config overlay.capturable, default true). Since the program
captures the screen itself while Tab is held, the columns it drew last time are blanked out of that frame
(rate_rects) before the list is searched for; with overlay.capturable = false the window is excluded from
every capture instead (WDA_EXCLUDEFROMCAPTURE).

The game must run in borderless-window mode: exclusive fullscreen hides overlays.
"""
import ctypes
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PyQt6.QtWidgets import QWidget

WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11


class Overlay(QWidget):
    def __init__(self, screen_geometry):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(screen_geometry)
        self.stats_of = None                # lookup(entity) -> PlayerStat or None
        self.roster = None                  # the team list on screen (roster.Roster), or None
        self._roster_t = 0.0
        self.capturable = True              # keep the window in screenshots and streams
        self.rate_rects = ()                # what _draw_roster drew last, in the 1080p layout
        self._game_fonts = False            # the client's fonts are loaded (add_game_fonts)
        self._glows = {}                    # _glow_text: the shadow images made so far

    def _apply_capture_affinity(self):
        """Keep the window in screenshots (WDA_NONE) or exclude it from every capture."""
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(
                int(self.winId()), WDA_NONE if self.capturable else WDA_EXCLUDEFROMCAPTURE)
        except Exception:                   # noqa: BLE001 - a window without an affinity is a normal window
            pass

    def set_capturable(self, on):
        """True: screenshots and streams show the rates. False: the window is excluded from all capture."""
        self.capturable = bool(on)
        if self.isVisible():
            self._apply_capture_affinity()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_capture_affinity()
        if not hasattr(self, "_top_timer"):
            self._top_timer = QTimer(self)
            self._top_timer.timeout.connect(self._keep_on_top)
            self._top_timer.start(2000)

    def _keep_on_top(self):
        """The game can put its window above ours again (a new battle, a window mode change); check every
        2 seconds and take the top back."""
        try:
            from . import monitor
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            game = monitor.game_window()
            if not game:
                return
            above, current = False, user32.GetWindow(hwnd, 3)        # GW_HWNDPREV
            for _ in range(80):
                if not current:
                    break
                if current == game:
                    above = True
                    break
                current = user32.GetWindow(current, 3)
            if above or not self.isVisible():
                # TOPMOST, without moving, resizing or activating
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
                self.show()
                self._covered = getattr(self, "_covered", 0) + 1
                print(f"overlay: the game's window was above it, put back on top ({self._covered})", flush=True)
        except Exception as error:          # noqa: BLE001 - never stop the program for this
            print(f"overlay: keep-on-top check failed: {error!r}", flush=True)

    def set_player_stats(self, lookup):
        """lookup(entity) -> PlayerStat or None; None switches the columns off."""
        self.stats_of = lookup

    def add_game_fonts(self, paths):
        """Load the client's UI fonts (GAME_FONTS, bundled in assets/fonts) so the columns are written in
        the game's own letters; without them the system font is used."""
        from PyQt6.QtGui import QFontDatabase
        for path in paths:
            QFontDatabase.addApplicationFont(str(path))
        families = set(QFontDatabase.families())
        self._game_fonts = "Warhelios" in families and GAME_CJK in families
        self._warm_fonts()
        print(f"game fonts: {'in' if self._game_fonts else 'not found'}", flush=True)

    def _warm_fonts(self):
        """Draw every letter the columns use once: the client's CJK font rasterizes its first glyphs in
        ~300 ms, which would otherwise be the delay of the first Tab."""
        image = QImage(320, 40, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setPen(QColor(255, 255, 255))
        for font in (self._list_font(ROSTER_HEAD_PX, bold=True), self._list_font(ROSTER_ROW_PX)):
            painter.setFont(font)
            painter.drawText(QRectF(0, 0, 320, 40), Qt.AlignmentFlag.AlignCenter,
                             "本船胜率账号胜率场数战绩已隐藏—0123456789.%")
        painter.end()

    def _list_font(self, px, bold=False):
        """Warhelios for Latin letters and digits, the client's Source Han Sans for Chinese (its Bold for
        headings); `px` on screen."""
        font = QFont()
        font.setFamilies(["Warhelios", GAME_CJK_BOLD if bold else GAME_CJK] if self._game_fonts
                         else ["Microsoft YaHei"])
        font.setPixelSize(max(int(round(px)), 8))
        font.setBold(bold)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return font

    def set_roster(self, roster):
        """The team list as it is on screen now (roster.Roster), or None when it closed."""
        had = self.roster is not None
        self.roster, self._roster_t = roster, time.time()
        if roster is not None or had:
            self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # everything is in physical screen pixels, which is what the capture measures: with Windows
        # display scaling Qt paints in logical units, so undo that here
        ratio = self.devicePixelRatioF()
        if ratio and ratio != 1.0:
            painter.scale(1.0 / ratio, 1.0 / ratio)
        geometry = getattr(self, "geo", None)
        painter.save()
        if geometry is not None and not geometry.identity:
            painter.scale(geometry.scale, geometry.scale)
            painter.translate(-geometry.pad, 0)
        self.rate_rects = ()
        self._draw_roster(painter)
        painter.restore()
        painter.end()

    def _draw_roster(self, painter):
        """The columns of both teams, in the 1080p layout and sized by the list's scale."""
        roster = self.roster
        if roster is None or self.stats_of is None or time.time() - self._roster_t > ROSTER_KEEP_S:
            return
        from .playerstats import rate_color
        table, scale = roster.table, roster.table.scale

        def text(rect, value, color):
            self._glow_text(painter, rect, value, painter.font(), color, scale)

        head_font = self._list_font(ROSTER_HEAD_PX * scale, bold=True)
        row_font = self._list_font(ROSTER_ROW_PX * scale)
        head_metrics, row_metrics = QFontMetricsF(head_font), QFontMetricsF(row_font)
        pad = ROSTER_CELL_PAD_PX * scale
        rate_w = max(head_metrics.horizontalAdvance("本船胜率"), head_metrics.horizontalAdvance("账号胜率"),
                     row_metrics.horizontalAdvance("100.0%")) + 2 * pad
        count_w = max(head_metrics.horizontalAdvance("场数"), row_metrics.horizontalAdvance("88888")) + 2 * pad
        group_gap, gap = ROSTER_GROUP_GAP_PX * scale, 4 * scale
        group_w = rate_w + count_w
        side_w = 2 * group_w + group_gap
        text_color = count_color = QColor(250, 250, 250)
        colors = roster.colors or {}
        rects = []                          # what is drawn, so our own capture can leave it out
        for side, rows, edge, sign in (("ours", roster.ours, table.x0 - gap, -1),
                                       ("theirs", roster.theirs, table.rx1 + gap, 1)):
            if not rows:
                continue
            side_colors = colors.get(side) or {}
            left = edge - side_w if sign < 0 else edge
            rects.append((left, table.y0 - 2 * scale, left + side_w, table.row(len(rows) - 1)[1] + 2 * scale))
            ship_x = edge - group_w if sign < 0 else edge
            account_x = left if sign < 0 else edge + group_w + group_gap
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*side_colors.get("head", (90, 120, 120))))
            painter.drawRect(QRectF(left, table.y0, side_w, table.y1 - table.y0))
            painter.setFont(head_font)
            for x, width, heading in ((ship_x, rate_w, "本船胜率"), (ship_x + rate_w, count_w, "场数"),
                                      (account_x, rate_w, "账号胜率"), (account_x + rate_w, count_w, "场数")):
                text(QRectF(x, table.y0, width, table.y1 - table.y0), heading, text_color)
            row_colors = side_colors.get("rows") or []
            line_colors = side_colors.get("lines") or []
            if row_colors:                  # the strip between the header bar and the first row
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(*row_colors[0]))
                painter.drawRect(QRectF(left, table.y1, side_w, table.row(0)[0] - table.y1))
            for index, entity in enumerate(rows):
                top, bottom = table.row(index)
                height = bottom - top
                back = row_colors[index] if index < len(row_colors) else (80, 84, 88)
                line = line_colors[index] if index < len(line_colors) else tuple(min(v + 14, 255) for v in back)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(*line))                     # the line above the row, then the row
                painter.drawRect(QRectF(left, top - 1 * scale, side_w, 1 * scale))
                painter.setBrush(QColor(*back))
                painter.drawRect(QRectF(left, top, side_w, height))
                painter.setBrush(QColor(*(max(v - 22, 0) for v in back)))
                painter.drawRect(QRectF(left + group_w + group_gap / 2 - 0.5 * scale, top, 1 * scale, height))
                stat = self.stats_of(entity) if entity is not None else None
                if stat is None:
                    continue
                if stat.hidden:
                    painter.setFont(row_font)
                    text(QRectF(left, top, side_w, height), "战绩已隐藏", count_color)
                    continue
                for x, rate, battles, few in ((ship_x, stat.ship_rate, stat.ship_battles, stat.ship_battles),
                                              (account_x, stat.rate, stat.battles, None)):
                    painter.setFont(row_font)
                    text(QRectF(x, top, rate_w, height), f"{rate:.1f}%" if rate is not None else "—",
                         QColor(*_lift(rate_color(rate, few), ROSTER_LIFT)) if rate is not None else count_color)
                    text(QRectF(x + rate_w, top, count_w, height), str(battles or 0), count_color)
        self.rate_rects = tuple(rects)

    def _glow_text(self, painter, rect, value, font, color, scale=1.0):
        """Text with the soft dark glow the game's lists have, made once per text and size and kept."""
        center = Qt.AlignmentFlag.AlignCenter
        key = (value, font.key(), round(rect.width()), round(rect.height()))
        image = self._glows.get(key)
        pad = int(6 * scale) + 2
        if image is None:
            import cv2
            width, height = int(rect.width()) + 2 * pad, int(rect.height()) + 2 * pad
            lettering = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            lettering.fill(0)
            letter_painter = QPainter(lettering)
            letter_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            letter_painter.setFont(font)
            letter_painter.setPen(QColor(255, 255, 255))
            letter_painter.drawText(QRectF(pad, pad, rect.width(), rect.height()), center, value)
            letter_painter.end()
            alpha = np.frombuffer(lettering.constBits().asstring(lettering.sizeInBytes()), np.uint8).reshape(
                height, lettering.bytesPerLine() // 4, 4)[:, :width, 3]
            alpha = cv2.GaussianBlur(alpha.astype(np.float32) / 255.0, (0, 0), GLOW_SIGMA_PX * scale)
            alpha = np.clip(alpha * GLOW_GAIN, 0.0, 1.0) * GLOW_ALPHA
            shadow = np.zeros((height, width, 4), np.uint8)
            shadow[..., 3] = (alpha * 255).astype(np.uint8)         # black: premultiplied colour stays 0
            image = QImage(shadow.tobytes(), width, height, width * 4,
                           QImage.Format.Format_ARGB32_Premultiplied).copy()
            if len(self._glows) > 600:
                self._glows.clear()
            self._glows[key] = image
        painter.drawImage(QPointF(rect.left() - pad, rect.top() - pad + GLOW_DY_PX * scale), image)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect, center, value)


def _lift(rgb, amount):
    """A colour `amount` of the way towards white."""
    return tuple(int(channel + (255 - channel) * amount) for channel in rgb)


GAME_FONTS = ("Warhelios_Regular.ttf", "Warhelios_Bold.ttf", "Source_Han_Sans_CN_Medium_WH.ttf",
              "Source_Han_Sans_CN_Bold_WH.ttf")       # the client's gui/fonts, bundled in assets/fonts
GAME_CJK = "Source Han Sans CN Medium WH"
GAME_CJK_BOLD = "Source Han Sans CN Bold WH"
GLOW_SIGMA_PX = 1.3      # text glow: blur of the letters (px at 1080p) ...
GLOW_GAIN = 1.7          # ... strengthened ...
GLOW_ALPHA = 0.62        # ... to at most this black ...
GLOW_DY_PX = 0.6         # ... a little lower than the letters
ROSTER_LIFT = 0.3        # the rates' colours this much towards white, like the list's own coloured text
ROSTER_HEAD_PX = 19.0    # the list's header bar text at 1080p
ROSTER_ROW_PX = 15.0     # ... its row text (names, ship names)
ROSTER_CELL_PAD_PX = 9.0  # ... room on each side of a column's widest text
ROSTER_GROUP_GAP_PX = 10  # ... between the ship's pair and the account's
ROSTER_KEEP_S = 0.6      # ... the columns stay this long after the list was last seen
