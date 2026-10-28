"""Follow the replay the game writes during a battle (read-only) and keep its player list.

The client records every battle into the replays folder as it goes: a small header (JSON arena info),
then a Blowfish-encrypted zlib stream of packets. Both decode incrementally, so a background thread tails
the growing file and feeds the packets to BattleData (replaydata.py): who is on which team, in which ship,
with which account and server. That is what the win rates beside the Tab list are looked up from.
"""
import json
import pathlib
import struct
import threading
import time
import zlib

from .modes import find_battle_file
from .replaydata import PKT_BASE_PLAYER, PKT_METHOD, BattleData

KEY = bytes([0x29, 0xB7, 0xC9, 0x09, 0x38, 0x3F, 0x84, 0x88, 0xFA, 0x98, 0xEC, 0x4E, 0x13, 0x19, 0x79, 0xFB])
REPLAY_MAGIC = 0x11343212   # first u32 of a finished replay file
PKT_KEEP = (PKT_BASE_PLAYER, PKT_METHOD)


class StreamDecoder:
    """Incremental decoder for one replay file: feed() the raw bytes as they appear.

    Behind the header the body is either "enc" (8 bytes of stream sizes, then a Blowfish-encrypted zlib
    stream, which is what a finished replay holds) or "raw" (plain packets, what the in-battle file may
    hold before the client compresses it). The mode is detected from the first body bytes.
    """

    def __init__(self):
        from Crypto.Cipher import Blowfish
        self.bf = Blowfish.new(KEY, Blowfish.MODE_ECB)
        self.raw = bytearray()          # undecoded file bytes
        self.header = None
        self.header_done = False
        self.mode = None                # None (undetected), "enc", "raw", "error: ..."
        self.prev = None                # previous decrypted block (CBC-like chaining)
        self.z = zlib.decompressobj()
        self.plain = bytearray()        # decoded bytes not yet parsed into packets
        self.n_packets = 0

    def feed(self, data):
        """The (type, time, payload) packets completed by this data."""
        self.raw += data
        if not self.header_done:
            if len(self.raw) < 8:
                return []
            if struct.unpack_from("<I", self.raw, 0)[0] != REPLAY_MAGIC:
                # no replay header: the in-battle temp file starts straight with packets
                self.header_done, self.header = True, {}
            elif not self._parse_header():
                return []
        if self.mode is None and not self._detect():
            return []
        if self.mode == "raw":
            self.plain += self.raw
            self.raw.clear()
        elif self.mode == "enc":
            usable = len(self.raw) - len(self.raw) % 8
            if usable:
                decrypted = bytearray()
                for offset in range(0, usable, 8):
                    block = self.bf.decrypt(bytes(self.raw[offset:offset + 8]))
                    if self.prev is not None:
                        block = (int.from_bytes(block, "little")
                                 ^ int.from_bytes(self.prev, "little")).to_bytes(8, "little")
                    self.prev = block
                    decrypted += block
                del self.raw[:usable]
                try:
                    self.plain += self.z.decompress(bytes(decrypted))
                except zlib.error as error:
                    self.mode = f"error: zlib {error}"
                    return []
        else:
            return []
        packets = self._packets()
        self.n_packets += len(packets)
        return packets

    def _parse_header(self):
        data = self.raw
        if len(data) < 8:
            return False
        _, nblocks = struct.unpack("<II", data[:8])
        if nblocks > 16:
            self.mode = "error: not a replay header"
            return False
        at, blocks = 8, []
        for _ in range(nblocks):
            if len(data) < at + 4:
                return False
            length = struct.unpack("<I", data[at:at + 4])[0]
            if len(data) < at + 4 + length:
                return False
            blocks.append(bytes(data[at + 4:at + 4 + length]))
            at += 4 + length
        try:
            self.header = json.loads(blocks[0]) if blocks else {}
        except ValueError:
            self.header = {}
        del self.raw[:at]
        self.header_done = True
        return True

    @staticmethod
    def _plausible_packets(data, at, need=4):
        """Do `need` sane packet headers follow each other from data[at]? None while unsure."""
        last_time = -1.0
        for _ in range(need):
            if at + 12 > len(data):
                return None
            size, typ, when = struct.unpack_from("<IIf", data, at)
            if size > 1_000_000 or typ > 512 or not (0.0 <= when < 7200.0) or when + 1e-3 < last_time:
                return False
            last_time = when
            at += 12 + size
        return True

    def _detect(self):
        data = self.raw
        if len(data) < 64:
            return False
        if self.header == {}:
            # headerless file: find where a run of sane packets starts
            for at in range(0, min(len(data) - 12, 65536)):
                ok = self._plausible_packets(data, at, need=8)
                if ok is None:
                    return False
                if ok:
                    self.mode = "raw"
                    del self.raw[:at]
                    return True
            if len(data) > 65536 + 4096:
                self.mode = "error: no packets found in a headerless file"
            return False
        # encrypted zlib stream after the 8 size bytes: its first decrypted bytes are a zlib header
        first = self.bf.decrypt(bytes(data[8:16]))
        if first[0] == 0x78 and (first[0] * 256 + first[1]) % 31 == 0:
            self.mode = "enc"
            del self.raw[:8]
            return True
        for at in (8, 0):
            ok = self._plausible_packets(data, at)
            if ok is None:
                return False
            if ok:
                self.mode = "raw"
                del self.raw[:at]
                return True
        if len(data) > 4096:
            self.mode = "error: unknown body format"
        return False

    def _packets(self):
        packets = []
        buffer = self.plain
        at = 0
        while at + 12 <= len(buffer):
            size, typ, when = struct.unpack_from("<IIf", buffer, at)
            if at + 12 + size > len(buffer):
                break
            if typ in PKT_KEEP:
                packets.append((typ, when, bytes(buffer[at + 12:at + 12 + size])))
            at += 12 + size
        del buffer[:at]
        return packets


