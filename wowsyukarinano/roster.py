"""The Tab team list: where it is on screen and which player each row is, so the overlay can put the win
rates beside it.

Where: the two header bars (ours teal, theirs salmon) side by side, found by their colours in a frame of the
1920x1080 layout (screen.py). Their width gives the list's scale (421 px per table at 1080p, the interface
scale setting included); the rows follow under them:

    header  y0 .. y1 (31 px)      rows  from y1 + 3, 29 px apart (28 px high and a 1 px line)
    ours    x0 .. x1 (421 px)     theirs  from x1 + 4, the same width

Who: a row is matched to a player by the shape of its name (a fingerprint kept for each player once read,
a fraction of a millisecond a row) and, for a row no fingerprint fits, by reading the name and the ship
once and comparing them with the replay's player list (RowFinder). The order changes as ships sink, so
every frame is matched again.
"""
import difflib
import re
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

REF_TABLE_W = 421.0        # px, one table at 1080p and 100% interface scale
HEAD_H = 31.0              # px, the header bar's height there
ROW_TOP = 3.0              # the first row starts this far under the header bar
ROW_PITCH = 29.0
ROW_H = 28.0
NAME_CELL = (22.0, 162.0)  # the player name: this far in from the table's outer edge
SHIP_CELL = (4.0, 150.0)   # the tier and ship name: this far in from the table's inner edge
MIN_MATCH = 0.45           # a row and a player go together from this score (0..1) ...
MIN_LEFT = 0.2             # ... and the rows left over with the players left over from this one
FP_SIZE = (96, 14)         # a name's fingerprint: its letters' mask at this size (w, h)
FP_MATCH = 0.72            # a row is the player whose fingerprint overlaps its own this much (IoU)
READ_AGAIN_S = 1.0         # rows nobody fits are read at most this often


@dataclass
class Table:
    x0: float               # our table, left edge
    x1: float               # ... right edge (exclusive)
    rx0: float              # theirs
    rx1: float
    y0: float               # header bar top
    y1: float               # ... bottom (exclusive)
    scale: float

    def row(self, index):
        """(top, bottom) of row `index` (0-based)."""
        top = self.y1 + (ROW_TOP + index * ROW_PITCH) * self.scale
        return top, top + ROW_H * self.scale


@dataclass
class Roster:
    table: Table
    ours: list = field(default_factory=list)      # entity (or None) per row of our table
    theirs: list = field(default_factory=list)
    colors: dict = None                           # colors(): the list's own, to draw in


def colors(bgr, table, n_ours, n_theirs):
    """The list's own colours (RGB) as it looks now: each header bar's, and each row's and the line above
    it at the table's outer edge (the rows are see-through, so they change with the sea behind them).

    {"ours"|"theirs": {"head": colour, "rows": [colour], "lines": [colour]}}"""
    def median(region):
        if not region.size:
            return (80, 84, 88)
        return tuple(int(value) for value in np.median(region.reshape(-1, 3), 0)[::-1])

    scale = table.scale
    result = {}
    for side, count, (head_x0, head_x1), (edge_x0, edge_x1) in (
            ("ours", n_ours, (table.x0, table.x1), (table.x0 + 2 * scale, table.x0 + 12 * scale)),
            ("theirs", n_theirs, (table.rx0, table.rx1), (table.rx1 - 12 * scale, table.rx1 - 2 * scale))):
        rows, lines = [], []
        for index in range(count):
            top, bottom = table.row(index)
            rows.append(median(bgr[int(top + 6 * scale):int(bottom - 6 * scale), int(edge_x0):int(edge_x1)]))
            lines.append(median(bgr[int(top) - 1:int(top), int(edge_x0):int(edge_x0 + 30 * scale)]))
        result[side] = {"head": median(bgr[int(table.y0):int(table.y1), int(head_x0):int(head_x1)]),
                        "rows": rows, "lines": lines}
    return result


def _span(counts, minimum):
    """(first, last + 1) of the entries at or above `minimum`, or None."""
    found = np.nonzero(counts >= minimum)[0]
    return (int(found[0]), int(found[-1]) + 1) if len(found) else None


