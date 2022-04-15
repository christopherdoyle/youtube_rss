import logging
import shutil
from multiprocessing import Process, ProcessError
from pathlib import Path
from typing import List

import requests

from . import db, output, parser, ui, utils
from .config import CONFIG

logger = logging.getLogger("youtube_rss")

RETURN_FROM_MENU = object()


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
    def __init__(self, video: db.FeedEntry, activation_index, key=ord("a")):
        item = MethodMenuDecision(
            "mark video as read",
            self._mark_read,
            video,
        )
        super().__init__(key=key, item=item, activation_index=activation_index)

    @staticmethod
    def _mark_read(video: db.FeedEntry) -> None:
        video.seen = True


# use this function to add a subscription to the database
def add_subscription_to_database(
    channel_id: str, channel_title: str, refresh: bool = False
) -> None:
    database = CONFIG.get_database()
    feed = database.fetch_one_or_none(db.Feed, channel_id=channel_id)
    new_feed = db.Feed(channel_id=channel_id, title=channel_title, entries=[])
    if feed is None:
        database.add(new_feed)
        feed = new_feed
    else:
        feed.update(new_feed)

    database.save()

    if refresh:
        refresh_subscriptions_by_channel_id([feed])


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


# use this function to retrieve new RSS entries for a subscription and add them to
# a database
def refresh_subscriptions_by_channel_id(feeds: List[db.Feed]):
    process = Process(
        target=refresh_subscriptions_by_channel_id_process,
        args=(feeds,),
    )
    try:
        process.start()
        process.join()
    except Exception as e:
        logger.error(e)
        process.kill()
        raise e
    if process.exitcode != 0:
        raise ProcessError("Non-zero exit code")


def refresh_subscriptions_by_channel_id_process(feeds: List[db.Feed]):
    database = CONFIG.get_database()
    threads = []

    for feed in feeds:
        feed_ = database.fetch_one_or_none(db.Feed, channel_id=feed.channel_id)
        if feed_ is None:
            continue

        thread = utils.ErrorCatchingThread(
            refresh_subscription_by_channel_id,
            feed_,
        )
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    if CONFIG.USE_THUMBNAILS:
        get_thumbnails_for_all_subscriptions(feeds, database)

    database.save()


def refresh_subscription_by_channel_id(feed: db.Feed):
    remote_feed = parser.get_rss_entries_from_channel_id(feed.channel_id)
    if remote_feed is not None:
        remote_feed.reverse()
        for remote_entry in remote_feed:
            filtered_entry = get_relevant_dict_from_feed_parser_dict(remote_entry)

            for entry in feed.entries:
                if entry.video_id == filtered_entry.video_id:
                    # in case any relevant data about the entry is changed, update it
                    filtered_entry.seen = entry.seen
                    entry.update(filtered_entry)
                    break
            else:
                feed.entries.insert(0, filtered_entry)


# use this function to get the data we care about from the entries found by the
# RSS parser
def get_relevant_dict_from_feed_parser_dict(feedparser_dict) -> db.FeedEntry:
    return db.FeedEntry(
        video_id=feedparser_dict["id"],
        link=feedparser_dict["link"],
        title=feedparser_dict["title"],
        thumbnail=feedparser_dict["media_thumbnail"][0]["url"],
        seen=False,
    )


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
    database.to_json(CONFIG.DATABASE_PATH)


# this is the application level flow entered when the user has chosen to search for a
# video
def do_interactive_search_for_video():
    query = CONFIG.get_ui().user_input("Search for video: ")
    querying = True
    while querying:
        try:
            result_list = CONFIG.get_ui().wait_screen(
                "Getting video results...",
                parser.get_video_query_results,
                query,
            )
            if result_list:
                menu_options = [
                    MethodMenuDecision(
                        result,
                        play_video,
                        result.url,
                    )
                    for result in result_list
                ]
                menu_options.insert(
                    0, MethodMenuDecision("[Go back]", return_from_menu)
                )
                do_method_menu(f"Search results for '{query}':", menu_options)
                querying = False
            else:
                CONFIG.get_ui().notify("no results found")
                querying = False
        except ProcessError as e:
            logger.error(e)
            if not CONFIG.get_ui().yes_no_query("Something went wrong. Try again?"):
                querying = False

    if CONFIG.THUMBNAIL_SEARCH_DIR.is_dir():
        shutil.rmtree(CONFIG.THUMBNAIL_SEARCH_DIR)


