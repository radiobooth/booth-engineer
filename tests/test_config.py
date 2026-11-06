import json

from radiobooth import cli, config


def test_saved_address_follows_booth_dj_to_its_new_home(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    monkeypatch.setenv("BOOTH_CONFIG", str(p))
    p.write_text(json.dumps({"server": "https://booth-dj-juvsqx4frq-uc.a.run.app/", "device_token": "be_x"}))
    assert config.load() == {"server": cli.DEFAULT_SERVER, "device_token": "be_x"}


def test_other_saved_addresses_stay_put(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    monkeypatch.setenv("BOOTH_CONFIG", str(p))
    p.write_text(json.dumps({"server": "http://localhost:8080"}))
    assert config.load()["server"] == "http://localhost:8080"


def test_old_addresses_move_to_the_default():
    assert set(config.MOVED.values()) == {cli.DEFAULT_SERVER}
