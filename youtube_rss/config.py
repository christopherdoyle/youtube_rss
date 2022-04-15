import logging
import os
from pathlib import Path

from . import db

logger = logging.getLogger("youtube_rss.config")


def get_app_data_directory() -> Path:
    if os.name == "nt":
        app_data_dir = os.environ.get("APPDATA")
    else:
        app_data_dir = os.environ.get("XDG_DATA_HOME")
        if app_data_dir is None:
            app_data_dir = os.path.join(
                os.environ.get("HOME"),
                ".local",
                "share",
            )

    if app_data_dir is None:
        raise OSError("Could not find app data directory")

    return Path(app_data_dir)


class Config:
    YOUTUBE_RSS_DIR = get_app_data_directory() / "youtube_rss"
    THUMBNAIL_DIR = YOUTUBE_RSS_DIR / "thumbnails"
    THUMBNAIL_SEARCH_DIR = THUMBNAIL_DIR / "search"
    DATABASE_PATH = YOUTUBE_RSS_DIR / "database"
    LOG_PATH = YOUTUBE_RSS_DIR / "run.log"

    HIGHLIGHTED = 1
    NOT_HIGHLIGHTED = 2

    ANY_INDEX = -1

    USE_THUMBNAILS = False

    def __init__(self) -> None:
        self.YOUTUBE_RSS_DIR.mkdir(parents=True, exist_ok=True)
        self.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        self.THUMBNAIL_SEARCH_DIR.mkdir(parents=True, exist_ok=True)
        self._ui = None

    def get_database(self) -> db.IDatabase:
        database = db.JsonDatabase({}, self.DATABASE_PATH)
        if not CONFIG.DATABASE_PATH.is_file():
            logger.info("Initializing new database")
            database.new()
        else:
            database.connect()

        return database

    def get_ui(self):
        from . import ui

        if self._ui is None:
            self._ui = ui.tui.TUI()
        return self._ui


CONFIG = Config()
