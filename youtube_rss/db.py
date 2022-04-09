from __future__ import annotations

import json
import threading
from pathlib import Path


class DatabaseEncoder(json.JSONEncoder):
    def default(self, o):
        return o.db


class DatabaseDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, object_hook=self.object_hook)

    def object_hook(self, dct):
        if isinstance(dct, (dict, list)):
            return Database(dct)
        return dct


class Database:
    def __init__(self, db):
        self.db = db
        self.__lock = threading.Lock()

    def __repr__(self):
        return repr(self.db)

    def __getitem__(self, item):
        with self.__lock:
            return self.db[item]

    def __setitem__(self, item, value):
        with self.__lock:
            self.db[item] = value

    def __iter__(self):
        return iter(self.db)

    def update(self, *args, **kwargs):
        self.db.update(*args, **kwargs)

    def pop(self, *args, **kwargs):
        return self.db.pop(*args, **kwargs)

    @classmethod
    def from_json(cls, filepath: Path) -> Database:
        with filepath.open("r") as file_pointer:
            return json.load(file_pointer, cls=DatabaseDecoder)

    def to_json(self, filepath: Path) -> None:
        with filepath.open("w") as file_pointer:
            return json.dump(self, file_pointer, indent=4, cls=DatabaseEncoder)


def initialize_database():
    database = Database({})
    database["feeds"] = Database({})
    database["id to title"] = Database({})
    database["title to id"] = Database({})
    return database
