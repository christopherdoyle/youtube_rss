import logging
import os
import signal
import sys

from . import command_line_parser, db, tui, utils, youtube_rss
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

    flags = command_line_parser.read_flags(sys.argv)
    for flag in flags:
        if flag not in command_line_parser.allowed_flags:
            raise command_line_parser.CommandLineParseError

    if "use-thumbnails" in flags:
        flag = flags[flags.index("use-thumbnails")]
        flag.treated = True
        CONFIG.USE_THUMBNAILS = True

    for flag in flags:
        if not flag.treated:
            raise command_line_parser.CommandLineParseError

    if not CONFIG.DATABASE_PATH.is_file():
        logger.info("Initializing new database")
        database = db.initialize_database()
        tui.wait_screen("", database.to_json, CONFIG.DATABASE_PATH)
    else:
        tui.wait_screen("", db.Database.from_json, CONFIG.DATABASE_PATH)

    youtube_rss.do_main_menu()
    logger.info("Program end")
    os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    main()
