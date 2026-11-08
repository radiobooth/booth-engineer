"""The Mac app, Radio Booth.app, with the On Air icon. It has no window of its own: Booth shows its page in
the browser (see `web`).

Inside the app, `Contents/MacOS/Radio Booth` is a small launcher that starts the Booth program built for this
Mac's chip (Apple silicon or Intel). Opened from Finder, Launchpad or Spotlight, Booth first puts itself in an
Applications folder: a downloaded app runs from a temporary, read-only copy until it's moved (macOS calls this
app translocation), and starting at sign-in and updating need a place that lasts. The copy carries no
download mark, so macOS asks about it only once.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = "Radio Booth.app"
LAUNCHER = "Radio Booth"  # Contents/MacOS/Radio Booth
BUNDLE_ID = "com.radiobooth.engineer"


def bundle(exe: str | Path) -> Path | None:
    """The .app this program runs from, if it does."""
    p = Path(exe)
    if p.parent.name == "MacOS" and p.parent.parent.name == "Contents" and p.parents[2].suffix == ".app":
        return p.parents[2]
    return None


def launcher(app: Path) -> Path:
    return app / "Contents" / "MacOS" / LAUNCHER


def folders(home: Path) -> list[Path]:
    """Applications folders, best first: the shared one (any admin can add to it), then the user's own."""
    return [Path("/Applications"), home / "Applications"]


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def place(app: Path, home: Path, choices: list[Path] | None = None) -> Path:
    """Where the app should live: where it is, if that's already an Applications folder, else the first one
    this user can add to."""
    choices = choices if choices is not None else folders(home)
    if any(_same(app.parent, folder) for folder in choices):
        return app
    for folder in choices:
        if folder.is_dir() and os.access(folder, os.W_OK):
            return folder / APP
    return choices[-1] / APP  # the user's own; made on the way in


def install(app: Path, home: Path, choices: list[Path] | None = None) -> Path:
    """Put the app in an Applications folder (replacing an older copy there) and return where it is."""
    target = place(app, home, choices)
    if _same(app, target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    swap(app, target)
    return target


def swap(app: Path, target: Path) -> None:
    """Copy `app` over `target`, so that a failure never leaves a broken app behind."""
    staged, old = target.with_name(f".{APP}.new"), target.with_name(f".{APP}.old")
    for leftover in (staged, old):
        shutil.rmtree(leftover, ignore_errors=True)
    # A full copy first. Python's copy on a Mac copies the files and their permissions but not the download
    # mark (quarantine), so this copy opens without asking.
    try:
        shutil.copytree(app, staged, symlinks=True)
        if target.exists():
            target.rename(old)  # a running Booth keeps going: it was unpacked when it started
        staged.rename(target)
    except OSError:
        shutil.rmtree(staged, ignore_errors=True)
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def opened_from_finder(argv: list[str], platform: str = sys.platform) -> bool:
    """True for the app opened from Finder, Launchpad, Spotlight or the Dock: nothing typed, no window."""
    if platform != "darwin" or argv or not getattr(sys, "frozen", False) or bundle(sys.executable) is None:
        return False
    return sys.stdin is None or not sys.stdin.isatty()


def agent_plist(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"


def open_app(
    exe: str | Path, home: Path | None = None, run=subprocess.run, popen=subprocess.Popen
) -> int | None:
    """Opened from Finder: move the app into Applications first. Returns None to carry on in this process (the
    app was already there), or an exit code after handing over to the copy in Applications."""
    app = bundle(exe)
    if app is None:
        return None
    home = home or Path.home()
    try:
        placed = install(app, home)
    except OSError:
        return None  # Applications can't be written to: run this copy as it is
    if placed == app:
        return None
    if agent_plist(home).exists():
        # A newer download just replaced the app: point the Booth that starts at sign-in at it (an older
        # version's sign-in item may start Booth differently) and restart it, so it's this one.
        from radiobooth import autostart

        with contextlib.suppress(OSError):
            autostart.install("darwin", home, run=run, cmd=[str(launcher(placed))])
    # The copy in Applications opens Booth's page (or finds the Booth already running and opens its page).
    popen([str(launcher(placed)), "app"], start_new_session=True, close_fds=True)
    return 0
