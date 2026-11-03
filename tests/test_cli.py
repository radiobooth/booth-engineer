import pytest

from radiobooth import __version__
from radiobooth.cli import UNBUILT, main


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "booth" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("command", sorted(UNBUILT))
def test_unbuilt_commands_exit_nonzero(command):
    assert main([command]) == 2


def test_index_needs_plex_settings(monkeypatch, capsys):
    monkeypatch.delenv("PLEX_URL", raising=False)
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    assert main(["index"]) == 1
    assert "PLEX_URL" in capsys.readouterr().err
