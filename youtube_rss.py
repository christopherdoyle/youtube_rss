#! /usr/bin/env python3

import curses
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import urllib
import urllib.parse
from abc import ABC
from html.parser import HTMLParser
from json import JSONDecoder, JSONEncoder
from multiprocessing import Process, ProcessError
from pathlib import Path
from typing import Optional

import feedparser
import requests as req

import command_line_parser

try:
    import ueberzug.lib.v0 as ueberzug
except ImportError:
    ueberzug = None

#############
# constants #
#############


class Config:
    HOME = Path(os.environ.get("HOME"))
    YOUTUBE_RSS_DIR = HOME / ".youtube_rss"
    THUMBNAIL_DIR = YOUTUBE_RSS_DIR / "thumbnails"
    THUMBNAIL_SEARCH_DIR = THUMBNAIL_DIR / "search"
    DATABASE_PATH = YOUTUBE_RSS_DIR / "database"
    LOG_PATH = YOUTUBE_RSS_DIR / "log"

    HIGHLIGHTED = 1
    NOT_HIGHLIGHTED = 2

    ANY_INDEX = -1

    USE_THUMBNAILS = False


CONFIG = Config()

###########
# classes #
###########

"""
Thread classes
"""


class ErrorCatchingThread(threading.Thread):
    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.exc = None

    def run(self):
        self.exc = None
        try:
            self.function(*self.args, **self.kwargs)
        except SystemExit:
            raise SystemExit
        except Exception as exc:
            self.exc = exc

    def join(self, timeout: Optional[float] = None) -> None:
        try:
            super().join(timeout)
            if self.exc is not None:
                raise self.exc
        except KeyboardInterrupt:
            os.kill(os.getpid(), signal.SIGTERM)

    def get_thread_id(self):
        if hasattr(self, "_thread_id"):
            return self._thread_id
        for thread_id, thread in threading._active.items():
            if thread is self:
                return thread_id


"""
Parser classes
"""


# Parser used for extracting an RSS Address from channel page HTML
class RssAddressParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rss_address = None

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if "type" in attr_dict and attr_dict["type"] == "application/rss+xml":
            self.rss_address = attr_dict["href"]


# Parser used for extracting information about channels from YouTube channel query HTML
class ChannelQueryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.is_script_tag = False
        self.result_list = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.is_script_tag = True

    def handle_data(self, data):
        if self.is_script_tag:
            self.is_script_tag = False
            if "var ytInitialData" in data:
                pattern = re.compile(
                    '"channelRenderer":{"channel_id":"([^"]+)",'
                    + '"title":{"simpleText":"([^"]+)"'
                )
                tuple_list = pattern.findall(data)
                result_list = []
                for tup in tuple_list:
                    result_list.append(
                        ChannelQueryObject(channel_id=tup[0], title=tup[1])
                    )
                self.result_list = result_list


# Parser used for extracting information about channels from YouTube channel query HTML
class VideoQueryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.is_script_tag = False
        self.result_list = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.is_script_tag = True

    def handle_data(self, data):
        if self.is_script_tag:
            self.is_script_tag = False
            if "var ytInitialData" in data:
                pattern = re.compile(
                    'video_id":"([^"]+)","thumbnail":{"thumbnails":'
                    + '[{"url":"([^"]+)","width":[0-9]+,"height":[0-9]+},{"url"'
                    + ':"[^"]+","width":[0-9]+,"height":[0-9]+}]},"title":{'
                    + '"runs":[{"text":"[^"]+"}],"accessibility":{'
                    + '"accessibilityData":{"label":"([^"]+)"}'
                )
                tuple_list = pattern.findall(data)
                result_list = []
                for tup in tuple_list:
                    result_list.append(
                        VideoQueryObject(
                            video_id=tup[0], thumbnail=tup[1], title=tup[2]
                        )
                    )
                self.result_list = result_list


"""
Indicator classes
"""


# Parent to all indicator classes
class IndicatorClass(ABC):
    pass


class NoCanvas(IndicatorClass):
    def __exit__(self, dummy1, dummy2, dummy3):
        pass

    def __enter__(self):
        pass


# returned from menu method to indicate that application flow should step
# closer to the root menu
class ReturnFromMenu(IndicatorClass):
    pass


# indicates whether selection query should return by index, item or both
class QueryStyle(IndicatorClass):
    pass


# indicates that selection query should return by index
class IndexQuery(QueryStyle):
    pass


# indicates that selection query should return by item
class ItemQuery(QueryStyle):
    pass


# indicates that selection query should return by both item and index
class CombinedQuery(QueryStyle):
    pass


"""
Exception classes
"""


# indicates that the provided query style is not supported
class UnknownQueryStyle(Exception):
    pass


class InstantiateIndicatorClassError(Exception):
    def __init__(self, message="Can't instantiate an indicator class!"):
        self.message = message
        super().__init__(message)


