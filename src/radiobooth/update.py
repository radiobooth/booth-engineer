"""Keep the Booth app up to date by itself, from this project's GitHub releases.

Every few hours the app asks GitHub for the latest release (a plain request: nothing about you or your music
is sent). When there's a newer version, and Booth isn't in the middle of a show, it downloads the file for
this computer, checks it against the release's SHA256SUMS, swaps it in and starts again. A file Booth
downloads itself carries no "downloaded from the internet" mark, so Windows and macOS don't ask again.

Only the double-click apps update themselves. The `booth` command (uv) and the Docker image are updated the
way they were installed; for those the Booth page only says that a new version is out.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from radiobooth import __version__, macapp

REPO = "radiobooth/booth-engineer"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
SUMS = "SHA256SUMS"
ASSETS = {"win32": "RadioBooth-Windows.exe", "darwin": "RadioBooth-macOS.zip"}
CHECK_EVERY_S = 6 * 3600
FIRST_CHECK_S = 60
USER_AGENT = f"radiobooth/{__version__}"


class UpdateError(Exception):
    pass


def version_tuple(text: str) -> tuple[int, ...] | None:
    """(0, 2, 1) for "v0.2.1" or "0.2.1"; None for anything else (a pre-release, a typo)."""
    text = text.strip().removeprefix("v")
    parts = text.split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def newer(latest: str, current: str = __version__) -> bool:
    a, b = version_tuple(latest), version_tuple(current)
    return a is not None and b is not None and a > b


def fetch(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"couldn't reach GitHub ({getattr(e, 'reason', e)})") from None


def latest_release(get: Callable[[str], bytes] = fetch) -> dict:
    """{"version", "assets": {name: download url}} for the newest published (not pre-) release."""
    try:
        data = json.loads(get(LATEST))
    except ValueError:
        raise UpdateError("GitHub sent something that isn't a release") from None
    if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str):
        raise UpdateError("GitHub sent something that isn't a release")
    assets = {}
    for a in data.get("assets") or []:
        url = a.get("browser_download_url") if isinstance(a, dict) else None
        # Only files on this project's own release pages, over https.
        if isinstance(url, str) and url.startswith(DOWNLOADS) and isinstance(a.get("name"), str):
            assets[a["name"]] = url
    return {"version": data["tag_name"].removeprefix("v"), "assets": assets}


def parse_sums(text: str) -> dict[str, str]:
    """`sha256sum` output: {file name: hex digest}."""
    found = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and len(parts[0]) == 64:
            found[parts[1].lstrip("*")] = parts[0].lower()
    return found


def download(url: str, dest: Path, expected: str, timeout: float = 120) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as f:
            while chunk := resp.read(1 << 16):
                digest.update(chunk)
                f.write(chunk)
    except (urllib.error.URLError, TimeoutError) as e:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"the download failed ({getattr(e, 'reason', e)})") from None
    if digest.hexdigest() != expected:
        dest.unlink(missing_ok=True)
        raise UpdateError("the download didn't match the release's checksum, so it wasn't used")


def installed(platform: str = sys.platform, exe: str | None = None) -> Path | None:
    """What an update replaces: the Windows app file, or the Mac app. None if this isn't the app."""
    if not getattr(sys, "frozen", False) or platform not in ASSETS:
        return None
    exe = exe or sys.executable
    if platform == "darwin":
        return macapp.bundle(exe)
    return Path(exe)


def swap_windows(new: Path, exe: Path) -> None:
    """Windows lets a running program's file be renamed, not replaced: move it aside, put the new one in."""
    old = exe.with_name(exe.stem + ".old" + exe.suffix)
    old.unlink(missing_ok=True)
    os.replace(exe, old)
    try:
        os.replace(new, exe)
    except OSError:
        os.replace(old, exe)
        raise


def swap_mac(zip_file: Path, app: Path, run=subprocess.run) -> None:
    """Unpack the downloaded app next to the running one and swap it in."""
    with tempfile.TemporaryDirectory(dir=app.parent, prefix=".booth-update-") as tmp:
        done = run(["ditto", "-x", "-k", str(zip_file), tmp], capture_output=True)
        unpacked = Path(tmp) / macapp.APP
        if getattr(done, "returncode", 1) or not macapp.launcher(unpacked).is_file():
            raise UpdateError("the downloaded app couldn't be unpacked")
        macapp.swap(unpacked, app)


