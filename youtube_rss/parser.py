import logging
import re
import shutil
import urllib
from html.parser import HTMLParser
from multiprocessing import Process, ProcessError
from pathlib import Path
from typing import List

import feedparser
import requests

from . import utils
from .config import CONFIG

logger = logging.getLogger(__name__)


class RssAddressParser(HTMLParser):
    """Parser used for extracting an RSS Address from channel page HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rss_address = None

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if "type" in attr_dict and attr_dict["type"] == "application/rss+xml":
            self.rss_address = attr_dict["href"]


class ChannelQueryParser(HTMLParser):
    """Parser used for extracting information about channels from YouTube channel query
    HTML.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.is_script_tag = False
        self.result_list: List[ChannelQueryObject] = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.is_script_tag = True

    def handle_data(self, data):
        if self.is_script_tag:
            self.is_script_tag = False
            if "var ytInitialData" in data:
                pattern = re.compile(
                    # fmt: off
                    r'"channelRenderer":\{'
                    r'"channelId":"([^"]+)",'
                    r'"title":\{"simpleText":"([^"]+)"'
                    # fmt: on
                )
                tuple_list = pattern.findall(data)
                result_list = []
                for tup in tuple_list:
                    result_list.append(
                        ChannelQueryObject(channel_id=tup[0], title=tup[1])
                    )
                self.result_list = result_list


class VideoQueryParser(HTMLParser):
    """Parser used for extracting information about channels from YouTube channel query
    HTML.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.is_script_tag = False
        self.result_list: List[VideoQueryObject] = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.is_script_tag = True

    def handle_data(self, data):
        if self.is_script_tag:
            self.is_script_tag = False
            if "var ytInitialData" in data:
                # fmt: off
                pattern = re.compile(
                    r'videoId":"([^"]+)",'
                    r'"thumbnail":'
                    r'{"thumbnails":\['
                    r'\{"url":"([^"]+)","width":[0-9]+,"height":[0-9]+\},'
                    r'\{"url":"[^"]+","width":[0-9]+,"height":[0-9]+\}'
                    r'\]\},'
                    r'"title":\{'
                    r'"runs":\[\{"text":"[^"]+"\}\],'
                    r'"accessibility":\{"accessibilityData":\{"label":"([^"]+)"'
                    r'\}'
                )
                # fmt: on
                tuple_list = pattern.findall(data)
                result_list = []
                for tup in tuple_list:
                    result_list.append(
                        VideoQueryObject(
                            video_id=tup[0], thumbnail=tup[1], title=tup[2]
                        )
                    )
                self.result_list = result_list


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


class ChannelQueryObject:
    def __init__(self, channel_id=None, title=None):
        self.channel_id = channel_id
        self.title = title

    def __str__(self):
        return f"{self.title}  --  (channel ID {self.channel_id})"


def get_http_content(url, method="GET", post_payload=None):
    session = requests.Session()
    session.headers["Accept-Language"] = "en-US"
    # This cookie lets us avoid the YouTube consent page
    session.cookies["CONSENT"] = "YES+"
    if method == "GET":
        return session.get(url)
    elif method == "POST":
        return session.post(url, post_payload or {})


def get_rss_address_from_channel_id(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def get_channel_query_results(query) -> List[ChannelQueryObject]:
    """Get a list of channels that match a query."""
    url = (
        "https://youtube.com/results?search_query="
        + urllib.parse.quote(query)
        + "&sp=EgIQAg%253D%253D"
    )
    html_content = get_http_content(url).text
    p = ChannelQueryParser()
    p.feed(html_content)
    return p.result_list


def get_video_query_results(query) -> List[VideoQueryObject]:
    """Get a list of videos that match a query."""
    url = (
        "https://youtube.com/results?search_query="
        + urllib.parse.quote(query)
        + "&sp=EgIQAQ%253D%253D"
    )
    html_content = get_http_content(url).text
    p = VideoQueryParser()
    p.feed(html_content)
    if CONFIG.USE_THUMBNAILS:
        if CONFIG.THUMBNAIL_SEARCH_DIR.is_dir():
            shutil.rmtree(CONFIG.THUMBNAIL_SEARCH_DIR)

        CONFIG.THUMBNAIL_SEARCH_DIR.mkdir()
        process = Process(
            target=get_search_thumbnails,
            args=(p.result_list,),
        )
        try:
            process.start()
            process.join()
        except Exception as e:
            logger.error(e)
            process.kill()
            raise e
        if process.exitcode != 0:
            raise ProcessError
    return p.result_list


def get_rss_entries_from_channel_id(channel_id):
    rss_address = get_rss_address_from_channel_id(channel_id)
    rss_content = get_http_content(rss_address).text
    entries = feedparser.parse(rss_content)["entries"]
    return entries


def get_search_thumbnail_from_search_result(result):
    video_id = result.video_id.split(":")[-1]
    thumbnail_filename: Path = CONFIG.THUMBNAIL_SEARCH_DIR / video_id + ".jpg"
    thumbnail_content = get_http_content(result.thumbnail)
    result.thumbnailFile = thumbnail_filename
    thumbnail_filename.write_bytes(thumbnail_content.content)


def get_search_thumbnails(result_list):
    threads = []
    for result in result_list:
        thread = utils.ErrorCatchingThread(
            get_search_thumbnail_from_search_result,
            result,
        )
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
