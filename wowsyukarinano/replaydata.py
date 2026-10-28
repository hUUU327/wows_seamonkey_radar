"""The player list out of the replay packet stream.

The in-battle file has no JSON header, so everything comes from the packets:
  type 0  BasePlayerCreate   u32 entity id of our Avatar
  type 8  EntityMethod       u32 entity, u32 method, u32 length, arguments
The method that carries the arena state (u64 arena id, u8, then length-prefixed pickles with the player
rows) has no fixed number: it is a position in the client's method table and moves when the game adds
methods, so every Avatar method is tried with the parser and the first whose payloads parse exactly wins.
"""
import io
import pickle
import struct
from dataclasses import dataclass, field

PKT_BASE_PLAYER = 0
PKT_METHOD = 8

# Player rows are lists of (field index, value) in the client's alphabetical field order, so a property
# added or dropped by a game update moves the fields behind it. The layouts are listed newest first and a
# row is read with the first one whose values make sense; an unseen layout is found by shifting the late
# fields (entity, params, team) by a few places.
PLAYER_LAYOUTS = [
    {"account": 0, "avatar": 2, "clan": 6, "name": 25, "entity": 34, "params": 35, "team": 37},
    {"account": 0, "avatar": 2, "clan": 6, "name": 25, "entity": 33, "params": 34, "team": 36},
]
BOT_LAYOUTS = [
    {"clan": 5, "name": 19, "entity": 24, "params": 25, "team": 27},
    {"clan": 5, "name": 19, "entity": 23, "params": 24, "team": 26},
]
REALMS = ("ASIA", "EU", "NA", "RU", "CN")   # the server names a player row holds
BOT_NFIELDS = 27                            # a row of about this many fields is a bot, a longer one a player
SHIFTED = ("entity", "params", "team")
MAX_SHIFT = 3


@dataclass
class Player:
    entity: int           # Vehicle entity id
    name: str
    clan: str
    team: int
    params: int           # ship GameParams id, the ships.json ship_id
    avatar: int = 0
    account: int = 0      # accountDBID (0 for bots)
    realm: str = ""       # "ASIA", "EU", "NA", ... ("" if not found)


class _Any:
    """Stand-in for the client's classes: only the plain data inside the pickles is used."""

    def __init__(self, *args, **kwargs):
        pass

    def __setstate__(self, state):
        pass


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        return type(name, (_Any,), {})


def _blob(data, at):
    length = data[at]
    at += 1
    if length == 0xFF:
        length = data[at] | data[at + 1] << 8 | data[at + 2] << 16
        at += 3
    if at + length > len(data):
        raise ValueError("blob past end")
    return data[at:at + length], at + length


def _plausible(row, fields):
    """Do the fields of this layout hold what they should?"""
    name, entity = row.get(fields["name"]), row.get(fields["entity"])
    params, team = row.get(fields["params"]), row.get(fields["team"])
    return (isinstance(name, str) and type(entity) is int and 0 < entity < 2 ** 31
            and type(params) is int and params >= 1_000_000_000 and type(team) is int and 0 <= team < 8)


def _player(row, layouts, bot):
    values = dict(row)
    fields = next((layout for layout in layouts if _plausible(values, layout)), None)
    if fields is None:                  # not a layout we know: the late fields moved by a few places
        base = layouts[0]
        for shift in sorted(range(-MAX_SHIFT, MAX_SHIFT + 1), key=abs):
            moved = dict(base, **{name: base[name] + shift for name in SHIFTED})
            if shift and _plausible(values, moved):
                fields = moved
                break
    if fields is None:
        raise ValueError("unexpected player fields")
    return Player(entity=values[fields["entity"]], name=values[fields["name"]],
                  clan=values.get(fields["clan"]) or "", team=values[fields["team"]],
                  params=values[fields["params"]],
                  avatar=int(values.get(fields.get("avatar", -1), 0) or 0),
                  account=_int(values.get(fields.get("account", -1))) if not bot else 0,
                  realm=next((value for value in values.values() if isinstance(value, str) and value in REALMS), ""))


def _int(value):
    return value if type(value) is int and value > 0 else 0


def parse_arena(payload):
    """Arena state payload -> [Player] (humans and bots)."""
    if len(payload) < 20 or b"\x80\x02" not in payload[8:16]:
        raise ValueError("no pickle")
    at, players = 9, []
    while at < len(payload):
        blob, at = _blob(payload, at)
        if not blob.startswith(b"\x80\x02"):
            continue
        rows = _Unpickler(io.BytesIO(blob), encoding="latin1").load()
        if not (isinstance(rows, list) and rows and isinstance(rows[0], list)):
            continue
        for row in rows:
            count = len(row)
            if count > BOT_NFIELDS + 3:
                players.append(_player(row, PLAYER_LAYOUTS, False))
            elif abs(count - BOT_NFIELDS) <= 3:
                players.append(_player(row, BOT_LAYOUTS, True))
            # other rows are the payload's event objects (towers, portals), not ships
    if not players:
        raise ValueError("no players")
    return players


PARSERS = {"arena": parse_arena}
CONFIRM = {"arena": 1}      # exact parses needed before a method is trusted


@dataclass
class BattleData:
    """Fed with every packet of one battle; keeps the player list."""
    avatar: int = None
    players: dict = field(default_factory=dict)      # Vehicle entity -> Player
    own_entity: int = None
    methods: dict = field(default_factory=dict)      # kind -> method id, once confirmed
    _cand: dict = field(default_factory=dict)        # (kind, method) -> exact parses, or -1 once it failed

    def feed(self, typ, t, body):
        if typ == PKT_BASE_PLAYER and len(body) >= 4:
            self.avatar = struct.unpack_from("<I", body, 0)[0]
            return
        if typ != PKT_METHOD or self.avatar is None or len(body) < 12:
            return
        entity, method, length = struct.unpack_from("<III", body, 0)
        if entity != self.avatar:
            return
        payload = body[12:12 + length]
        for kind, parse in PARSERS.items():
            known = self.methods.get(kind)
            if known is not None and known != method:
                continue
            if self._cand.get((kind, method)) == -1:
                continue
            try:
                result = parse(payload)
            except (ValueError, struct.error, IndexError, pickle.UnpicklingError, EOFError, TypeError,
                    AttributeError, KeyError):
                if known is None:
                    self._cand[(kind, method)] = -1
                continue
            if known is None:
                seen = self._cand.get((kind, method), 0) + 1
                self._cand[(kind, method)] = seen
                if seen >= CONFIRM[kind]:
                    self.methods[kind] = method
            self._use(kind, result)
            return

    def _use(self, kind, result):
        if kind == "arena":
            self.players = {player.entity: player for player in result}
            me = next((player for player in result if player.avatar == self.avatar), None)
            self.own_entity = me.entity if me else None

    @property
    def own_team(self):
        me = self.players.get(self.own_entity)
        return me.team if me else None