def tidy(platform: str = sys.platform) -> None:
    """Remove what the last update moved aside (Windows can't delete a running program's file)."""
    target = installed(platform)
    if target and platform == "win32":
        with contextlib.suppress(OSError):
            target.with_name(target.stem + ".old" + target.suffix).unlink(missing_ok=True)


def apply(
    release: dict, platform: str = sys.platform, get=fetch, fetch_file=download, run=subprocess.run
) -> str:
    """Download, check and install `release`; returns the new version. Raises UpdateError."""
    target = installed(platform)
    name = ASSETS.get(platform)
    if target is None or name is None:
        raise UpdateError("this copy of Booth doesn't update itself")
    url, sums_url = release["assets"].get(name), release["assets"].get(SUMS)
    if not url or not sums_url:
        raise UpdateError(f"version {release['version']} has no checked download for this computer")
    expected = parse_sums(get(sums_url).decode("utf-8", "replace")).get(name)
    if not expected:
        raise UpdateError(f"version {release['version']} has no checksum for {name}")
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".booth-download-") as tmp:
        dest = Path(tmp) / name
        fetch_file(url, dest, expected)
        if platform == "win32":
            swap_windows(dest, target)
        else:
            swap_mac(dest, target, run)
    return release["version"]


def restart_command(platform: str = sys.platform, exe: str | None = None) -> list[str]:
    """How to start the updated app again, in the background (the Booth page reconnects by itself)."""
    exe = exe or sys.executable
    if platform == "darwin" and (app := macapp.bundle(exe)):
        exe = str(macapp.launcher(app))
    return [exe, "app", "--background", "--wait"]


def relaunch(platform: str = sys.platform, popen=subprocess.Popen, run=subprocess.run) -> None:
    """Start the new version; the caller then exits. Under launchd, launchd restarts Booth itself."""
    if platform == "darwin" and os.environ.get("XPC_SERVICE_NAME") == macapp.BUNDLE_ID:
        run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{macapp.BUNDLE_ID}"])
        return
    kwargs: dict = {"close_fds": True}
    if platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    popen(restart_command(platform), **kwargs)


class Updater:
    """Checks now and then; installs when Booth is idle. What it's doing is in `status()` for the page."""

    def __init__(self, busy: Callable[[], bool], restart: Callable[[], None], auto: Callable[[], bool]):
        self._busy, self._restart, self._auto = busy, restart, auto
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self.can_install = installed() is not None
        self.latest: str | None = None
        self.checked_at: float | None = None
        self.state = "idle"  # idle | checking | available | installing | failed
        self.message = ""
        self._release: dict | None = None

    def status(self) -> dict:
        return {
            "current": __version__,
            "latest": self.latest,
            "available": bool(self.latest and newer(self.latest)),
            "can_install": self.can_install,
            "state": self.state,
            "message": self.message,
            "checked_at": self.checked_at,
        }

    def start(self) -> None:
        threading.Thread(target=self._loop, name="booth-updates", daemon=True).start()

    def check_now(self) -> None:
        self._wake.set()

    def install_now(self) -> None:
        threading.Thread(target=self._install, name="booth-update-now", daemon=True).start()

    def check(self) -> None:
        self.state, self.message = "checking", ""
        try:
            release = latest_release()
        except UpdateError as e:
            self.state, self.message = "failed", f"Couldn't check for updates: {e}."
            return
        self.checked_at = time.time()
        self.latest = release["version"]
        if newer(self.latest):
            self._release = release
            self.state = "available"
        else:
            self.state = "idle"

    def _install(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._release is None:
                self.check()
            if self._release is None or not newer(self._release["version"]):
                return
            self.state, self.message = "installing", f"Installing version {self._release['version']}..."
            try:
                apply(self._release)
            except (UpdateError, OSError) as e:
                self.state, self.message = "failed", f"Couldn't install the update: {e}."
                return
            self.message = f"Version {self._release['version']} installed; Booth is starting again."
            self._restart()
        finally:
            self._lock.release()

    def _loop(self) -> None:
        tidy()
        wait = FIRST_CHECK_S
        while True:
            self._wake.wait(wait)
            self._wake.clear()
            self.check()
            wait = CHECK_EVERY_S
            # Install when nothing's on its way into Plex; check again in a minute if something is.
            while self.state == "available" and self.can_install and self._auto():
                if not self._busy():
                    self._install()
                    break
                time.sleep(60)
