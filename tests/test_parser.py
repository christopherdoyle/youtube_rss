import pytest

import youtube_rss.parser


def test_get_channel_query_results():
    query = "music"
    results = youtube_rss.parser.get_channel_query_results(query)
    assert len(results) > 1


def test_get_rss_entries_from_channel_id():
    result = youtube_rss.parser.get_rss_entries_from_channel_id(pytest.TEST_CHANNEL_ID)
    assert len(result) > 0
