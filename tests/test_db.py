from youtube_rss import config, db


def test_save_fetch():
    database = config.CONFIG.get_database()
    database.new()
    feed = db.Feed("A", "A", [])
    database.add(feed)
    result = database.fetch_one_or_none(db.Feed, channel_id="A")
    assert result == feed


def test_database_save_load():
    database = config.CONFIG.get_database()
    database.new()
    feed = db.Feed("A", "A", [])
    database.add(feed)
    del database

    database = config.CONFIG.get_database()
    feeds = database.fetch_all(db.Feed)
    assert len(feeds) == 1
    assert isinstance(feeds[0], db.Feed)
    assert feeds[0].channel_id == "A"
