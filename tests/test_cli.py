import os
import sys

import pytest

from radiobooth import __version__, cli
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


def test_name_window_titles_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli.name_window(platform="darwin")
    assert capsys.readouterr().out == "\033]0;Radio Booth\007"


def test_name_window_leaves_pipes_alone(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    cli.name_window(platform="linux")
    assert capsys.readouterr().out == ""


def test_name_window_never_fails_on_windows():
    cli.name_window(platform="win32")  # no ctypes.windll here: quietly does nothing


def test_a_mac_checks_https_against_its_own_certificates(monkeypatch, tmp_path):
    import ssl
    from types import SimpleNamespace

    bundle = tmp_path / "cert.pem"
    bundle.write_text("certificates")
    monkeypatch.setattr(cli, "MAC_CERTIFICATES", str(bundle))
    for var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):  # set first, so the test's own change is undone after
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: SimpleNamespace(cafile=None, capath=None))
    cli.use_system_certificates("linux")
    assert "SSL_CERT_FILE" not in os.environ
    cli.use_system_certificates("darwin")
    assert os.environ["SSL_CERT_FILE"] == str(bundle)


def test_a_mac_with_working_certificates_is_left_alone(monkeypatch):
    import ssl
    from types import SimpleNamespace

    for var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):  # set first, so the test's own change is undone after
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    found = SimpleNamespace(cafile="/opt/homebrew/etc/openssl@3/cert.pem", capath=None)
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: found)
    cli.use_system_certificates("darwin")
    assert "SSL_CERT_FILE" not in os.environ
