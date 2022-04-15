import argparse
import logging
import os
import signal
import sys

from . import tui, utils, youtube_rss
from .config import CONFIG

logger = logging.getLogger("youtube_rss")


def main():
    logger.level = logging.DEBUG
    handler = logging.FileHandler(CONFIG.LOG_PATH)
    handler.level = logging.DEBUG
    logger.addHandler(handler)
    logger.info("Program start")

    if not utils.is_mpv_installed():
        logger.error("MPV not found")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--use_thumbnails", action="store_true", default=False)
    parsed_args = parser.parse_args()
    CONFIG.USE_THUMBNAILS = parsed_args.use_thumbnails

    tui.wait_screen("", CONFIG.get_database)
    youtube_rss.do_main_menu()
    logger.info("Program end")
    os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    main()
