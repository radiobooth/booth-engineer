import pytest

from radiobooth import __version__
from radiobooth.cli import COMMANDS, main


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "booth" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_unbuilt_commands_exit_nonzero(command):
    assert main([command]) == 2
