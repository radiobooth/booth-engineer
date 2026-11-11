import os
import sys
from pathlib import Path

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


def test_the_app_command_starts_booths_page(monkeypatch):
    from radiobooth import web

    seen = []
    monkeypatch.setattr(web, "main", lambda name, background, wait: seen.append((background, wait)) or 0)
    assert main(["app", "--background"]) == 0 and seen == [(True, False)]


def test_the_double_clicked_app_opens_booths_page(monkeypatch):
    from radiobooth import macapp

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["RadioBooth.exe"])
    monkeypatch.setattr(macapp, "opened_from_finder", lambda argv: False)
    monkeypatch.setattr(cli, "windows_home", lambda: None)
    seen = []
    monkeypatch.setattr(cli, "dispatch", lambda argv: seen.append(argv) or 0)
    assert main() == 0 and seen == [["app"]]


def test_without_a_console_messages_go_to_a_log_file(monkeypatch, tmp_path):
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(cli, "NO_CONSOLE", False)  # put back after
    cli.without_console()
    assert cli.NO_CONSOLE
    print("hello from the Windows app", file=sys.stderr)
    sys.stderr.flush()
    assert "hello from the Windows app" in (tmp_path / "booth.log").read_text()
    sys.stderr.close()


def test_the_windows_app_moves_into_its_own_folder_and_starts_there(monkeypatch, tmp_path):
    exe = tmp_path / "Downloads" / "RadioBooth-Windows.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ app")
    monkeypatch.setenv("BOOTH_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)
    started = []
    assert cli.windows_home("win32", popen=lambda args, **k: started.append(args)) == 0
    home = tmp_path / "Local" / "Radio Booth" / "RadioBooth.exe"
    assert started == [[str(home)]] and home.read_bytes() == b"MZ app"
    monkeypatch.setattr(sys, "executable", str(home))
    assert cli.windows_home("win32", popen=lambda args, **k: started.append(args)) is None  # already there
    assert cli.windows_home("darwin") is None


def test_versions_agree():
    """Release tags are checked against pyproject.toml; the app and its notices report __version__."""
    import tomllib

    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__


def test_license_shows_the_gpl(capsys):
    assert cli.main(["license"]) == 0
    out = capsys.readouterr().out
    assert "Thomas Bohmbach, Jr." in out and "NO WARRANTY" in out and "GNU GENERAL PUBLIC LICENSE" in out


def test_license_inside_the_app_says_it_once(tmp_path, monkeypatch, capsys):
    (tmp_path / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE\n")
    (tmp_path / "NOTICES.txt").write_text("Radio Booth 0.3.0\nCopyright\n")
    monkeypatch.setattr(cli.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert cli.main(["license"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Radio Booth 0.3.0") and out.count("Copyright") == 1 and "GNU GENERAL" in out


def test_license_without_a_console_opens_a_file(tmp_path, monkeypatch, capsys):
    """The Windows app has no console: the text opens in a viewer instead of vanishing into the log."""
    from radiobooth import config

    monkeypatch.setattr(config, "path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(cli, "NO_CONSOLE", True)
    opened = []
    assert cli.license_(None, opener=opened.append) == 0
    assert capsys.readouterr().out == ""
    assert "GNU GENERAL PUBLIC LICENSE" in Path(opened[0]).read_text(encoding="utf-8")
