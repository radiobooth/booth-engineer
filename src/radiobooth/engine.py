"""Booth Engineer's work, the same for `booth run` and the app: check in with Booth DJ, read the library
when a show asks for it, deliver finished shows into Plex.

`station` builds what the link loop needs from the saved settings. `Engine` runs that loop in the background
for the app, and keeps what its Booth page shows: whether Booth is connected, what it did lately, and what
only setup can fix.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from radiobooth import config, history, plexshare
from radiobooth.link import Link, LinkError, Station
from radiobooth.link import run_all as run_desks
from radiobooth.sources import folder as folder_source
from radiobooth.sources import plex as plex_source
from radiobooth.sources.plex import PlexAuthError, PlexClient
from radiobooth.targets import playlist as playlist_target
from radiobooth.targets import plex as plex_target


def setting(settings: dict, env: str, key: str) -> str | None:
    """The environment wins over the config file."""
    return os.environ.get(env) or settings.get(key) or None


def delivery_settings(settings: dict) -> tuple[dict, list[str]]:
    """What delivering into Plex needs, and the names of what's missing."""
    found = {
        "url": setting(settings, "PLEX_URL", "plex_url"),
        "token": setting(settings, "PLEX_TOKEN", "plex_token"),
        "library": setting(settings, "BOOTH_BREAKS_LIBRARY", "breaks_library"),
        "dest": setting(settings, "BOOTH_BREAKS_DIR", "breaks_dir"),
    }
    names = {
        "url": "PLEX_URL",
        "token": "PLEX_TOKEN",
        "library": "BOOTH_BREAKS_LIBRARY",
        "dest": "BOOTH_BREAKS_DIR",
    }
    return found, [names[k] for k, v in found.items() if not v]


def folder_mode(settings: dict) -> bool:
    """Music from a plain folder, shows as playlist files (not Plex)."""
    return setting(settings, "BOOTH_SOURCE", "music_source") == "folder"


def folder_settings(settings: dict) -> tuple[dict, list[str]]:
    """What making shows from a music folder needs, and the names of what's missing."""
    found = {
        "music": setting(settings, "BOOTH_MUSIC_FOLDER", "music_folder"),
        "shows": setting(settings, "BOOTH_SHOWS_FOLDER", "shows_folder"),
    }
    names = {"music": "BOOTH_MUSIC_FOLDER", "shows": "BOOTH_SHOWS_FOLDER"}
    return found, [names[k] for k, v in found.items() if not v]


def needs(settings: dict) -> tuple[dict, list[str], list[str]]:
    """For whichever kind of setup this is: its settings, what's missing, and the folders it needs."""
    if folder_mode(settings):
        found, missing = folder_settings(settings)
        return found, missing, [found["music"], found["shows"]]
    found, missing = delivery_settings(settings)
    return found, missing, [found["dest"]]


def read_folder(settings: dict, on_scan: Callable | None = None) -> dict:
    """The music folder's catalog (the index brought up to date). `on_scan(done, total)` hears how reading
    it goes, then `on_scan(report)` gets the tag report, or `on_scan(None)` if reading failed."""
    found, _ = folder_settings(settings)
    try:
        built, report = folder_source.build_catalog(
            found["music"],
            settings.get("library_name") or "Music",
            config.folder_key(),
            config.path().parent,
            skip=[Path(found["shows"]).expanduser()],
            progress=on_scan,
        )
    except BaseException:
        if on_scan:
            on_scan(None)
        raise
    if on_scan:
        on_scan(report)
    return built


def remember(show_dir: Path, log: Callable[[str], None], person: str | None = None) -> None:
    """Note a delivered show's tracks so later shows skip them. Never fails the delivery."""
    try:
        package = json.loads((show_dir / "show.json").read_text(encoding="utf-8"))
        history.record_package(package, person=person)
    except Exception as e:
        log(f"Couldn't update the show history ({e}); later shows may repeat these tracks.")


