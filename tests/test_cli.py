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


def test_pair_uses_the_same_server_as_setup(monkeypatch, tmp_path):
    from radiobooth import cli
    from radiobooth.link import Link

    monkeypatch.delenv("BOOTH_SERVER", raising=False)
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    seen = []
    monkeypatch.setattr(Link, "redeem", lambda self, code, name: seen.append(self.server) or "be_x")
    assert main(["pair", "ABCD-2345"]) == 0
    assert seen == [cli.DEFAULT_SERVER.rstrip("/")]


def test_run_needs_pairing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    from radiobooth import cli

    assert main(["run"]) == cli.NEEDS_PAIRING
    assert "booth pair" in capsys.readouterr().err


def test_index_needs_plex_settings(monkeypatch, capsys):
    monkeypatch.delenv("PLEX_URL", raising=False)
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    assert main(["index"]) == 1
    assert "PLEX_URL" in capsys.readouterr().err
