"""Ship names by GameParams id, for matching the rows of the team list."""
import json
import pathlib

from .paths import data_file


class ShipDB:
    def __init__(self, path=None):
        path = path or data_file("ships.json")
        self.ships = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        self._by_id = {ship["ship_id"]: ship for ship in self.ships if ship.get("ship_id")}

    def by_id(self, ship_id):
        """The ship ({"ship_id", "name"}) or None."""
        return self._by_id.get(ship_id)
