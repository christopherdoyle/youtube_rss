import os
from pathlib import Path


class Config:
    HOME = Path(os.environ.get("HOME"))
    YOUTUBE_RSS_DIR = HOME / ".youtube_rss"
    THUMBNAIL_DIR = YOUTUBE_RSS_DIR / "thumbnails"
    THUMBNAIL_SEARCH_DIR = THUMBNAIL_DIR / "search"
    DATABASE_PATH = YOUTUBE_RSS_DIR / "database"
    LOG_PATH = YOUTUBE_RSS_DIR / "run.log"

    HIGHLIGHTED = 1
    NOT_HIGHLIGHTED = 2

    ANY_INDEX = -1

    USE_THUMBNAILS = False


CONFIG = Config()
