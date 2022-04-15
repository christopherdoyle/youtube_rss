from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, TypeVar

_T = TypeVar("_T")


class UnknownQueryStyle(Exception):
    """Indicates that the provided query style is not supported."""


class QueryStyle(Enum):
    INDEX_QUERY_STYLE = 0
    ITEM_QUERY_STYLE = 1
    COMBINED_QUERY_STYLE = 2


class BaseUI(ABC):
    @abstractmethod
    def notify(self, message: str) -> None:
        pass

    @abstractmethod
    def select_query(
        self,
        query: str,
        options,
        query_style=QueryStyle.ITEM_QUERY_STYLE,
        initial_index=None,
        show_item_number: bool = True,
        adhoc_keys=None,
    ):
        """Display a list to the user to choose."""

    @abstractmethod
    def user_input(self, query: str):
        pass

    @abstractmethod
    def wait_screen(
        self, prompt: str, wait_function: Callable[..., _T], *args, **kwargs
    ) -> _T:
        """Display a message while the user waits for a function to execute."""

    @abstractmethod
    def yes_no_query(self, prompt: str) -> bool:
        """Ask user yes or no and return True if yes else No."""