def get_thumbnails_for_all_subscriptions(channel_id_list, database):
    feeds = database["feeds"]
    threads = []
    for channel_id in channel_id_list:
        feed = feeds[channel_id]
        thread = utils.ErrorCatchingThread(get_thumbnails_for_feed, feed)
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()


def get_thumbnails_for_feed(feed):
    for entry in feed:
        if "thumbnail file" in entry:
            continue
        video_id = entry["id"].split(":")[-1]
        thumbnail_filename = CONFIG.THUMBNAIL_DIR / video_id + ".jpg"
        thumbnail_content = parser.get_http_content(entry["thumbnail"])
        entry["thumbnail file"] = thumbnail_filename
        thumbnail_filename.write_bytes(thumbnail_content.content)


# this is the application level flow entered when the user has chosen to subscribe to a
# new channel
def do_interactive_channel_subscribe():
    query = CONFIG.get_ui().user_input("Enter channel to search for: ")
    querying = True
    while querying:
        try:
            result_list = CONFIG.get_ui().wait_screen(
                "Getting channel results...",
                parser.get_channel_query_results,
                query,
            )
            if result_list:
                menu_options = [
                    MethodMenuDecision(
                        str(result),
                        do_channel_subscribe,
                        result=result,
                    )
                    for result in result_list
                ]
                menu_options.insert(
                    0, MethodMenuDecision("[Go back]", return_from_menu)
                )
                do_method_menu(
                    f"search results for '{query}', choose which "
                    + "channel to supscribe to",
                    menu_options,
                )
                querying = False
            else:
                if not CONFIG.get_ui().yes_no_query("No results found. Try again?"):
                    querying = False
        except requests.exceptions.ConnectionError as e:
            logger.error(e)
            if not CONFIG.get_ui().yes_no_query(
                "Something went wrong with the connection. Try again?"
            ):
                querying = False


# this is the application level flow entered when the user has chosen a channel that it
# wants to subscribe to
def do_channel_subscribe(result: parser.ChannelQueryObject):
    database: db.IDatabase = CONFIG.get_ui().wait_screen("", CONFIG.get_database)

    if database.fetch(db.Feed, channel_id=result.channel_id):
        CONFIG.get_ui().notify("Already subscribed to this channel!")
        return

    while True:
        try:
            CONFIG.get_ui().wait_screen(
                f"getting data from feed for {result.title}...",
                add_subscription_to_database,
                result.channel_id,
                result.title,
                refresh=True,
            )
            break
        except requests.exceptions.ConnectionError as e:
            logger.error(e)
            if not CONFIG.get_ui().yes_no_query(
                "Something went wrong with the " + "connection. Try again?"
            ):
                do_channel_unsubscribe(result.channel_id)
                break

    return RETURN_FROM_MENU


# this is the application level flow entered when the user has chosen to unsubscribe to
# a channel
def do_interactive_channel_unsubscribe():
    database: db.IDatabase = CONFIG.get_ui().wait_screen("", CONFIG.get_database)
    if not database.fetch_first(db.Feed):
        CONFIG.get_ui().notify("You are not subscribed to any channels")
        return
    menu_options = [
        MethodMenuDecision(feed.title, do_channel_unsubscribe, feed.channel_id)
        for feed in database.fetch_all(db.Feed)
    ]
    menu_options.insert(0, MethodMenuDecision("[Go back]", return_from_menu))
    do_method_menu("Which channel do you want to unsubscribe from?", menu_options)


# this is the application level flow entered when the user has chosen a channel that it
# wants to unsubscribe from
def do_channel_unsubscribe(channel_id):
    database = CONFIG.get_ui().wait_screen("", CONFIG.get_database)
    database.remove(db.Feed, channel_id=channel_id)
    if CONFIG.USE_THUMBNAILS:
        delete_thumbnails_by_channel_title(database, channel_id)
    database.save()
    return RETURN_FROM_MENU


def describe_feed(feed: db.Feed) -> str:
    return "".join(
        (
            feed.title,
            ": (",
            str(sum(1 for entry in feed.entries if not entry.seen)),
            "/",
            str(len(feed.entries)),
            ")",
        )
    )


# this is the application level flow entered when the user has chosen to browse
# its current subscriptions
def do_interactive_browse_subscriptions():
    database: db.IDatabase = CONFIG.get_ui().wait_screen("", CONFIG.get_database)
    menu_options = [
        MethodMenuDecision(
            describe_feed(feed),
            do_select_video_from_subscription,
            database,
            feed.channel_id,
        )
        for feed in database.fetch_all(db.Feed)
    ]

    adhoc_keys = [
        MarkAllAsReadKey(channel_id, i + 1, database)
        for i, channel_id in enumerate(database.fetch_all(db.Feed))
    ]

    if not menu_options:
        CONFIG.get_ui().notify("You are not subscribed to any channels")
        return

    menu_options.insert(0, MethodMenuDecision("[Go back]", return_from_menu))
    do_method_menu(
        "Which channel do you want to watch a video from?",
        menu_options,
        adhoc_keys=adhoc_keys,
    )