def station(
    settings: dict,
    log: Callable[[str], None],
    music: str | None = None,
    on_plex_refused: Callable[[], None] | None = None,
    busy: Callable[[bool], None] | None = None,
    on_delivered: Callable[[str], None] | None = None,
    person: dict | None = None,
    on_scan: Callable | None = None,
    reading: Callable[[], dict | None] | None = None,
) -> Station:
    """The link loop's view of this machine, from saved settings (and the environment, which wins).
    `person`: another person sharing this Booth (see config.people), with their own show history and their
    name before their playlists' titles; their shows go into the same Plex, with this computer's sign-in."""
    who = person["id"] if person else None
    prefix = f"{person['name']}: " if person else ""
    if folder_mode(settings):
        return folder_station(settings, log, busy, on_delivered, who, prefix, on_scan, reading)
    share_with = person.get("plex_user") if person else None
    found, _ = delivery_settings(settings)
    plex = PlexClient(found["url"], found["token"])
    library, dest = found["library"], Path(found["dest"])
    music = music or setting(settings, "BOOTH_MUSIC_LIBRARY", "music_library")
    mark = busy or (lambda on: None)

    def signed_in(step):
        """`step()`, and if Plex refuses the sign-in, once more with a newer one saved since Booth started
        (setup run again in another window). Without one, the refusal stands: only signing in fixes it."""
        try:
            return step()
        except PlexAuthError as e:
            # The saved sign-in, even when PLEX_URL/PLEX_TOKEN are set: a token exported in this shell
            # outlives the one setup just saved.
            saved = config.load()
            saved_url = saved.get("plex_url") or plex.base_url
            saved_token = saved.get("plex_token")
            if not saved_token or (saved_url.rstrip("/"), saved_token) == (plex.base_url, plex.token):
                if on_plex_refused:
                    on_plex_refused()
                if os.environ.get("PLEX_TOKEN"):
                    raise PlexAuthError(
                        f"{e} PLEX_TOKEN is set here and wins over setup's: unset it."
                    ) from None
                raise
            plex.base_url, plex.token = saved_url.rstrip("/"), saved_token
            log("Plex refused the sign-in Booth started with; using the one saved by setup.")
            return step()

    def catalog() -> dict:
        mark(True)
        try:
            return history.annotate(
                signed_in(lambda: plex_source.build_catalog(plex, music, exclude=library)[0]), who
            )
        finally:
            mark(False)

    def deliver_show(show_dir: Path) -> str:
        mark(True)
        try:
            done = signed_in(lambda: plex_target.deliver(plex, show_dir, library, dest, prefix=prefix))
            title = done.title
            remember(show_dir, log, who)
            if share_with:
                share(done, share_with)
            if on_delivered:
                on_delivered(title)
            return title
        finally:
            mark(False)

    def share(done, user: dict) -> None:
        """Share a person's new playlist with their Plex user. The show is in Plex either way, so a problem
        here is logged, not a failed delivery."""
        try:
            client_id = config.plex_client_id()
            plexshare.share_playlist(
                plex.token, client_id, done.machine, done.playlist_key, done.title, user["id"]
            )
            log(f"Shared {done.title!r} with {user.get('title')!r} in Plex.")
        except Exception as e:
            log(
                f"Couldn't share {done.title!r} with {user.get('title')!r} in Plex ({e})."
                " Grant them access to it in Plex Web."
            )

    return Station(catalog=catalog, deliver=deliver_show, log=log)


class FolderBusy(Exception):
    """The music folder is being read in the background: ask again later."""


def folder_station(
    settings: dict,
    log: Callable[[str], None],
    busy: Callable[[bool], None] | None,
    on_delivered: Callable[[str], None] | None,
    who: str | None,
    prefix: str,
    on_scan: Callable | None = None,
    reading: Callable[[], dict | None] | None = None,
) -> Station:
    """`station` for music in a plain folder, delivered as playlist files (`on_scan`: see `read_folder`).
    `reading()`: how a read already under way in the background is going, or None."""
    found, _ = folder_settings(settings)
    shows = Path(found["shows"]).expanduser()
    home = config.path().parent
    mark = busy or (lambda on: None)

    def catalog() -> dict:
        # A first read of a big folder can take an hour. Waiting for it here would hold up every check-in
        # (and other shows' deliveries); this show is tried again at the next one instead.
        if reading and reading():  # the page shows how far it's got; the message stays the same, logged once
            raise FolderBusy("Booth is still reading your music folder; the show starts after that.")
        mark(True)
        try:
            return history.annotate(read_folder(settings, on_scan), who)
        finally:
            mark(False)

    def deliver_show(show_dir: Path) -> str:
        mark(True)
        try:
            music = folder_source.music_root(found["music"])
            index = folder_source.open_index(music, config.folder_key(), home)
            try:
                done = playlist_target.deliver(show_dir, shows, music, index.lookup, prefix=prefix)
            finally:
                index.close()
            if done.missing:
                log(f"Left {done.missing} tracks out of {done.title!r}: they're gone from the music folder.")
            remember(show_dir, log, who)
            if on_delivered:
                on_delivered(done.title)
            return done.title
        finally:
            mark(False)

    return Station(catalog=catalog, deliver=deliver_show, log=log)