class LiveReplay(threading.Thread):
    """Tails the replay being written in `folder` and keeps the player list up to date."""

    def __init__(self, folder, poll_s=0.05):
        super().__init__(daemon=True)
        self.folder = pathlib.Path(folder)
        self.poll_s = poll_s
        self.lock = threading.Lock()
        self.path = None
        self.pos = 0
        self.dec = None
        self.last_packet_wall = None
        self.battle = BattleData()
        self.gaps = [0.0, 0]          # [longest gap between data blocks (s), gaps over 2 s] in this battle
        self.prev_gaps = [0.0, 0]     # the same for the battle before
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _now(self):
        return time.time()

    def _current_file(self):
        """The replay being written, or None between battles."""
        return find_battle_file(self.folder)

    def _reset(self, path):
        self.path, self.pos = path, 0
        self.dec = StreamDecoder() if path else None
        self.battle = BattleData()
        self.last_packet_wall = None
        self.prev_gaps, self.gaps = self.gaps, [0.0, 0]

    def run(self):
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception:           # noqa: BLE001 - a partial or rotated file must never stop the thread
                self._reset(None)
            time.sleep(self.poll_s)

    def _poll(self):
        path = self._current_file()
        if path != self.path:
            self._reset(path)
        if path is None:
            return
        size = path.stat().st_size
        if size < self.pos:             # truncated or reused: start over
            self._reset(path)
        if size == self.pos:
            return
        with open(path, "rb") as handle:
            handle.seek(self.pos)
            data = handle.read(size - self.pos)
        self.pos += len(data)
        packets = self.dec.feed(data)
        if packets:
            self._ingest(packets)

    def _ingest(self, packets):
        now = self._now()
        with self.lock:
            for typ, when, body in packets:
                if typ == PKT_BASE_PLAYER or typ == PKT_METHOD:
                    self.battle.feed(typ, when, body)
            if self.last_packet_wall is not None:
                gap = now - self.last_packet_wall
                self.gaps[0] = max(self.gaps[0], gap)
                self.gaps[1] += gap > 2.0
            self.last_packet_wall = now

    @property
    def problem(self):
        """Why a replay that is there cannot be used (a game update changed the format), or None."""
        if self.dec is None or self.path is None:
            return None
        if self.dec.mode and self.dec.mode.startswith("error"):
            return f"unreadable format ({self.dec.mode})"
        if self.pos > 262144 and self.dec.n_packets == 0:
            return "no player packets found (packet format changed?)"
        return None
