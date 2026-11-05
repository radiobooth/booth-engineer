import json
from datetime import UTC, datetime

import pytest
from test_deliver import make_show

from radiobooth import history
from radiobooth.cli import remember


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    return tmp_path / "cfg"


def catalog(*ids):
    return {"protocol": "radiobooth/catalog@0", "tracks": [{"id": i} for i in ids]}


def test_delivered_tracks_are_marked_in_later_catalogs(tmp_path, cfg):
    package = json.loads((make_show(tmp_path) / "show.json").read_text())
    history.record_package(package, datetime(2026, 11, 5, 8, 0, tzinfo=UTC))
    assert (cfg / "history.json").is_file()
    tracks = history.annotate(catalog("101", "103", "999"))["tracks"]
    assert tracks == [
        {"id": "101", "last_in_show_at": "2026-11-05T08:00:00Z"},
        {"id": "103", "last_in_show_at": "2026-11-05T08:00:00Z"},
        {"id": "999"},
    ]


def test_a_later_show_moves_the_date_and_keeps_the_rest():
    history.record(["1", "2"], datetime(2026, 11, 1, tzinfo=UTC))
    history.record(["2"], datetime(2026, 11, 4, tzinfo=UTC))
    assert history.load() == {"1": "2026-11-01T00:00:00Z", "2": "2026-11-04T00:00:00Z"}


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"tracks": []}', '{"tracks": {"1": 5}}'])
def test_a_broken_or_missing_history_is_empty(cfg, text):
    assert history.load() == {}
    cfg.mkdir()
    (cfg / "history.json").write_text(text)
    assert history.load() == {}
    assert history.annotate(catalog("1"))["tracks"] == [{"id": "1"}]
    history.record(["1"])  # and the next delivery starts it over
    assert list(history.load()) == ["1"]


def test_history_trouble_never_fails_a_delivery(tmp_path, monkeypatch):
    show = make_show(tmp_path)
    monkeypatch.setattr(history, "record", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    log = []
    remember(show, log.append)
    assert "disk full" in log[0]