"""
Other classes
"""


# contains information from one result item from video query
class VideoQueryObject:
    def __init__(self, video_id=None, thumbnail=None, title=None):
        self.video_id = video_id
        self.thumbnail = thumbnail
        self.title = title
        if video_id is not None:
            self.url = f"https://youtube.com/watch?v={video_id}"
        else:
            self.url = None

    def __str__(self):
        return f"{self.title}"


# contains information from one result item from channel query
class ChannelQueryObject:
    def __init__(self, channel_id=None, title=None):
        self.channel_id = channel_id
        self.title = title

    def __str__(self):
        return f"{self.title}  --  (channel ID {self.channel_id})"


class DatabaseEncoder(JSONEncoder):
    def default(self, o):
        return o.db


class DatabaseDecoder(JSONDecoder):
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


# item of the sort provided in list to do_method_menu; it is provided a
# description of an option presented to the user, a function that will be
# executed if chosen by the user, and all arguments that the function needs
class MethodMenuDecision:
    def __init__(self, description, function, *args, **kwargs):
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.description = description

    def __str__(self):
        return str(self.description)

    def execute_decision(self):
        return self.function(*self.args, **self.kwargs)


class FeedVideoDescriber:
    def __init__(self, video):
        self.video = video

    def __str__(self):
        return self.video["title"] + (" (unseen!)" if not self.video["seen"] else "")

    def get_thumbnail(self):
        return self.video["thumbnail file"]


class VideoQueryObjectDescriber:
    def __init__(self, video_query_object):
        self.video_query_object = video_query_object

    def __str__(self):
        return self.video_query_object.title

    def get_thumbnail(self):
        return CONFIG.THUMBNAIL_SEARCH_DIR / self.video_query_object.video_id + ".jpg"


class FeedDescriber:
    def __init__(self, feed, channel_title):
        self.feed = feed
        self.channel_title = channel_title

    def __str__(self):
        return "".join(
            [
                self.channel_title,
                ": (",
                str(sum([1 for video in self.feed if not video["seen"]])),
                "/",
                str(len(self.feed)),
                ")",
            ]
        )


class AdHocKey:
    def __init__(self, key, item, activation_index=CONFIG.ANY_INDEX):
        self.key = key
        self.item = item
        self.activation_index = activation_index

    def is_valid_index(self, index):
        if self.activation_index == CONFIG.ANY_INDEX:
            return True
        else:
            return index == self.activation_index

    def __eq__(self, other):
        if isinstance(other, int):
            return other == self.key
        if isinstance(other, chr):
            return other == chr(self.key)
        if isinstance(other, AdHocKey):
            return (
                other.key == self.key
                and other.item == self.item
                and other.activation_index == self.activation_index
            )
        else:
            raise TypeError


class MarkAllAsReadKey(AdHocKey):
    def __init__(self, channel_id, activation_index, database, key=ord("a")):
        item = MethodMenuDecision(
            f"mark all by {channel_id} as read",
            do_mark_channel_as_read,
            database,
            channel_id,
        )
        super().__init__(key=key, item=item, activation_index=activation_index)


class MarkEntryAsReadKey(AdHocKey):
    def __init__(self, video, activation_index, key=ord("a")):
        item = MethodMenuDecision(
            "mark video as read",
            lambda video: video.update({"seen": (not video["seen"])}),
            video,
        )
        super().__init__(key=key, item=item, activation_index=activation_index)


#############
# functions #
#############

"""
Presentation functions
"""


# This function displays a message while the user waits for a function to execute
def do_wait_screen(message, wait_function, *args, **kwargs):
    return curses.wrapper(
        do_wait_screen_ncurses, message, wait_function, *args, **kwargs
    )


# This function is where the Ncurses level of do_wait_screen starts.
# It should never be called directly, but always through do_wait_screen!
def do_wait_screen_ncurses(stdscr, message, wait_function, *args, **kwargs):
    curses.curs_set(0)
    curses.init_pair(CONFIG.HIGHLIGHTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CONFIG.NOT_HIGHLIGHTED, curses.COLOR_WHITE, curses.COLOR_BLACK)
    print_menu(message, [], stdscr, 0, show_item_number=False)
    return wait_function(*args, **kwargs)


# This Function gets a yes/no response to some query from the user
def do_yes_no_query(query):
    return curses.wrapper(do_yes_no_query_ncurses, query)


# This function is where the Ncurses level of do_yes_no_query starts.
# It should never be called directly, but always through do_yes_no_query!
def do_yes_no_query_ncurses(stdscr, query):
    return (
        do_selection_query_ncurses(stdscr, query, ["yes", "no"], show_item_number=False)
        == "yes"
    )


