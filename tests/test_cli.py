import pytest

from radiobooth import __version__
from radiobooth.cli import main


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "booth" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_pair_needs_a_server(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("BOOTH_SERVER", raising=False)
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    assert main(["pair"]) == 1
    assert "--server" in capsys.readouterr().err


def test_run_needs_pairing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    assert main(["run"]) == 1
    assert "booth pair" in capsys.readouterr().err


def test_index_needs_plex_settings(monkeypatch, capsys):
    monkeypatch.delenv("PLEX_URL", raising=False)
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    assert main(["index"]) == 1
    assert "PLEX_URL" in capsys.readouterr().err