def find_table(bgr):
    """The team list's Table in a 1080p-layout frame (BGR), or None when it is not shown."""
    band = bgr[100:700, 200:1720].astype(np.int16)
    blue, green, red = band[..., 0], band[..., 1], band[..., 2]
    teal = (green - red > 35) & (blue - red > 25) & (green > 100)
    salmon = (red - green > 30) & (red - blue > 40) & (red > 120)
    per_row = teal.sum(1)
    if per_row.max() < 200:
        return None
    header_rows = _span(per_row, 0.6 * per_row.max())
    if header_rows is None or not (15 <= header_rows[1] - header_rows[0] <= 80):
        return None
    top = header_rows[0]
    columns = _span(teal[top:header_rows[1]].sum(0), 0.5 * (header_rows[1] - top))
    if columns is None:
        return None
    width = columns[1] - columns[0]
    scale = width / REF_TABLE_W
    # The header bar is HEAD_H*scale tall. A row highlighted under the mouse carries the header's colour and
    # can make the run longer, which would push every row below it down; keep the bar's known height and
    # read the colours over that height alone.
    bottom = min(header_rows[1], top + max(int(round(HEAD_H * scale)), 1))
    if bottom < header_rows[1]:
        columns = _span(teal[top:bottom].sum(0), 0.5 * (bottom - top)) or columns
        width = columns[1] - columns[0]
        scale = width / REF_TABLE_W
        bottom = min(header_rows[1], top + max(int(round(HEAD_H * scale)), 1))
    enemy = _span(salmon[top:bottom].sum(0), 0.5 * (bottom - top))
    # theirs must be just right of ours and as wide
    if (enemy is None or abs((enemy[1] - enemy[0]) - width) > 0.06 * width
            or not (0 <= enemy[0] - columns[1] <= 12 * scale)
            or abs((header_rows[1] - top) - HEAD_H * scale) > 6 * scale):
        return None
    return Table(x0=columns[0] + 200, x1=columns[1] + 200, rx0=enemy[0] + 200, rx1=enemy[1] + 200,
                 y0=top + 100, y1=bottom + 100, scale=scale)


def cells(bgr, table, n_ours, n_theirs):
    """The (player name, ship name) cells of each row as BGR crops: ([ours], [theirs])."""
    scale = table.scale
    out = ([], [])
    for side, count in ((0, n_ours), (1, n_theirs)):
        for index in range(count):
            top, bottom = table.row(index)
            if side == 0:       # ours: the name at the left (outer) end, the ship at the right (inner) one
                spans = ((table.x0 + NAME_CELL[0] * scale, table.x0 + NAME_CELL[1] * scale),
                         (table.x1 - SHIP_CELL[1] * scale, table.x1 - SHIP_CELL[0] * scale))
            else:               # theirs: mirrored
                spans = ((table.rx1 - NAME_CELL[1] * scale, table.rx1 - NAME_CELL[0] * scale),
                         (table.rx0 + SHIP_CELL[0] * scale, table.rx0 + SHIP_CELL[1] * scale))
            crops = [bgr[int(top):int(bottom), int(x0):int(x1)] for x0, x1 in spans]
            out[side].append(tuple(crop if crop.size else None for crop in crops))
    return out


def _stretched(crop):
    """A cell with its letters at full contrast: a sunk ship's row is written dark grey on dark grey."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    low, high = float(np.median(gray)), float(np.percentile(gray, 99.5))
    if high - low >= 90 or high - low < 8:
        return crop
    gray = np.clip((gray - low) / (high - low) * 230.0 + 15.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def read_name(ocr, crop):
    """OCR of one name cell (recognition only), '' when unreadable."""
    if crop is None or not crop.size:
        return ""
    image = cv2.resize(_stretched(crop), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    result, _ = ocr(image, use_det=False, use_cls=False)
    return " ".join(text.strip() for text, confidence in (result or [])
                    if text.strip() and float(confidence) > 0.3)


def _norm(name):
    """A name as the list shows it, comparable: no clan tag, no bot colons, no "...", lower case."""
    name = re.sub(r"\[[^\]]*\]?", "", name)
    name = name.replace("…", "").replace("...", "").strip(" .:")
    return re.sub(r"[^0-9a-z_\-]", "", name.lower())


def _ship_norm(text):
    """A ship cell as read ("VII 长门", "长门 VIl ~") or a ship name, comparable: no tier numeral, no marks."""
    words = [word for word in re.split(r"\s+", text)
             if word and not re.fullmatch(r"[IVXl1|√~.·]+", word)]
    return re.sub(r"[\s\W]", "", "".join(words).lower())


def _score(read, name):
    if not read or not name:
        return 0.0
    if len(read) >= 5 and (name.startswith(read) or read in name):   # a long name is cut with "..." in the list
        return 0.95
    return difflib.SequenceMatcher(None, read, name).ratio()


def score(read, player):
    """How well a row read as (name, ship) fits a player (entity, name, clan, ship name): 0..1."""
    name_read, ship_read = read
    _, name, clan, ship = player
    by_name = max(_score(_norm(name_read), _norm(name)),
                  _score(re.sub(r"[^0-9a-z_\-]", "", name_read.lower()),
                         re.sub(r"[^0-9a-z_\-]", "", (clan + name).lower())))
    ship_read, ship_name = _ship_norm(ship_read), _ship_norm(ship or "")
    if not ship_read or not ship_name:
        return by_name
    return 0.65 * by_name + 0.35 * difflib.SequenceMatcher(None, ship_read, ship_name).ratio()


def match(reads, players):
    """reads: (name, ship) read per row; players: [(entity, name, clan, ship name)] of that team.

    Returns the entity (or None) per row, each player at most once, best matches first."""
    pairs = sorted(((score(read, player), index, player[0])
                    for index, read in enumerate(reads) for player in players), reverse=True)
    rows, used = [None] * len(reads), set()
    for least in (MIN_MATCH, MIN_LEFT):     # the clear ones first, then what is left with what is left
        for value, index, entity in pairs:
            if value < least:
                break
            if rows[index] is None and entity not in used:
                rows[index] = entity
                used.add(entity)
    # one row left and one player left: that is them (a name the OCR could not read at all)
    free = [player[0] for player in players if player[0] not in used]
    empty = [index for index, entity in enumerate(rows) if entity is None]
    if len(free) == 1 and len(empty) == 1:
        rows[empty[0]] = free[0]
    return rows


def fingerprint(crop):
    """The shape of a name cell's letters at FP_SIZE as a bool mask, None for an empty cell.

    What is brighter than the row by about half of how bright its letters are: white on a living ship's
    row, dark grey on a sunk one's, the same shape either way."""
    if crop is None or not crop.size:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    background = float(np.median(gray))
    contrast = float(np.percentile(gray, 99.5)) - background
    if contrast < 12:
        return None
    mask = (gray > background + 0.45 * contrast).astype(np.float32)
    if mask.sum() < 8:
        return None
    _, letters = np.nonzero(mask)
    mask = mask[:, max(letters.min() - 1, 0):letters.max() + 2]      # the letters themselves
    return cv2.resize(mask, FP_SIZE, interpolation=cv2.INTER_AREA) > 0.3


