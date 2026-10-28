"""Win rates of both teams, for the Tab list: on the ship and over the account (random battles).

The replay's player list gives each player's account id and server. The numbers come from the public data
behind the official profile pages (vortex.worldofwarships.<server>), which needs no key:
  /api/accounts/<id>/                    statistics.pvp battles_count / wins, or hidden_profile = true
  /api/accounts/<id>/ships/<ship>/pvp/   statistics.<ship>.pvp battles_count / wins
Two requests per player, asked in the background once the player list is in, and asked again in every
battle (clear()). A request that failed is tried again after RETRY_S and nothing is shown meanwhile.
"""
import concurrent.futures
import json
import threading
import time
import urllib.request
from dataclasses import dataclass

RETRY_S = 60.0
TIMEOUT_S = 8.0
WORKERS = 4
FEW_BATTLES = 20          # fewer battles on the ship than this: the rate says little (shown grey)
HOSTS = {"ASIA": "asia", "EU": "eu", "NA": "com"}


def host_of(account, realm=""):
    """The profile server of an account: the replay's server name, else the account id's range (under
    0.5e9 the Russian server, which this data does not cover, then Europe, North America, Asia)."""
    if realm in HOSTS:
        return HOSTS[realm]
    if account >= 2_000_000_000:
        return "asia"
    if account >= 1_000_000_000:
        return "com"
    if account >= 500_000_000:
        return "eu"
    return None


@dataclass
class PlayerStat:
    hidden: bool = False
    battles: int = 0           # random battles of the account
    wins: int = 0
    ship_battles: int = 0      # ... on this ship
    ship_wins: int = 0

    @property
    def rate(self):
        return 100.0 * self.wins / self.battles if self.battles else None

    @property
    def ship_rate(self):
        return 100.0 * self.ship_wins / self.ship_battles if self.ship_battles else None


# the community's colour scale (the one the stats sites use), lower bound -> colour
RATE_COLORS = ((65.0, (225, 95, 255)), (60.0, (180, 125, 255)), (56.0, (60, 200, 120)), (52.0, (140, 220, 90)),
               (49.0, (250, 215, 80)), (47.0, (255, 150, 60)), (0.0, (255, 85, 80)))
FEW_COLOR = (188, 195, 203)   # light enough to read on the list's grey rows


def rate_color(rate, battles=None):
    """(r, g, b) for a win rate; grey when there are too few battles to say anything."""
    if rate is None or (battles is not None and battles < FEW_BATTLES):
        return FEW_COLOR
    return next(color for lower, color in RATE_COLORS if rate >= lower)


class PlayerStats:
    """Fetches and keeps the win rates. want() from the worker thread, get() from anywhere."""

    def __init__(self, fetch=None):
        self._fetch = fetch or self._http
        self._lock = threading.Lock()
        self._pool = concurrent.futures.ThreadPoolExecutor(WORKERS, thread_name_prefix="stats")
        self._busy = set()
        self._failed = {}          # key -> time of the failure
        self.data = {}             # "a<account>" -> [time, hidden, battles, wins]; "s<account>/<ship>" -> [time, battles, wins]

    def clear(self):
        """A new battle: everything is asked again."""
        with self._lock:
            self.data.clear()
            self._failed.clear()

    def want(self, players):
        """players: [(account, ship id, server name)]: fetch what is not known yet."""
        now = time.time()
        for account, ship, realm in players:
            host = host_of(account, realm) if account else None
            if host is None:
                continue
            for key, url in ((f"a{account}", f"https://vortex.worldofwarships.{host}/api/accounts/{account}/"),
                             (f"s{account}/{ship}",
                              f"https://vortex.worldofwarships.{host}/api/accounts/{account}/ships/{ship}/pvp/")):
                with self._lock:
                    if (self.data.get(key) or key in self._busy
                            or now - self._failed.get(key, -1e9) < RETRY_S):
                        continue
                    self._busy.add(key)
                self._pool.submit(self._one, key, url, account, ship)

    def get(self, account, ship):
        """PlayerStat, or None while nothing is known about the account yet."""
        with self._lock:
            account_row = self.data.get(f"a{account}")
            ship_row = self.data.get(f"s{account}/{ship}")
        if account_row is None:
            return None
        if account_row[1]:
            return PlayerStat(hidden=True)
        return PlayerStat(battles=account_row[2], wins=account_row[3],
                          ship_battles=ship_row[1] if ship_row else 0, ship_wins=ship_row[2] if ship_row else 0)

    @staticmethod
    def _http(url):
        request = urllib.request.Request(url, headers={"User-Agent": "wowsyukarinano",
                                                      "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.load(response)

    def _one(self, key, url, account, ship):
        try:
            payload = self._fetch(url)
            if payload.get("status") != "ok":
                raise ValueError(payload.get("error"))
            row = (payload.get("data") or {}).get(str(account)) or {}
            if key[0] == "a":
                pvp = (row.get("statistics") or {}).get("pvp") or {}
                value = [time.time(), bool(row.get("hidden_profile")),
                         int(pvp.get("battles_count") or 0), int(pvp.get("wins") or 0)]
            else:
                pvp = ((row.get("statistics") or {}).get(str(ship)) or {}).get("pvp") or {}
                value = [time.time(), int(pvp.get("battles_count") or 0), int(pvp.get("wins") or 0)]
            with self._lock:
                self.data[key] = value
                self._failed.pop(key, None)
        except Exception as error:      # noqa: BLE001 - offline or a server hiccup: retried later, never shown
            with self._lock:
                self._failed[key] = time.time()
            print(f"player stats: {url}: {error!r}", flush=True)
        finally:
            with self._lock:
                self._busy.discard(key)