# This function lets the user choose an object from a list
def do_selection_query(
    query,
    options,
    query_style=ItemQuery,
    initial_index=None,
    show_item_number=True,
    adhoc_keys=None,
):
    return curses.wrapper(
        do_selection_query_ncurses,
        query,
        options,
        query_style=query_style,
        initial_index=initial_index,
        show_item_number=show_item_number,
        adhoc_keys=adhoc_keys or [],
    )


# This function is where the Ncurses level of do_selection_query starts.
# It should never be called directly, but always through do_selection_query!
def do_selection_query_ncurses(
    stdscr,
    query,
    options,
    query_style=ItemQuery,
    initial_index=None,
    show_item_number=True,
    adhoc_keys=None,
):
    curses.curs_set(0)
    curses.init_pair(CONFIG.HIGHLIGHTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CONFIG.NOT_HIGHLIGHTED, curses.COLOR_WHITE, curses.COLOR_BLACK)
    jump_num_list = []
    if initial_index is not None:
        choice_index = initial_index
    else:
        choice_index = 0
    while True:
        with (ueberzug.Canvas() if CONFIG.USE_THUMBNAILS else NoCanvas()) as canvas:
            print_menu(
                query,
                options,
                stdscr,
                choice_index,
                show_item_number=show_item_number,
                jump_num_str="".join(jump_num_list),
                canvas=canvas,
            )
            key = stdscr.getch()
            # Ad hoc keys should always take first precedence

            if key in (adhoc_keys or []):
                for adhoc_key in adhoc_keys or []:
                    if adhoc_key.is_valid_index(choice_index):
                        if query_style is ItemQuery:
                            return adhoc_key.item
                        elif query_style is IndexQuery:
                            return choice_index
                        elif query_style is CombinedQuery:
                            return adhoc_key.item, choice_index

            elif key in [curses.KEY_UP, ord("k")]:
                jump_num_list = []
                choice_index = (choice_index - 1) % len(options)
            elif key in [curses.KEY_DOWN, ord("j")]:
                jump_num_list = []
                choice_index = (choice_index + 1) % len(options)
            elif key in [ord(digit) for digit in "1234567890"]:
                if len(jump_num_list) < 6:
                    jump_num_list.append(chr(key))
            elif key in [curses.KEY_BACKSPACE, ord("\b"), ord("\x7f")]:
                if jump_num_list:
                    jump_num_list.pop()
            elif key == ord("g"):
                jump_num_list = []
                choice_index = 0
            elif key == ord("G"):
                jump_num_list = []
                choice_index = len(options) - 1
            elif key in [ord("q"), ord("h"), curses.KEY_LEFT]:
                raise KeyboardInterrupt
            elif key in [curses.KEY_ENTER, 10, 13, ord("l"), curses.KEY_RIGHT]:
                if jump_num_list:
                    jump_num = int("".join(jump_num_list))
                    choice_index = min(jump_num - 1, len(options) - 1)
                    jump_num_list = []
                elif query_style is ItemQuery:
                    return options[choice_index]
                elif query_style is IndexQuery:
                    return choice_index
                elif query_style is CombinedQuery:
                    return options[choice_index], choice_index
                else:
                    raise UnknownQueryStyle


# This function displays a piece of information to the user until they confirm having
# seen it
def do_notify(message):
    do_selection_query(message, ["ok"], show_item_number=False)


# This function gets a string of written input from the user
def do_get_user_input(query, max_input_length=40):
    return curses.wrapper(
        do_get_user_input_ncurses, query, max_input_length=max_input_length
    )


