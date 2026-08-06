from core.config import FeedConfig
from roles.blair.tools import feed, tables, workspace

CFG = FeedConfig("host", 22, "user", "password", "/data")


def test_csv_can_become_a_generic_table(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "ROOT", tmp_path)
    monkeypatch.setattr(feed, "_download", lambda cfg, name: b"id,name\n1,one\n2,two\n")

    result = feed.read_file(CFG, "things.csv", save_as="things")

    assert result["table"]["source"] == "feed:things.csv"
    assert tables.load("things") == [
        {"id": "1", "name": "one"},
        {"id": "2", "name": "two"},
    ]


def test_large_text_read_is_paged(monkeypatch):
    monkeypatch.setattr(feed, "MAX_BYTES", 5)
    monkeypatch.setattr(feed, "_download", lambda cfg, name: b"abcdefgh")

    result = feed.read_file(CFG, "notes.txt")

    assert result["text"] == "abcde"
    assert result["complete"] is False
    assert result["next_offset"] == 5


def test_filename_cannot_escape(monkeypatch):
    monkeypatch.setattr(feed, "_download", lambda cfg, name: b"secret")

    assert "error" in feed.read_file(CFG, "../secret")
