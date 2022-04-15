from __future__ import annotations

import dataclasses
import json
import logging
import sys
import threading
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Type, TypeVar, Union

logger = logging.getLogger(__name__)

ChannelID: str
VideoID: str


class Url(str):
    def __new__(cls, *args) -> Url:
        if len(args) == 0:
            return str.__new__(cls)
        elif len(args) > 1:
            raise ValueError
        else:
            value = args[0]

            if not isinstance(value, str):
                raise TypeError(f"Unexpected type for Url '{value}'")

            # noinspection HttpUrlsUsage
            if not (value.startswith("http://") or value.startswith("https://")):
                raise ValueError(f"Value does not look like a Url '{value}'")

            return str.__new__(cls, value)


class _TableMetaclass(type):
    def __new__(metacls, name, bases, dct):
        class_obj = super().__new__(metacls, name, bases, dct)
        class_obj.__tablename__ = name
        return class_obj


class TableMetaclass(_TableMetaclass, ABCMeta):
    pass


class ITable(ABC, metaclass=TableMetaclass):
    __tablename__: str

    def update(self, other: ITable) -> None:
        for key in self.__dict__:
            self.__dict__[key] = other.__dict__[key]


@dataclass
class FeedEntry(ITable):
    video_id: VideoID
    link: Url
    title: str
    thumbnail: Url
    seen: bool


@dataclass
class Feed(ITable):
    channel_id: ChannelID
    title: str
    entries: List[FeedEntry]


@dataclass
class TitleCache(ITable):
    video_id: VideoID
    title: str


T = TypeVar("T", bound=ITable)


class IDatabase(ABC):
    @abstractmethod
    def add(self, row: ITable) -> None:
        pass

    @abstractmethod
    def connect(self) -> IDatabase:
        pass

    @abstractmethod
    def fetch(self, table_class: Type[T], **filter_by) -> List[T]:
        pass

    @abstractmethod
    def fetch_first(self, table_class: Type[T], **filter_by) -> Optional[T]:
        pass

    @abstractmethod
    def fetch_one_or_none(self, table_class: Type[T], **filter_by) -> Optional[T]:
        pass

    @abstractmethod
    def fetch_all(self, table_class: Type[T]) -> List[T]:
        pass

    @abstractmethod
    def remove(self, table_class: Type[T], **filter_by) -> None:
        pass

    @abstractmethod
    def save(self) -> None:
        pass


class DatabaseEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, JsonDatabase):
            return o._data
        elif dataclasses.is_dataclass(o):
            result = self._to_dict(o)
            return result

        return super().default(o)

    @staticmethod
    def _to_dict(obj):
        if dataclasses._is_dataclass_instance(obj):
            result = []
            for f in dataclasses.fields(obj):
                value = DatabaseEncoder._to_dict(getattr(obj, f.name))
                result.append((f.name, value))

            data = dict(result)
            data["__dataclass__"] = obj.__class__.__name__
            return data
        else:
            return obj


class DatabaseDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, object_hook=self.object_hook)

    def object_hook(self, data):
        if isinstance(data, dict):
            if "__dataclass__" in data:
                try:
                    class_ = getattr(sys.modules[__name__], data.pop("__dataclass__"))
                except KeyError:
                    pass
                else:
                    obj = class_(**data)
                    return obj

        return data


class DatabaseError(Exception):
    pass


class JsonDatabase(IDatabase):
    def __init__(self, data: Union[dict] = None, filepath: Path = None) -> None:
        self._data = data or {}
        self._filepath = filepath
        self.__lock = threading.Lock()

    def add(self, row: ITable) -> None:
        with self.__lock:
            self._data.setdefault(row.__tablename__, []).append(row)
            self.save()

    def connect(self) -> JsonDatabase:
        with self.__lock:
            self._load()
        return self

    def fetch(self, table_class: Type[T], **filter_by) -> List[T]:
        with self.__lock:
            all_results = self._data.get(table_class.__tablename__, [])
            results = [
                x
                for x in all_results
                if all(getattr(x, k) == v for k, v in filter_by.items())
            ]
            return results

    def fetch_first(self, table_class: Type[T], **filter_by) -> Optional[T]:
        with self.__lock:
            all_results = self._data.get(table_class.__tablename__, [])
            results = (
                x
                for x in all_results
                if all(getattr(x, k) == v for k, v in filter_by.items())
            )
            try:
                result = next(results)
            except StopIteration:
                return None
            else:
                return result

    def fetch_one_or_none(self, table_class: Type[T], **filter_by) -> Optional[T]:
        with self.__lock:
            all_results = self._data.get(table_class.__tablename__, [])
            results = (
                x
                for x in all_results
                if all(getattr(x, k) == v for k, v in filter_by.items())
            )
            try:
                result = next(results)
            except StopIteration:
                return None
            else:
                try:
                    next(results)
                except StopIteration:
                    return result
                else:
                    raise DatabaseError("Multiple entries found")

    def fetch_all(self, table_class: Type[T]) -> List[T]:
        with self.__lock:
            return self._data.get(table_class.__tablename__, [])

    def new(self) -> None:
        with self.__lock:
            self._data = {}
            self.save()

    def remove(self, table_class: Type[T], **filter_by) -> None:
        with self.__lock:
            self._data[table_class.__tablename__] = [
                x
                for x in self._data.get(table_class.__tablename__, [])
                if any(getattr(x, k) != v for k, v in filter_by.items())
            ]

    def _load(self) -> None:
        with self._filepath.open("r") as file_pointer:
            try:
                data = json.load(file_pointer, cls=DatabaseDecoder)
            except json.JSONDecodeError as err:
                logger.error(err)
                data = {}
            self._data = data

    def save(self) -> None:
        with self._filepath.open("w") as file_pointer:
            json.dump(self, file_pointer, indent=4, cls=DatabaseEncoder)
            file_pointer.flush()