# This function is where the Ncurses level of do_get_user_input starts.
# It should never be called directly, but always through do_get_user_input!
def do_get_user_input_ncurses(stdscr, query, max_input_length=40):
    curses.curs_set(0)
    curses.init_pair(CONFIG.HIGHLIGHTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CONFIG.NOT_HIGHLIGHTED, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.curs_set(0)
    cursor_position = 0
    user_input_chars = []
    while True:
        print_menu(
            query,
            [
                "".join(user_input_chars),
                "".join(
                    [
                        "—" if i == cursor_position else " "
                        for i in range(max_input_length)
                    ]
                ),
            ],
            stdscr,
            0,
            x_alignment=max_input_length // 2,
            show_item_number=False,
        )
        key = stdscr.getch()
        if key in [curses.KEY_BACKSPACE, ord("\b"), ord("\x7f")]:
            delete_index = cursor_position - 1
            if delete_index >= 0:
                user_input_chars.pop(cursor_position - 1)
            cursor_position = max(0, cursor_position - 1)
        elif key in [curses.KEY_DC]:
            delete_index = cursor_position + 1
            if delete_index <= len(user_input_chars):
                user_input_chars.pop(cursor_position)
        elif key in [curses.KEY_ENTER, 10, 13]:
            return "".join(user_input_chars)
        elif key == curses.KEY_LEFT:
            cursor_position = max(0, cursor_position - 1)
        elif key == curses.KEY_RIGHT:
            cursor_position = min(len(user_input_chars), cursor_position + 1)
        elif key == curses.KEY_RESIZE:
            pass
        elif len(user_input_chars) < max_input_length:
            user_input_chars.insert(cursor_position, chr(key))
            cursor_position = min(max_input_length, cursor_position + 1)


# This function is used to visually represent a query and a number of menu items to the
# user, by using nCurses. It is used for all text printing in the program (even where
# no application level menu is presented, i.e by simply not providing a query and no
# menu objects)
def print_menu(
    query,
    menu,
    stdscr,
    choice_index,
    x_alignment=None,
    show_item_number=True,
    jump_num_str="",
    canvas=None,
):
    if canvas is None:
        canvas = NoCanvas()
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    screen_center_x = width // 2
    screen_center_y = height // 2
    n_rows_to_print = len(menu) + 2

    if x_alignment is not None:
        item_x = max(min(screen_center_x - x_alignment, width - 2), 0)
    elif menu:
        menu_width = max(
            [
                len(f"{i+1}: {item}" if show_item_number else str(item))
                for i, item in enumerate(menu)
            ]
        )
        item_x = max(screen_center_x - menu_width // 2, 0)
    else:
        item_x = None

    if item_x != 0 and item_x is not None:
        item_x = max(min(item_x, width - 2), 0)

    jump_num_str = jump_num_str[: max(min(len(jump_num_str), width - 1), 0)]
    if jump_num_str:
        stdscr.addstr(0, 0, jump_num_str)

    offset = 0
    title_y = screen_center_y - n_rows_to_print // 2
    if n_rows_to_print >= height - 2:
        y_title_theoretical = screen_center_y - n_rows_to_print // 2
        y_selected_theoretical = y_title_theoretical + 2 + choice_index
        y_last_theoretical = y_title_theoretical + n_rows_to_print - 1
        offset = min(
            max(y_selected_theoretical - screen_center_y, y_title_theoretical),
            y_last_theoretical - (height - 2),
        )
    title_y -= offset

    title_x = max(screen_center_x - (len(query) // 2), 0)
    if title_x != 0:
        title_x = max(min(abs(title_x), width) * (title_x // abs(title_x)), 0)
    if len(query) >= width - 1:
        query = query[0 : width - 1]
    if 0 <= title_y < height - 1:
        stdscr.addstr(title_y, title_x, query)
    for i, item in enumerate(menu):
        item_string = f"{i+1}: {item}" if show_item_number else str(item)
        if item_x + len(item_string) >= width - 1:
            item_string = item_string[: max((width - item_x - 2), 0)]
        attr = curses.color_pair(
            CONFIG.HIGHLIGHTED if i == choice_index else CONFIG.NOT_HIGHLIGHTED
        )
        if (
            i == choice_index
            and hasattr(item, "description")
            and hasattr(item.description, "getThumbnail")
            and type(canvas) is not NoCanvas
        ):
            thumbnail_width = item_x - 1
            thumbnail_height = height - 3
            if not (thumbnail_width <= 0 or thumbnail_height <= 0):
                thumbnail_placement = canvas.create_placement(
                    "thumbnail",
                    x=0,
                    y=2,
                    scaler=ueberzug.ScalerOption.CONTAIN.value,
                    width=thumbnail_width,
                    height=thumbnail_height,
                )
                thumbnail_placement.path = item.description.get_thumbnail()
                thumbnail_placement.visibility = ueberzug.Visibility.VISIBLE
        stdscr.attron(attr)
        item_y = screen_center_y - n_rows_to_print // 2 + i + 2 - offset
        if 0 <= item_y < height - 1 and item_string:
            stdscr.addstr(item_y, item_x, item_string)
        stdscr.attroff(attr)
    stdscr.refresh()


"""
Functions for retreiving and processing network data
"""


# use this function to make HTTP requests without using Tor
def unproxied_get_http_content(url, session=None, method="GET", post_payload=None):
    if session is None:
        if method == "GET":
            return req.get(url)
        elif method == "POST":
            return req.post(url, post_payload or {})
    else:
        if method == "GET":
            return session.get(url)
        elif method == "POST":
            return session.post(url, post_payload or {})


# use this function to get content (typically hypertext or xml) using HTTP from YouTube
def get_http_content(url, circuit_manager=None, auth=None):
    session = req.Session()
    session.headers["Accept-Language"] = "en-US"
    # This cookie lets us avoid the YouTube consent page
    session.cookies["CONSENT"] = "YES+"
    response = unproxied_get_http_content(url, session=session)

    return response


# if you have a channel id, you can use this function to get the rss address
def get_rss_address_from_channel_id(channel_id):
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


# use this function to get a list of query results from searching for a channel
# results are of the type ChannelQueryObject
def get_channel_query_results(query, circuit_manager=None):
    url = (
        "https://youtube.com/results?search_query="
        + urllib.parse.quote(query)
        + "&sp=EgIQAg%253D%253D"
    )
    html_ceontent = get_http_content(url, circuit_manager=circuit_manager).text
    parser = ChannelQueryParser()
    parser.feed(html_ceontent)
    return parser.result_list


# use this function to get a list of query results from searching for a video
# results are of the type VideoQueryObject
def get_video_query_results(query, circuit_manager=None):
    url = (
        "https://youtube.com/results?search_query="
        + urllib.parse.quote(query)
        + "&sp=EgIQAQ%253D%253D"
    )
    html_ceontent = get_http_content(url, circuit_manager=circuit_manager).text
    parser = VideoQueryParser()
    parser.feed(html_ceontent)
    if CONFIG.USE_THUMBNAILS:
        if CONFIG.THUMBNAIL_SEARCH_DIR.is_dir():
            shutil.rmtree(CONFIG.THUMBNAIL_SEARCH_DIR)

        CONFIG.THUMBNAIL_SEARCH_DIR.mkdir()
        process = Process(
            target=get_search_thumbnails,
            args=(parser.result_list,),
            kwargs={"circuit_manager": circuit_manager},
        )
        try:
            process.start()
            process.join()
        except Exception as e:
            process.kill()
            raise e
        if process.exitcode != 0:
            raise ProcessError
    return parser.result_list


# use this function to get rss entries from channel id
def get_rss_entries_from_channel_id(channel_id, circuit_manager=None):
    rss_address = get_rss_address_from_channel_id(channel_id)
    rss_content = get_http_content(rss_address, circuit_manager=circuit_manager).text
    entries = feedparser.parse(rss_content)["entries"]
    return entries


# use this function to initialize the database (dict format so it's easy to save
# as json)
def initiate_youtube_rss_database():
    database = Database({})
    database["feeds"] = Database({})
    database["id to title"] = Database({})
    database["title to id"] = Database({})
    return database


# use this function to add a subscription to the database
def add_subscription_to_database(
    channel_id, channel_title, refresh=False, circuit_manager=None
):
    database = parse_database_file(CONFIG.DATABASE_PATH)
    database["feeds"][channel_id] = []
    database["id to title"][channel_id] = channel_title
    database["title to id"][channel_title] = channel_id
    output_database_to_file(database, CONFIG.DATABASE_PATH)
    if refresh:
        refresh_subscriptions_by_channel_id(
            [channel_id], circuit_manager=circuit_manager
        )


def delete_thumbnails_by_channel_title(database, channel_title):
    if channel_title not in database["title to id"]:
        return
    channel_id = database["title to id"][channel_title]
    delete_thumbnails_by_channel_id(database, channel_id)
    return


def delete_thumbnails_by_channel_id(database, channel_id):
    if channel_id not in database["id to title"]:
        return
    feed = database["feeds"][channel_id]
    for entry in feed:
        Path(entry["thumbnail file"]).unlink(missing_ok=True)


# use this function to remove a subscription from the database by channel title
def remove_subscription_from_database_by_channel_title(database, channel_title):
    if channel_title not in database["title to id"]:
        return
    channel_id = database["title to id"][channel_title]
    remove_subscription_from_database_by_channel_id(database, channel_id)
    return


# use this function to remove a subscription from the database by channel ID
def remove_subscription_from_database_by_channel_id(database, channel_id):
    if channel_id not in database["id to title"]:
        return
    channel_title = database["id to title"].pop(channel_id)
    database["title to id"].pop(channel_title)
    database["feeds"].pop(channel_id)
    output_database_to_file(database, CONFIG.DATABASE_PATH)


# use this function to retrieve new RSS entries for a subscription and add them to
# a database
def refresh_subscriptions_by_channel_id(channel_id_list, circuit_manager=None):
    process = Process(
        target=refresh_subscriptions_by_channel_id_process,
        args=(channel_id_list,),
        kwargs={"circuit_manager": circuit_manager},
    )
    try:
        process.start()
        process.join()
    except Exception as e:
        process.kill
        raise e
    if process.exitcode != 0:
        raise ProcessError


def refresh_subscriptions_by_channel_id_process(channel_id_list, circuit_manager=None):
    database = parse_database_file(CONFIG.DATABASE_PATH)
    local_feeds = database["feeds"]
    threads = []
    for channel_id in channel_id_list:
        local_feed = local_feeds[channel_id]
        thread = ErrorCatchingThread(
            refresh_subscription_by_channel_id,
            channel_id,
            local_feed,
            circuit_manager=circuit_manager,
        )
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    if CONFIG.USE_THUMBNAILS:
        get_thumbnails_for_all_subscriptions(
            channel_id_list, database, circuit_manager=circuit_manager
        )
    output_database_to_file(database, CONFIG.DATABASE_PATH)


def refresh_subscription_by_channel_id(channel_id, local_feed, circuit_manager=None):
    remote_feed = get_rss_entries_from_channel_id(
        channel_id, circuit_manager=circuit_manager
    )
    if remote_feed is not None:
        remote_feed.reverse()
        for entry in remote_feed:
            filtered_entry = get_relevant_dict_from_feed_parser_dict(entry)

            filtered_entry_is_new = True
            for i, local_entry in enumerate(local_feed):
                if local_entry["id"] == filtered_entry["id"]:
                    filtered_entry_is_new = False
                    # in case any relevant data about the entry is changed, update it
                    filtered_entry["seen"] = local_entry["seen"]
                    if (
                        filtered_entry["thumbnail"] == local_entry["thumbnail"]
                        and "thumbnail file" in filtered_entry
                    ):
                        filtered_entry["thumbnail file"] = local_entry["thumbnail file"]
                    local_feed[i] = filtered_entry
                    break
            if filtered_entry_is_new:
                local_feed.insert(0, filtered_entry)


# use this function to open a YouTube video url in mpv
def open_url_in_mpv(url, max_resolution=1080, circuit_manager=None):
    try:
        command = []
        command += [
            "mpv",
            f"--ytdl-format=bestvideo[height=?{max_resolution}]+bestaudio/best",
        ]
        command.append(url)
        mpv_process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
        )
        mpv_process.wait()
        result = mpv_process.poll()
    except KeyboardInterrupt:
        mpv_process.kill()
        mpv_process.wait()
        result = -1
    return result == 0


# use this function to get the data we care about from the entries found by the
# RSS parser
def get_relevant_dict_from_feed_parser_dict(feedparser_dict):
    output_dict = {
        "id": feedparser_dict["id"],
        "link": feedparser_dict["link"],
        "title": feedparser_dict["title"],
        "thumbnail": feedparser_dict["media_thumbnail"][0]["url"],
        "seen": False,
    }
    return output_dict


"""
Functions for managing database persistence between user sessions
"""


# use this function to read database from json file
def parse_database_file(filename):
    with open(filename, "r") as file_pointer:
        return json.load(file_pointer, cls=DatabaseDecoder)


# use this function to write json representation of database to file
def output_database_to_file(database, filename: Path):
    with filename.open("w") as file_pointer:
        return json.dump(database, file_pointer, indent=4, cls=DatabaseEncoder)


"""
Application control flow
"""


def do_mark_channel_as_read(database, channel_id):
    all_are_already_marked_as_read = True
    for video in database["feeds"][channel_id]:
        if not video["seen"]:
            all_are_already_marked_as_read = False
            break
    for video in database["feeds"][channel_id]:
        video["seen"] = not all_are_already_marked_as_read
    output_database_to_file(database, CONFIG.DATABASE_PATH)


# this is the application level flow entered when the user has chosen to search for a
# video
def do_interactive_search_for_video(circuit_manager=None):
    query = do_get_user_input("Search for video: ")
    querying = True
    while querying:
        try:
            result_list = do_wait_screen(
                "Getting video results...",
                get_video_query_results,
                query,
                circuit_manager=circuit_manager,
            )
            if result_list:
                menu_options = [
                    MethodMenuDecision(
                        VideoQueryObjectDescriber(result),
                        play_video,
                        result.url,
                        circuit_manager=circuit_manager,
                    )
                    for result in result_list
                ]
                menu_options.insert(
                    0, MethodMenuDecision("[Go back]", do_return_from_menu)
                )
                do_method_menu(f"Search results for '{query}':", menu_options)
                querying = False
            else:
                do_notify("no results found")
                querying = False
        except ProcessError:
            if not do_yes_no_query("Something went wrong. Try again?"):
                querying = False

    if CONFIG.THUMBNAIL_SEARCH_DIR.is_dir():
        shutil.rmtree(CONFIG.THUMBNAIL_SEARCH_DIR)


def get_thumbnails_for_all_subscriptions(
    channel_id_list, database, circuit_manager=None
):
    feeds = database["feeds"]
    threads = []
    for channel_id in channel_id_list:
        if circuit_manager is not None:
            auth = circuit_manager.getAuth()
        else:
            auth = None
        feed = feeds[channel_id]
        thread = ErrorCatchingThread(get_thumbnails_for_feed, feed, auth=auth)
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()


def get_thumbnails_for_feed(feed, auth=None):
    for entry in feed:
        if "thumbnail file" in entry:
            continue
        video_id = entry["id"].split(":")[-1]
        thumbnail_filename = CONFIG.THUMBNAIL_DIR / video_id + ".jpg"
        thumbnail_content = get_http_content(entry["thumbnail"], auth=auth)
        entry["thumbnail file"] = thumbnail_filename
        thumbnail_filename.write_bytes(thumbnail_content.content)


def get_search_thumbnails(result_list, circuit_manager=None):
    if circuit_manager is not None:
        auth = circuit_manager.getAuth()
    else:
        auth = None
    threads = []
    for result in result_list:
        thread = ErrorCatchingThread(
            get_search_thumbnail_from_search_result,
            result,
            auth=auth,
        )
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()


def get_search_thumbnail_from_search_result(result, auth=None):
    video_id = result.video_id.split(":")[-1]
    thumbnail_filename: Path = CONFIG.THUMBNAIL_SEARCH_DIR / video_id + ".jpg"
    thumbnail_content = get_http_content(result.thumbnail, auth=auth)
    result.thumbnailFile = thumbnail_filename
    thumbnail_filename.write_bytes(thumbnail_content.content)


# this is the application level flow entered when the user has chosen to subscribe to a
# new channel
def do_interactive_channel_subscribe(circuit_manager=None):
    query = do_get_user_input("Enter channel to search for: ")
    querying = True
    while querying:
        try:
            result_list = do_wait_screen(
                "Getting channel results...",
                get_channel_query_results,
                query,
                circuit_manager=circuit_manager,
            )
            if result_list:
                menu_options = [
                    MethodMenuDecision(
                        str(result),
                        do_channel_subscribe,
                        result=result,
                        circuit_manager=circuit_manager,
                    )
                    for result in result_list
                ]
                menu_options.insert(
                    0, MethodMenuDecision("[Go back]", do_return_from_menu)
                )
                do_method_menu(
                    f"search results for '{query}', choose which "
                    + "channel to supscribe to",
                    menu_options,
                )
                querying = False
            else:
                if not do_yes_no_query("No results found. Try again?"):
                    querying = False
        except req.exceptions.ConnectionError:
            if not do_yes_no_query(
                "Something went wrong with the connection. Try again?"
            ):
                querying = False


# this is the application level flow entered when the user has chosen a channel that it
# wants to subscribe to
def do_channel_subscribe(result, circuit_manager):
    database = do_wait_screen("", parse_database_file, CONFIG.DATABASE_PATH)
    refreshing = True
    if result.channel_id in database["feeds"]:
        do_notify("Already subscribed to this channel!")
        return
    while refreshing:
        try:
            do_wait_screen(
                f"getting data from feed for {result.title}...",
                add_subscription_to_database,
                result.channel_id,
                result.title,
                refresh=True,
                circuit_manager=circuit_manager,
            )
            refreshing = False
        except req.exceptions.ConnectionError:
            if not do_yes_no_query(
                "Something went wrong with the " + "connection. Try again?"
            ):
                do_channel_unsubscribe(result.title)
                refreshing = False
    return ReturnFromMenu


# this is the application level flow entered when the user has chosen to unsubscribe to
# a channel
def do_interactive_channel_unsubscribe():
    database = do_wait_screen("", parse_database_file, CONFIG.DATABASE_PATH)
    if not database["title to id"]:
        do_notify("You are not subscribed to any channels")
        return
    menu_options = [
        MethodMenuDecision(channel_title, do_channel_unsubscribe, channel_title)
        for channel_title in database["title to id"]
    ]
    menu_options.insert(0, MethodMenuDecision("[Go back]", do_return_from_menu))
    do_method_menu("Which channel do you want to unsubscribe from?", menu_options)


# this is the application level flow entered when the user has chosen a channel that it
# wants to unsubscribe from
def do_channel_unsubscribe(channel_title):
    database = do_wait_screen("", parse_database_file, CONFIG.DATABASE_PATH)
    if CONFIG.USE_THUMBNAILS:
        delete_thumbnails_by_channel_title(database, channel_title)
    remove_subscription_from_database_by_channel_title(database, channel_title)
    output_database_to_file(database, CONFIG.DATABASE_PATH)
    return ReturnFromMenu


# this is the application level flow entered when the user has chosen to browse
# its current subscriptions
def do_interactive_browse_subscriptions(circuit_manager):
    database = do_wait_screen("", parse_database_file, CONFIG.DATABASE_PATH)
    menu_options = [
        MethodMenuDecision(
            FeedDescriber(
                database["feeds"][database["title to id"][channel_title]], channel_title
            ),
            do_select_video_from_subscription,
            database,
            channel_title,
            circuit_manager,
        )
        for channel_title in database["title to id"]
    ]

    adhoc_keys = [
        MarkAllAsReadKey(channel_id, i + 1, database)
        for i, channel_id in enumerate(database["feeds"])
    ]

    if not menu_options:
        do_notify("You are not subscribed to any channels")
        return

    menu_options.insert(0, MethodMenuDecision("[Go back]", do_return_from_menu))
    do_method_menu(
        "Which channel do you want to watch a video from?",
        menu_options,
        adhoc_keys=adhoc_keys,
    )


# this is the application level flow entered when the user has chosen a channel while
# browsing its current subscriptions;
# the user now gets to select a video from the channel to watch
def do_select_video_from_subscription(database, channel_title, circuit_manager):
    channel_id = database["title to id"][channel_title]
    videos = database["feeds"][channel_id]
    menu_options = [
        MethodMenuDecision(
            FeedVideoDescriber(video),
            do_play_video_from_subscription,
            database,
            video,
            circuit_manager,
        )
        for video in videos
    ]

    adhoc_keys = [MarkEntryAsReadKey(video, i + 1) for i, video in enumerate(videos)]
    output_database_to_file(database, CONFIG.DATABASE_PATH)
    menu_options.insert(0, MethodMenuDecision("[Go back]", do_return_from_menu))
    do_method_menu(
        "Which video do you want to watch?", menu_options, adhoc_keys=adhoc_keys
    )
    output_database_to_file(database, CONFIG.DATABASE_PATH)


# this is the application level flow entered when the user has selected a video to watch
# while browsing its current subscriptions
def do_play_video_from_subscription(database, video, circuit_manager):
    result = play_video(video["link"], circuit_manager=circuit_manager)
    if not video["seen"]:
        video["seen"] = result
        output_database_to_file(database, CONFIG.DATABASE_PATH)


# this is the application level flow entered when the user is watching any video from
# YouTube
def play_video(video_url, circuit_manager=None):
    resolution_menu_list = [1080, 720, 480, 240]
    max_resolution = do_selection_query(
        "Which maximum resolution do you want to use?", resolution_menu_list
    )
    result = False
    while not result:
        result = do_wait_screen(
            "playing video...",
            open_url_in_mpv,
            video_url,
            max_resolution=max_resolution,
            circuit_manager=circuit_manager,
        )
        if result or not do_yes_no_query(
            "Something went wrong when playing the " + "video. Try again?"
        ):
            break
    return result


# this is the application level flow entered when the user has chosen to refresh its
# subscriptions
def do_refresh_subscriptions(circuit_manager=None):
    database = do_wait_screen("", parse_database_file, CONFIG.DATABASE_PATH)
    channel_id_list = list(database["id to title"])
    refreshing = True
    while refreshing:
        try:
            do_wait_screen(
                "refreshing subscriptions...",
                refresh_subscriptions_by_channel_id,
                channel_id_list,
                circuit_manager=circuit_manager,
            )
            refreshing = False
        except ProcessError:
            if not do_yes_no_query("Something went wrong. Try again?"):
                refreshing = False


def do_main_menu(circuit_manager=None):
    menu_options = [
        MethodMenuDecision(
            "Search for video",
            do_interactive_search_for_video,
            circuit_manager=circuit_manager,
        ),
        MethodMenuDecision(
            "Refresh subscriptions",
            do_refresh_subscriptions,
            circuit_manager=circuit_manager,
        ),
        MethodMenuDecision(
            "Browse subscriptions",
            do_interactive_browse_subscriptions,
            circuit_manager=circuit_manager,
        ),
        MethodMenuDecision(
            "Subscribe to new channel",
            do_interactive_channel_subscribe,
            circuit_manager=circuit_manager,
        ),
        MethodMenuDecision(
            "Unsubscribe from channel",
            do_interactive_channel_unsubscribe,
        ),
        MethodMenuDecision("Quit", do_return_from_menu),
    ]
    do_method_menu("What do you want to do?", menu_options)


# this is a function for managing menu hierarchies; once called, a menu presents
# application flows available to the user. If called from a flow selected in a previous
# method menu, the menu becomes a new branch one step further from the root menu
def do_method_menu(query, menu_options, show_item_number=True, adhoc_keys=None):
    index = 0
    try:
        while True:
            method_menu_decision, index = do_selection_query(
                query,
                menu_options,
                initial_index=index,
                query_style=CombinedQuery,
                show_item_number=show_item_number,
                adhoc_keys=adhoc_keys or [],
            )
            try:
                result = method_menu_decision.execute_decision()
            except KeyboardInterrupt:
                result = None
                pass
            if result is ReturnFromMenu:
                return
    except KeyboardInterrupt:
        return


# this function is an application level flow which when selected from a method
# menu simply returns to the preceding menu (one step closer to the root menu)
def do_return_from_menu():
    return ReturnFromMenu


################
# main section #
################


def main():
    flags = command_line_parser.read_flags(sys.argv)
    for flag in flags:
        if flag not in command_line_parser.allowedFlags:
            raise command_line_parser.CommandLineParseError

    if "use-thumbnails" in flags:
        flag = flags[flags.index("use-thumbnails")]
        flag.treated = True
        CONFIG.USE_THUMBNAILS = True

    for flag in flags:
        if not flag.treated:
            raise command_line_parser.CommandLineParseError

    CONFIG.YOUTUBE_RSS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG.DATABASE_PATH.is_file():
        database = initiate_youtube_rss_database()
        do_wait_screen("", output_database_to_file, database, CONFIG.DATABASE_PATH)
    else:
        database = do_wait_screen("", parse_database_file, CONFIG.DATABASE_PATH)

    do_main_menu()
    os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    main()