def desks(
    settings: dict,
    log: Callable[[str], None],
    link_for: Callable[[str, str], Link],
    skip: set[str] = frozenset(),
    **station_args,
) -> tuple[list[tuple[Link, Station]], list[dict]]:
    """What `run_desks` checks in for: this computer's own Booth account first, then each other person
    sharing it (and the list of those people, in the same order), less those in `skip` (already known to be
    forgotten by their Booth account)."""
    people = [p for p in config.people(settings) if p["id"] not in skip]
    server = settings["server"]
    delivers_to = "playlist" if folder_mode(settings) else "plex"

    def link(token: str) -> Link:
        out = link_for(server, token)
        if isinstance(out, Link):  # so Booth DJ says where shows go: Plex, or the Booth shows folder
            out.delivers_to = delivers_to
        return out

    out = [(link(settings["device_token"]), station(settings, log, **station_args))]
    for p in people:

        def said(msg: str, name: str = p["name"]) -> None:
            log(f"{name}: {msg}")

        out.append((link(p["device_token"]), station(settings, said, person=p, **station_args)))
    return out, people


# What the Booth page says about the engine.
NOT_SET_UP, STARTING, ON_AIR, OFFLINE, NEEDS_PAIRING, NEEDS_PLEX, NEEDS_FOLDER, STOPPED = (
    "not_set_up",
    "starting",
    "on_air",
    "offline",
    "needs_pairing",
    "needs_plex",
    "needs_folder",
    "stopped",
)


class _Stopped(Exception):
    pass


class _WatchedLink(Link):
    """A Link that tells the engine when Booth DJ answered a check-in."""

    def __init__(self, server: str, token: str, on_checkin: Callable[[], None]):
        super().__init__(server, token)
        self._on_checkin = on_checkin

    def checkin(self) -> dict:
        reply = super().checkin()
        self._on_checkin()
        return reply