def describe_feed_entry(feed_entry: db.FeedEntry) -> str:
    return feed_entry.title + (" (unseen!)" if not feed_entry.seen else "")


# this is the application level flow entered when the user has chosen a channel while
# browsing its current subscriptions;
# the user now gets to select a video from the channel to watch
def do_select_video_from_subscription(database: db.IDatabase, channel_id):
    feed = database.fetch_one_or_none(db.Feed, channel_id=channel_id)
    if feed is None:
        raise ValueError("Feed not found")

    menu_options = [
        MethodMenuDecision(
            describe_feed_entry(entry),
            do_play_video_from_subscription,
            database,
            entry,
        )
        for entry in feed.entries
    ]

    adhoc_keys = [
        MarkEntryAsReadKey(video, i + 1) for i, video in enumerate(feed.entries)
    ]
    database.save()
    menu_options.insert(0, MethodMenuDecision("[Go back]", return_from_menu))
    do_method_menu(
        "Which video do you want to watch?", menu_options, adhoc_keys=adhoc_keys
    )
    database.save()


# this is the application level flow entered when the user has selected a video to watch
# while browsing its current subscriptions
def do_play_video_from_subscription(database: db.IDatabase, video: db.FeedEntry):
    result = play_video(video.link)
    if not video.seen:
        video.seen = result
        database.save()


# this is the application level flow entered when the user is watching any video from
# YouTube
def play_video(video_url):
    resolution_menu_list = [1080, 720, 480, 240]
    max_resolution = CONFIG.get_ui().select_query(
        "Which maximum resolution do you want to use?", resolution_menu_list
    )
    result = False
    while not result:
        result = CONFIG.get_ui().wait_screen(
            "playing video...",
            output.open_url_in_mpv,
            video_url,
            max_resolution=max_resolution,
        )
        if result or not CONFIG.get_ui().yes_no_query(
            "Something went wrong when playing the video. Try again?"
        ):
            break
    return result


# this is the application level flow entered when the user has chosen to refresh its
# subscriptions
def do_refresh_subscriptions():
    database: db.IDatabase = CONFIG.get_ui().wait_screen("", CONFIG.get_database)
    feeds = database.fetch_all(db.Feed)
    while True:
        try:
            CONFIG.get_ui().wait_screen(
                "refreshing subscriptions...",
                refresh_subscriptions_by_channel_id,
                feeds,
            )
            break
        except ProcessError as e:
            logger.error("Failed to refresh subscriptions")
            logger.error(e)
            if not CONFIG.get_ui().yes_no_query("Something went wrong. Try again?"):
                break


def do_main_menu():
    menu_options = [
        MethodMenuDecision(
            "Search for video",
            do_interactive_search_for_video,
        ),
        MethodMenuDecision(
            "Refresh subscriptions",
            do_refresh_subscriptions,
        ),
        MethodMenuDecision(
            "Browse subscriptions",
            do_interactive_browse_subscriptions,
        ),
        MethodMenuDecision(
            "Subscribe to new channel",
            do_interactive_channel_subscribe,
        ),
        MethodMenuDecision(
            "Unsubscribe from channel",
            do_interactive_channel_unsubscribe,
        ),
        MethodMenuDecision("Quit", return_from_menu),
    ]
    do_method_menu("What do you want to do?", menu_options)


# this is a function for managing menu hierarchies; once called, a menu presents
# application flows available to the user. If called from a flow selected in a previous
# method menu, the menu becomes a new branch one step further from the root menu
def do_method_menu(query, menu_options, show_item_number=True, adhoc_keys=None):
    index = 0
    try:
        while True:
            method_menu_decision, index = CONFIG.get_ui().select_query(
                query,
                menu_options,
                initial_index=index,
                query_style=ui.QueryStyle.COMBINED_QUERY_STYLE,
                show_item_number=show_item_number,
                adhoc_keys=adhoc_keys or [],
            )
            try:
                result = method_menu_decision.execute_decision()
            except KeyboardInterrupt:
                result = None
            if result is RETURN_FROM_MENU:
                return
    except KeyboardInterrupt:
        return


def return_from_menu():
    return RETURN_FROM_MENU