def _iou(first, second):
    if first is None or second is None:
        return 0.0
    union = np.logical_or(first, second).sum()
    return float(np.logical_and(first, second).sum() / union) if union else 0.0


class RowFinder:
    """Who each row of the team list is, kept up as the order changes."""

    def __init__(self, ocr):
        self.ocr = ocr
        self.prints = {}           # entity -> fingerprint of its name as the list shows it
        self._read_at = {}         # side -> when its unknown rows were last read
        self._last = {}            # side -> who each row was the last time

    def rows(self, frame, table, ours, theirs, may_read=True):
        """([entity or None per our row], [... their row], [log lines of what was read])."""
        crops = cells(frame, table, len(ours), len(theirs))
        out, log = [], []
        for side, team, side_crops in (("ours", ours, crops[0]), ("theirs", theirs, crops[1])):
            prints = [fingerprint(crop[0]) for crop in side_crops]
            rows = self._by_print(prints, [player[0] for player in team])
            unknown = [index for index, entity in enumerate(rows) if entity is None]
            now = time.perf_counter()
            if unknown and may_read and self.ocr is not None \
                    and now - self._read_at.get(side, -1e9) >= READ_AGAIN_S:
                self._read_at[side] = now
                free = [player for player in team if player[0] not in rows]
                reads = [(read_name(self.ocr, side_crops[index][0]), read_name(self.ocr, side_crops[index][1]))
                         for index in unknown]
                names = {player[0]: player[1] for player in team}
                for index, read, entity in zip(unknown, reads, match(reads, free)):
                    rows[index] = entity
                    if entity is not None and prints[index] is not None:
                        self.prints[entity] = prints[index]
                    log.append(f"  {side} {index:2d}: {read[0]!r} / {read[1]!r} -> {names.get(entity)}")
            # a row still unknown keeps who it was last time (when that player is not in another row now):
            # a frame where a name could not be made out must not blank it
            last = self._last.get(side) or []
            for index, entity in enumerate(rows):
                if entity is None and index < len(last) and last[index] is not None and last[index] not in rows:
                    rows[index] = last[index]
            self._last[side] = list(rows)
            out.append(rows)
        return out[0], out[1], log

    def _by_print(self, prints, entities):
        """Rows to players by fingerprint: the best overlaps first, each player once."""
        known = [entity for entity in entities if entity in self.prints]
        pairs = sorted(((_iou(mask, self.prints[entity]), index, entity)
                        for index, mask in enumerate(prints) for entity in known), reverse=True)
        rows, used = [None] * len(prints), set()
        for value, index, entity in pairs:
            if value < FP_MATCH:
                break
            if rows[index] is None and entity not in used:
                rows[index] = entity
                used.add(entity)
        return rows