class Engine:
    """`booth run` on a background thread, restartable after setup changes the settings."""

    def __init__(self, load: Callable[[], dict] = config.load, retry_s: float = 60, echo: bool = True):
        self._load = load
        self._retry_s = retry_s
        self._echo = echo
        self._lock = threading.Lock()
        self._control = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = 0
        self.lines: deque[str] = deque(maxlen=200)
        self.state = NOT_SET_UP
        self.last_checkin: float | None = None
        self.last_show: dict | None = None
        self.unpaired: set[str] = set()  # people sharing this Booth whose accounts no longer know it
        self.scan: dict | None = None  # reading the music folder: {"done", "total", "started"}
        self._reading: str | None = None  # the folder scan_music is reading in the background
        self._read_again = False  # the folder changed during that read: read the new one after it
        self.report: dict | None = None  # the music folder's last tag report, for Booth's page

    # What the page reads

    @property
    def busy(self) -> bool:
        """Reading the library or delivering a show: not a moment to restart for an update."""
        return self._busy > 0

    def log(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.lines.append(line)
        if self._echo and sys.stderr is not None:
            print(line, file=sys.stderr, flush=True)

    def status(self) -> dict:
        return {
            "state": self.state,
            "busy": self.busy,
            "last_checkin": self.last_checkin,
            "last_show": self.last_show,
            "unpaired": sorted(self.unpaired),
            "scan": self.scan,
            "report": self.report,
            "log": list(self.lines)[-40:],
        }

    # Control

    def start(self) -> None:
        """Start (or restart, with the settings as they are now). Never two at once: a new start waits for
        the one before it to finish what it's doing (a delivery, say) before checking in itself."""
        with self._control:
            previous = self._thread
            self._stop.set()
            self.state = STARTING  # settings may have changed (signed in again, paired again): look afresh
            self.unpaired = set()
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._loop, args=(self._stop, previous), name="booth-engine", daemon=True
            )
            self._thread.start()

    def stop(self, wait: float | None = 5) -> None:
        """Stop; waits up to `wait` seconds (None: as long as it takes) for a show in hand to be finished."""
        with self._control:
            thread, self._thread = self._thread, None
            self._stop.set()
        if thread is not None:  # each start waits for the one before it, so the newest is the last to end
            thread.join(wait)

    def _mark(self, on: bool) -> None:
        with self._lock:
            self._busy += 1 if on else -1

    def _checked_in(self) -> None:
        self.last_checkin = time.time()
        if self.state in (STARTING, OFFLINE):
            self.state = ON_AIR

    def _scanned(self, *what) -> None:
        """Progress reading the music folder: (files done, files in all), then the tag report."""
        if len(what) == 2:
            done, total = what
            now, scan = time.time(), self.scan
            if not scan or not scan["total"]:  # the folder's been looked through; reading starts now
                scan = {"started": now, "first": done}
            # Files already in the index count as done straight away, so the rate is of those read since.
            read, spent = done - scan["first"], now - scan["started"]
            rate = read / spent if read and spent >= 2 else None
            left = (total - done) / rate if rate else None
            self.scan = scan | {"done": done, "total": total, "rate": rate, "left_s": left}
            return
        report = what[0]
        self.scan = None
        if report is None:  # the scan failed; the log says why
            return
        self.report = {
            "at": time.time(),
            "folder": folder_settings(self._load())[0]["music"],
            "lines": report.lines(),
            "files": report.files,
            "used": report.used,
        }

    def scan_music(self, again: bool = False) -> bool:
        """Read the music folder now, in the background (after setup, and when Booth starts, so the first
        long read happens before anyone asks for a show). False when there's no folder to read, or a read
        is under way; with `again`, that read is followed by another (the folder may have changed)."""
        settings = self._load()
        if not folder_mode(settings) or folder_settings(settings)[1]:
            return False
        folder = folder_settings(settings)[0]["music"]
        with self._lock:
            if self._reading or self.scan is not None:
                self._read_again = self._read_again or (again and folder != self._reading)
                return False
            self._reading, self._read_again = folder, False
            self.scan = {"done": 0, "total": 0, "started": time.time(), "first": 0}
            if self.report and self.report.get("folder") != folder:  # another folder's: not this one's
                self.report = None

        def go() -> None:
            self._mark(True)
            try:
                read_folder(settings, self._scanned)
            except Exception as e:  # noqa: BLE001 - say what; the next show tries again
                self.log(f"Couldn't read your music folder: {e}")
            finally:
                self._mark(False)
                with self._lock:
                    self._reading, again = None, self._read_again
                if again:
                    self.scan_music()

        threading.Thread(target=go, name="booth-scan", daemon=True).start()
        return True

    def _plex_refused(self) -> None:
        self.state = NEEDS_PLEX

    def _delivered(self, title: str) -> None:
        self.last_show = {"at": time.time(), "playlist": title}
        if self.state == NEEDS_PLEX:  # signed in again since
            self.state = ON_AIR

    def _loop(self, stop: threading.Event, previous: threading.Thread | None = None) -> None:
        def sleep(seconds: float) -> None:
            if stop.wait(seconds):
                raise _Stopped

        if previous is not None:
            previous.join()
        if stop.is_set():
            return
        self.state = STARTING

        while not stop.is_set():
            settings = self._load()
            _, missing, folders = needs(settings)
            if not settings.get("device_token") or not settings.get("server") or missing:
                self.state = NOT_SET_UP
                return
            absent = next((f for f in folders if not Path(f).expanduser().is_dir()), None)
            if absent:
                self.log(f"The folder {absent} isn't there (is the drive or share connected?).")
                self.state = NEEDS_FOLDER
                if stop.wait(self._retry_s):
                    break
                continue
            if self.state != NEEDS_PLEX:
                self.state = STARTING
            try:
                found_desks, people = desks(
                    settings,
                    self.log,
                    lambda server, token: _WatchedLink(server, token, self._checked_in),
                    skip=set(self.unpaired),
                    on_plex_refused=self._plex_refused,
                    busy=self._mark,
                    on_delivered=self._delivered,
                    on_scan=self._scanned,
                    reading=lambda: self.scan if self._reading else None,
                )
                for _, st in found_desks:
                    original_log = st.log

                    def logged(msg: str, _log=original_log) -> None:
                        _log(msg)
                        if msg.startswith("Could not reach Booth DJ"):
                            self.state = OFFLINE

                    st.log = logged

                def unpaired(i: int, people: list[dict] = people) -> None:
                    person = people[i - 1]
                    self.unpaired.add(person["id"])
                    name = person["name"]
                    self.log(f"{name}'s Booth account no longer knows this computer: add them again.")

                self.log(f"Connected to {settings['server']} as {settings.get('name', 'this machine')!r}.")
                if people:
                    names = ", ".join(p["name"] for p in people)
                    self.log(f"Also making shows for {names}.")
                run_desks(found_desks, sleep=sleep, unpaired=unpaired)
            except _Stopped:
                break
            except LinkError as e:
                if e.status == 401:
                    self.log("Booth DJ no longer knows this computer: connect it to your account again.")
                    if not stop.is_set():
                        self.state = NEEDS_PAIRING
                    return
                self.log(str(e))
            except Exception as e:  # noqa: BLE001 - say what, and try again in a minute
                self.log(f"Something went wrong: {e}")
            if stop.wait(self._retry_s):
                break
        if self._thread is None:  # stopped, not replaced by a newer start
            self.state = STOPPED
