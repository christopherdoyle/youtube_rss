import pytest

from youtube_rss import config, db, youtube_rss


def test_refresh_subscriptions__empty():
    feeds = []
    youtube_rss.refresh_subscriptions_by_channel_id(feeds)


def test_refresh_subscriptions():
    database = config.CONFIG.get_database()
    database.new()
    feed = db.Feed(pytest.TEST_CHANNEL_ID, pytest.TEST_CHANNEL_TITLE, [])
    database.add(feed)
    youtube_rss.refresh_subscriptions_by_channel_id([feed])
    database.connect()
    feed_ = database.fetch_one_or_none(db.Feed, channel_id=feed.channel_id)
    assert len(feed_.entries) > 1


def test_subscribe():
    database = config.CONFIG.get_database()
    database.new()
    youtube_rss.add_subscription_to_database(
        pytest.TEST_CHANNEL_ID, pytest.TEST_CHANNEL_TITLE, refresh=True
    )
