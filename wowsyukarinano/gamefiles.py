"""Read files out of the game client's resource packages (read-only).

Resources live in res_packages/*.pkg, indexed by bin/<build>/idx/*.idx:
  idx      "ISFP", u32 version, u32 id, u32 header size; at 0x10 n_nodes, n_files, n_packages and the
           offsets of the three tables (relative to 0x10)
  node     u64 name length, u64 name offset, u64 id, u64 parent id
  file     u64 node id, u64 package id, u64 offset, u32 compression, u32 flags, u32 stored size,
           u32 crc, u64 size
  package  u64 name length, u64 name offset, u64 id
Stored data is raw deflate (compression 5) or plain. GameParams.data is a byte-reversed zlib stream of a
pickle of all game parameters, loaded with stand-in classes.
"""
import io
import pathlib
import pickle
import struct
import zlib


class IdxFile:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        data = self.path.read_bytes()
        if data[:4] != b"ISFP":
            raise ValueError(f"{self.path.name}: not a resource index")
        n_nodes, n_files, n_packages = struct.unpack_from("<IIQ", data, 16)
        off_nodes, off_files, off_packages = (offset + 16 for offset in struct.unpack_from("<QQQ", data, 32))
        self.nodes = {}                 # id -> (name, parent id)
        for i in range(n_nodes):
            o = off_nodes + i * 32
            length, name_at, node_id, parent = struct.unpack_from("<QQQQ", data, o)
            name = data[o + name_at:o + name_at + length].split(b"\0", 1)[0].decode("utf-8", "replace")
            self.nodes[node_id] = (name, parent)
        self.files = {}                 # node id -> (package id, offset, compression, stored size, size)
        for i in range(n_files):
            o = off_files + i * 48
            node_id, package, offset, compression, _flags, stored, _crc, size = struct.unpack_from("<QQQIIIIQ", data, o)
            self.files[node_id] = (package, offset, compression, stored, size)
        self.packages = {}              # package id -> file name
        for i in range(n_packages):
            o = off_packages + i * 24
            length, name_at, package_id = struct.unpack_from("<QQQ", data, o)
            self.packages[package_id] = data[o + name_at:o + name_at + length].split(b"\0", 1)[0].decode()

    def path_of(self, node_id):
        parts = []
        while node_id in self.nodes:
            name, node_id = self.nodes[node_id]
            parts.append(name)
        return "/".join(reversed(parts))

    def find(self, suffix):
        """Node ids of the files whose path ends with suffix."""
        return [node_id for node_id in self.files if self.path_of(node_id).endswith(suffix)]

    def read(self, node_id, packages_dir):
        package, offset, compression, stored, size = self.files[node_id]
        with open(pathlib.Path(packages_dir) / self.packages[package], "rb") as handle:
            handle.seek(offset)
            data = handle.read(stored)
        if compression == 0 or stored == size:
            return data
        return zlib.decompress(data, -15)


def latest_build(game_dir):
    builds = [path for path in (pathlib.Path(game_dir) / "bin").iterdir()
              if path.is_dir() and path.name.isdigit()]
    if not builds:
        raise FileNotFoundError("no client build folder under bin/")
    return max(builds, key=lambda path: int(path.name))


def read_game_file(game_dir, suffix):
    """Bytes of the first resource whose path ends with suffix."""
    game_dir = pathlib.Path(game_dir)
    for idx_path in sorted((latest_build(game_dir) / "idx").glob("*.idx")):
        if idx_path.name.startswith("spaces_"):
            continue                    # maps: large, and never what is looked for
        index = IdxFile(idx_path)
        hits = index.find(suffix)
        if hits:
            return index.read(hits[0], game_dir / "res_packages")
    raise FileNotFoundError(suffix)


class _Obj:
    """Stand-in for the client's classes: keeps the pickled state as attributes."""

    def __init__(self, *args, **kwargs):
        pass

    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) == 2:      # (dict, slots)
            state = {**(state[0] or {}), **(state[1] or {})}
        if isinstance(state, dict):
            self.__dict__.update(state)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module in ("copy_reg", "copyreg") and name == "_reconstructor":
            return lambda cls, base, state: cls()
        if module in ("__builtin__", "builtins") and name in ("object", "set", "frozenset", "list", "dict", "tuple"):
            return {"object": object, "set": set, "frozenset": frozenset, "list": list,
                    "dict": dict, "tuple": tuple}[name]
        return type(name, (_Obj,), {})


def load_game_params(game_dir):
    """All game parameters: name -> object (ships, modules, consumables, ...)."""
    raw = read_game_file(game_dir, "GameParams.data")
    data = zlib.decompress(raw[::-1])
    obj = _Unpickler(io.BytesIO(data), encoding="latin1").load()
    if isinstance(obj, (list, tuple)):
        obj = obj[0]
    if isinstance(obj, dict) and "" in obj and len(obj) == 1:
        obj = obj[""]
    return obj


def read_mo(path):
    """A gettext .mo catalog -> {msgid: msgstr} (the client's language files)."""
    data = pathlib.Path(path).read_bytes()
    end = "<" if struct.unpack_from("<I", data, 0)[0] == 0x950412DE else ">"
    _, count, off_orig, off_trans = struct.unpack_from(end + "IIII", data, 4)
    texts = {}
    for i in range(count):
        len_o, at_o = struct.unpack_from(end + "II", data, off_orig + 8 * i)
        len_t, at_t = struct.unpack_from(end + "II", data, off_trans + 8 * i)
        texts[data[at_o:at_o + len_o].decode("utf-8", "replace")] = data[at_t:at_t + len_t].decode("utf-8", "replace")
    return texts


def client_texts(game_dir, lang):
    """The client's text catalog for a language (zh_sg, en)."""
    return read_mo(latest_build(game_dir) / "res" / "texts" / lang / "LC_MESSAGES" / "global.mo")
