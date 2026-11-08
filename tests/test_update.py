import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from radiobooth import update

D = update.DOWNLOADS + "v0.2.1/"


def release_json(tag="v0.2.1", extra=()):
    assets = [
        {"name": "RadioBooth-Windows.exe", "browser_download_url": D + "RadioBooth-Windows.exe"},
        {"name": "RadioBooth-macOS.zip", "browser_download_url": D + "RadioBooth-macOS.zip"},
        {"name": "SHA256SUMS", "browser_download_url": D + "SHA256SUMS"},
        *extra,
    ]
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


def test_versions_compare_as_numbers():
    assert update.newer("0.10.0", "0.9.9") and update.newer("v0.2.0", "0.1.4")
    assert not update.newer("0.1.4", "0.1.4") and not update.newer("0.1.3", "0.1.4")
    assert not update.newer("0.2.0-rc1", "0.1.4") and not update.newer("nonsense", "0.1.4")


def test_only_this_projects_own_downloads_are_used():
    evil = {"name": "RadioBooth-Windows.exe", "browser_download_url": "https://evil.example/booth.exe"}
    got = update.latest_release(lambda url: release_json(extra=[evil]))
    assert got["version"] == "0.2.1"
    assert got["assets"]["RadioBooth-Windows.exe"] == D + "RadioBooth-Windows.exe"
    with pytest.raises(update.UpdateError):
        update.latest_release(lambda url: b"<html>captive portal</html>")


def test_checksums_are_read_like_sha256sum_writes_them():
    sums = update.parse_sums(
        "a" * 64 + "  RadioBooth-Windows.exe\n" + "b" * 64 + " *RadioBooth-macOS.zip\njunk\n"
    )
    assert sums == {"RadioBooth-Windows.exe": "a" * 64, "RadioBooth-macOS.zip": "b" * 64}


def frozen_windows_app(tmp_path, monkeypatch, body=b"MZ old"):
    exe = tmp_path / "Radio Booth" / "RadioBooth.exe"
    exe.parent.mkdir()
    exe.write_bytes(body)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    return exe


def test_a_windows_update_swaps_the_app_file(tmp_path, monkeypatch):
    exe = frozen_windows_app(tmp_path, monkeypatch)
    new = b"MZ new"
    sums = f"{hashlib.sha256(new).hexdigest()}  RadioBooth-Windows.exe\n".encode()
    release = update.latest_release(lambda url: release_json())

    def fetch_file(url, dest, expected):
        assert url == D + "RadioBooth-Windows.exe"
        dest.write_bytes(new)
        assert hashlib.sha256(new).hexdigest() == expected

    assert update.apply(release, "win32", get=lambda url: sums, fetch_file=fetch_file) == "0.2.1"
    assert exe.read_bytes() == new
    old = exe.with_name("RadioBooth.old.exe")
    assert old.read_bytes() == b"MZ old"
    update.tidy("win32")
    assert not old.exists()


def test_a_release_without_a_checksum_is_not_installed(tmp_path, monkeypatch):
    exe = frozen_windows_app(tmp_path, monkeypatch)
    release = update.latest_release(lambda url: release_json())
    with pytest.raises(update.UpdateError, match="no checksum"):
        update.apply(release, "win32", get=lambda url: b"", fetch_file=pytest.fail)
    release["assets"].pop("SHA256SUMS")
    with pytest.raises(update.UpdateError, match="no checked download"):
        update.apply(release, "win32", get=pytest.fail, fetch_file=pytest.fail)
    assert exe.read_bytes() == b"MZ old"


def test_a_download_that_doesnt_match_is_thrown_away(tmp_path, monkeypatch):
    payload = b"tampered"

    class Resp:
        def __init__(self):
            self.chunks = [payload, b""]

        def read(self, n):
            return self.chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout: Resp())
    dest = tmp_path / "RadioBooth-Windows.exe"
    with pytest.raises(update.UpdateError, match="checksum"):
        update.download(D + "RadioBooth-Windows.exe", dest, "0" * 64)
    assert not dest.exists()
    update.download(D + "RadioBooth-Windows.exe", dest, hashlib.sha256(payload).hexdigest())
    assert dest.read_bytes() == payload


def test_a_mac_update_swaps_the_whole_app(tmp_path, monkeypatch):
    from test_macapp import make_app

    app = make_app(tmp_path / "Applications", b"old")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "Contents" / "MacOS" / "booth-arm64"))
    zip_file = tmp_path / "RadioBooth-macOS.zip"
    zip_file.write_bytes(b"zip")

    def ditto(args, **k):  # stands in for unpacking the zip
        assert args[:3] == ["ditto", "-x", "-k"]
        make_app(Path(args[-1]), b"new")
        return SimpleNamespace(returncode=0)

    update.swap_mac(zip_file, app, run=ditto)
    assert (app / "Contents" / "MacOS" / "booth-arm64").read_bytes() == b"new"
    assert sorted(p.name for p in app.parent.iterdir()) == ["Radio Booth.app"]  # nothing left behind


def test_only_the_apps_update_themselves(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert update.installed("win32") is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert update.installed("linux") is None


def test_restarting_starts_the_new_version_in_the_background(monkeypatch, tmp_path):
    started = []
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Radio Booth\RadioBooth.exe")
    update.relaunch("win32", popen=lambda args, **k: started.append((args, k)))
    ((args, kwargs),) = started
    assert args == [r"C:\Radio Booth\RadioBooth.exe", "app", "--background", "--wait"]
    assert kwargs["creationflags"]
    # Its own unpacked files, not the old version's (which go when the old version exits).
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and kwargs["env"][update.FRESH] == "1"

    ran = []
    monkeypatch.setenv("XPC_SERVICE_NAME", "com.radiobooth.engineer")
    monkeypatch.setattr(update.os, "getuid", lambda: 501, raising=False)
    update.relaunch("darwin", popen=pytest.fail, run=lambda args: ran.append(args))
    assert ran == [["launchctl", "kickstart", "-k", "gui/501/com.radiobooth.engineer"]]


def test_a_version_started_by_an_older_update_starts_again_afresh(monkeypatch):
    from radiobooth import cli

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv(update.FRESH, raising=False)
    argv = ["RadioBooth.exe", "app", "--background", "--wait"]
    assert update.started_by_old_update(argv)
    assert not update.started_by_old_update(["RadioBooth.exe", "app", "--background"])  # sign-in start
    relaunched = []
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(update, "relaunch", lambda *a, **k: relaunched.append(1))
    assert cli.app(cli.build_parser().parse_args(argv[1:])) == 0 and relaunched == [1]
    monkeypatch.setenv(update.FRESH, "1")  # started by relaunch() from now on: carries on
    assert not update.started_by_old_update(argv)
