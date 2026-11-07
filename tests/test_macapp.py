import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

from radiobooth import autostart, cli, macapp


def make_app(where: Path, body: bytes = b"booth") -> Path:
    app = where / "Radio Booth.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    for name in ("Radio Booth", "booth-arm64"):
        exe = app / "Contents" / "MacOS" / name
        exe.write_bytes(body)
        exe.chmod(0o755)
    (app / "Contents" / "Info.plist").write_bytes(b"<plist/>")
    return app


def test_the_app_knows_its_bundle(tmp_path):
    app = make_app(tmp_path)
    assert macapp.bundle(app / "Contents" / "MacOS" / "booth-arm64") == app
    assert macapp.bundle(tmp_path / "Downloads" / "booth") is None


def test_a_downloaded_app_moves_into_applications(tmp_path):
    app = make_app(tmp_path / "Downloads")
    shared, own = tmp_path / "Applications", tmp_path / "home" / "Applications"
    shared.mkdir()
    placed = macapp.install(app, tmp_path / "home", [shared, own])
    assert placed == shared / "Radio Booth.app"
    exe = placed / "Contents" / "MacOS" / "Radio Booth"
    assert exe.read_bytes() == b"booth"
    assert sys.platform == "win32" or exe.stat().st_mode & 0o111  # still runs
    assert sorted(p.name for p in shared.iterdir()) == ["Radio Booth.app"]  # nothing left over


def test_without_a_shared_applications_folder_it_uses_the_users_own(tmp_path):
    app = make_app(tmp_path / "Downloads")
    own = tmp_path / "home" / "Applications"
    assert macapp.install(app, tmp_path / "home", [tmp_path / "nope", own]) == own / "Radio Booth.app"


def test_a_newer_download_replaces_the_app(tmp_path):
    apps = tmp_path / "Applications"
    make_app(apps, b"old")
    new = make_app(tmp_path / "Downloads", b"new")
    placed = macapp.install(new, tmp_path, [apps])
    assert (placed / "Contents" / "MacOS" / "Radio Booth").read_bytes() == b"new"
    assert sorted(p.name for p in apps.iterdir()) == ["Radio Booth.app"]


def test_an_app_already_in_applications_stays_put(tmp_path):
    apps = tmp_path / "Applications"
    app = make_app(apps)
    assert macapp.install(app, tmp_path, [apps]) == app


def test_opened_from_finder_it_opens_terminal_on_the_installed_app(tmp_path, monkeypatch):
    app = make_app(tmp_path / "Downloads")
    monkeypatch.setattr(macapp, "folders", lambda home: [tmp_path / "Applications"])
    ran = []
    code = macapp.open_in_terminal(
        app / "Contents" / "MacOS" / "booth-arm64",
        tmp_path,
        run=lambda a: ran.append(a) or SimpleNamespace(returncode=0),
    )
    assert code == 0
    assert ran == [
        ["open", "-a", "Terminal", str(tmp_path / "Applications/Radio Booth.app/Contents/MacOS/Radio Booth")]
    ]


def test_only_the_mac_app_opened_without_a_window_hands_over(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "Contents" / "MacOS" / "booth-arm64"))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert macapp.opened_from_finder([], "darwin")
    assert not macapp.opened_from_finder(["run"], "darwin")  # started at sign-in
    assert not macapp.opened_from_finder([], "win32")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    assert not macapp.opened_from_finder([], "darwin")  # already in Terminal


def test_the_main_entry_opens_terminal_for_the_mac_app(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["booth-arm64"])
    monkeypatch.setattr(macapp, "opened_from_finder", lambda argv: True)
    monkeypatch.setattr(macapp, "open_in_terminal", lambda exe: 7)
    assert cli.main() == 7


def test_starting_at_sign_in_uses_the_app_in_applications(tmp_path, monkeypatch):
    app = make_app(tmp_path / "Downloads")
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(macapp, "folders", lambda home: [apps])
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart, "command", lambda: [str(app / "Contents" / "MacOS" / "booth-arm64")])
    legacy = tmp_path / "Library" / "Application Support" / "Radio Booth" / "Radio Booth"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"the old .command download")
    (legacy.parent / "breaks").mkdir()

    said = autostart.install("darwin", tmp_path, run=lambda *a, **k: None)
    assert "Applications" in said
    plist = plistlib.loads((tmp_path / "Library/LaunchAgents/com.radiobooth.engineer.plist").read_bytes())
    assert plist["ProgramArguments"] == [str(apps / "Radio Booth.app/Contents/MacOS/Radio Booth"), "run"]
    assert plist["AssociatedBundleIdentifiers"] == ["com.radiobooth.engineer"]
    assert not legacy.exists() and (legacy.parent / "breaks").is_dir()  # only the old program goes


def test_the_app_bundle_is_put_together(tmp_path):
    sys.path.insert(0, str(Path(__file__).parent.parent / "packaging"))
    try:
        import mac_app
    finally:
        sys.path.pop(0)
    parts = []
    for name in ("launcher", "arm64", "x86_64"):
        (tmp_path / name).write_bytes(name.encode())
        parts.append(tmp_path / name)
    app = mac_app.build(tmp_path / "dist", *parts, "0.1.3")
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == macapp.LAUNCHER and info["CFBundleIdentifier"] == macapp.BUNDLE_ID
    assert info["CFBundleShortVersionString"] == "0.1.3"
    macos = app / "Contents" / "MacOS"
    assert (macos / "Radio Booth").read_bytes() == b"launcher"
    assert sys.platform == "win32" or (macos / "booth-x86_64").stat().st_mode & 0o111
    assert (app / "Contents" / "Resources" / "booth.icns").read_bytes()[:4] == b"icns"


def test_an_update_restarts_the_booth_that_starts_at_sign_in(tmp_path, monkeypatch):
    app = make_app(tmp_path / "Downloads", b"new")
    make_app(tmp_path / "Applications", b"old")
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.radiobooth.engineer.plist").write_text("<plist/>")
    monkeypatch.setattr(macapp, "folders", lambda home: [tmp_path / "Applications"])
    monkeypatch.setattr(macapp.os, "getuid", lambda: 501, raising=False)
    ran = []
    macapp.open_in_terminal(
        app / "Contents" / "MacOS" / "booth-arm64",
        tmp_path,
        run=lambda a: ran.append(a) or SimpleNamespace(returncode=0),
    )
    assert ran[0] == ["launchctl", "kickstart", "-k", "gui/501/com.radiobooth.engineer"]
    assert ran[1][:3] == ["open", "-a", "Terminal"]
