from youtube_rss import config, db, youtube_rss

TEST_CHANNEL_ID = "UCXuqSBlHAE6Xw-yeJA0Tunw"
TEST_CHANNEL_TITLE = "Linus Tech Tips"


def test_get_channel_query_results():
    query = "music"
    results = youtube_rss.get_channel_query_results(query)
    assert len(results) > 1


def test_refresh_subscriptions__empty():
    feeds = []
    youtube_rss.refresh_subscriptions_by_channel_id(feeds)


def test_get_rss_entries_from_channel_id():
    result = youtube_rss.get_rss_entries_from_channel_id(TEST_CHANNEL_ID)
    assert len(result) > 0


def test_refresh_subscriptions():
    database = config.CONFIG.get_database()
    database.new()
    feed = db.Feed(TEST_CHANNEL_ID, "", [])
    database.add(feed)
    youtube_rss.refresh_subscriptions_by_channel_id([feed])
    database.connect()
    feed_ = database.fetch_one_or_none(db.Feed, channel_id=feed.channel_id)
    assert len(feed_.entries) > 1


def test_subscribe():
    database = config.CONFIG.get_database()
    database.new()
    youtube_rss.add_subscription_to_database(
        TEST_CHANNEL_ID, TEST_CHANNEL_TITLE, refresh=True
    )
