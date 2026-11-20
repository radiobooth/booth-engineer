"""The link to Booth DJ: pairing, check-ins, sending the catalog for a show, fetching finished shows,
asking for shows from Booth's page, and sending a show as one file when the listener asks for it on their
phone.

Every connection goes out from this machine; nothing here listens. What is sent is exactly what
protocol/api.md documents: this machine's name and Booth Engineer version, a catalog when a show asks for
one, the outcome of each delivery, the show requests typed into Booth's page, and a delivered show mixed
into one MP3 when its listener asks to download it (only then, and only that show).
"""

from __future__ import annotations

import contextlib
import gzip
import http.client
import json
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from radiobooth import __version__
from radiobooth.catalog import check as check_catalog

USER_AGENT = f"radiobooth/{__version__}"


class LinkError(Exception):
    """Booth DJ couldn't be reached or refused a request."""

    def __init__(self, message: str, status: int | None = None, *, network: bool = False):
        super().__init__(message)
        self.status = status
        self.network = network  # no answer came back (the request may or may not have arrived)


class PackageError(Exception):
    """Booth DJ sent a show package this machine won't use (reported back as a failed delivery)."""


GENERIC_FAILURE = "Delivery failed on this machine; details are in the booth run log there."
FILE_FAILURE = "Making the file failed on this machine; details are in Booth's log there."


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """API calls carry the device token, so they never follow a redirect anywhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_api = urllib.request.build_opener(_NoRedirects)


def secure_url(url: str) -> bool:
    """https anywhere, or http to this machine (local development)."""
    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    return bool(parts.hostname) and (parts.scheme == "https" or (parts.scheme == "http" and local))


class Link:
    def __init__(self, server: str, token: str | None = None, timeout: float = 60):
        # The device token rides on every call, so plain http is only for a DJ on this machine.
        if not secure_url(server):
            raise LinkError(f"Booth DJ's address must start with https:// (got {server!r}).")
        self.server = server.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.delivers_to: str | None = None  # "plex" or "playlist", said at check-in

    def _call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        # Only paths on the paired server: a URL from a reply must never carry the token elsewhere.
        if not path.startswith("/") or path.startswith("//"):
            raise LinkError(f"Refusing to send to {path!r}: not a path on {self.server}.")
        url = f"{self.server}{path}"
        h = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            with _api.open(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            message = f"HTTP {e.code}"
            try:  # the DJ's own message if it sent one; any odd or cut-short body keeps the status
                body = json.loads(e.read())
                if isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"]:
                    message = body["error"]
            except (ValueError, http.client.HTTPException, OSError):
                pass
            raise LinkError(f"Booth DJ: {message}", e.code) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise LinkError(f"Could not reach Booth DJ at {self.server}: {reason}", network=True) from None
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raise LinkError("Booth DJ sent a reply that isn't JSON (cut short?).") from None
        if not isinstance(data, dict):
            raise LinkError("Booth DJ sent an unexpected reply.")
        return status, data

    def get(self, path: str) -> dict:
        return self._call("GET", path)[1]

    def post(self, path: str, data: dict) -> tuple[int, dict]:
        return self.send("POST", path, data)

    def send(self, method: str, path: str, data: dict) -> tuple[int, dict]:
        body = json.dumps(data).encode()
        return self._call(method, path, body, {"Content-Type": "application/json"})

    # Pairing

    def redeem(self, code: str, name: str) -> str:
        """Trade a pairing code from the phone for this machine's device token."""
        _, data = self.post("/v0/pair", {"code": code, "name": name})
        token = data.get("device_token")
        if not isinstance(token, str) or not token:
            raise LinkError("Booth DJ accepted the code but sent no device token.")
        return token

    # Shows

    def ask(self, request: dict) -> dict:
        """Ask for a show as the phone page does: prompt, minutes, dj, voice, dj_name and station."""
        return self.post("/v0/shows", request)[1]

    def checkin(self) -> dict:
        """{"next_checkin_s": 5..3600, "shows": [entries with a show_id]}; anything else is a LinkError."""
        said = {"version": __version__}
        if self.delivers_to:
            said["delivers_to"] = self.delivers_to
        reply = self.post("/v0/checkin", said)[1]
        shows, wait = reply.get("shows", []), reply.get("next_checkin_s", 60)
        if not isinstance(shows, list) or not all(isinstance(s, dict) and s.get("show_id") for s in shows):
            raise LinkError("Booth DJ sent a check-in reply this version doesn't understand.")
        if isinstance(wait, bool) or not isinstance(wait, int | float) or wait != wait:
            wait = 60
        return {**reply, "shows": shows, "next_checkin_s": min(max(float(wait), 5.0), 3600.0)}

    def send_catalog(self, url: str, catalog: dict) -> None:
        body = gzip.compress(json.dumps(catalog, ensure_ascii=False).encode())
        self._call("PUT", url, body, {"Content-Type": "application/json", "Content-Encoding": "gzip"})

    def report(self, show_id: str, *, playlist: str | None = None, error: str | None = None) -> None:
        result = {"ok": True, "playlist": playlist} if error is None else {"ok": False, "error": error[:500]}
        self.post(f"/v0/shows/{show_id}/result", result)

    # A show as one file, for the listener's phone

    def file_making(self, show_id: str) -> None:
        self.post(f"/v0/shows/{show_id}/file/making", {})

    def file_upload(self, show_id: str, path: Path) -> None:
        """Upload the show's one file to the signed link Booth DJ hands out (it's signed: no token)."""
        size = path.stat().st_size
        _, where = self.post(f"/v0/shows/{show_id}/file/upload", {"bytes": size})
        url, headers = where.get("url"), where.get("headers") or {}
        if not isinstance(url, str) or not url:
            raise PackageError("Booth DJ sent no link to upload the file to.")
        if not secure_url(url):
            raise PackageError("Refusing to upload the file over an insecure link.")
        if not isinstance(headers, dict) or {str(k).lower() for k in headers} - {"content-type"}:
            raise PackageError("Booth DJ asked for upload headers this version won't send.")
        kind = next((str(v) for k, v in headers.items() if str(k).lower() == "content-type"), "audio/mpeg")
        h = {"User-Agent": USER_AGENT, "Content-Length": str(size), "Content-Type": kind}
        with path.open("rb") as f:
            req = urllib.request.Request(url, data=f, method="PUT", headers=h)
            try:
                # A slow home upload of a long show takes minutes; this is a quiet-connection limit.
                with urllib.request.urlopen(req, timeout=max(self.timeout, 120)) as resp:
                    resp.read()
            except urllib.error.HTTPError as e:
                # Storage said no: sending the same thing again won't change that, so it's a failed file.
                raise PackageError(f"Storage refused the file upload (HTTP {e.code}).") from None
            except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
                raise LinkError(
                    f"Couldn't upload the file: {getattr(e, 'reason', e)}", network=True
                ) from None

    def file_result(self, show_id: str, *, ok: bool) -> None:
        self.post(
            f"/v0/shows/{show_id}/file/result", {"ok": True} if ok else {"ok": False, "error": FILE_FAILURE}
        )

    def download(self, files: dict[str, str], into: Path) -> None:
        """Fetch a show package from its signed URLs (no token: they're signed already)."""
        for name, url in files.items():
            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise PackageError(f"Refusing package file name {name!r}.")
            if not isinstance(url, str) or not secure_url(url):
                # show.json says which breaks to trust, so it must not be swappable on the way here.
                raise PackageError(f"Refusing to download {name} over an insecure link.")
            dest = into / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            network = (urllib.error.URLError, http.client.HTTPException, OSError)
            # Network trouble is a LinkError (retried); a local OSError (disk full...) fails the delivery.
            with dest.open("wb") as f:
                try:
                    resp = urllib.request.urlopen(req, timeout=self.timeout)
                except network as e:
                    raise LinkError(f"Couldn't download {name}: {getattr(e, 'reason', e)}") from None
                with resp:
                    expected = resp.headers.get("Content-Length")
                    while True:
                        try:
                            chunk = resp.read(1 << 16)
                        except network as e:
                            raise LinkError(f"Couldn't download {name}: {e}") from None
                        if not chunk:
                            break
                        f.write(chunk)
                if expected is not None and f.tell() != int(expected):
                    raise LinkError(f"Download of {name} was cut short; will try again.")


@dataclass
class Station:
    """What `booth run` needs from this machine: how to read the catalog and how to deliver a show."""

    catalog: Callable[[], dict]
    deliver: Callable[[Path], str]  # show folder -> playlist title
    log: Callable[[str], None]
    # Outcomes not yet accepted by Booth DJ, so a lost report is retried instead of delivering twice.
    unreported: dict[str, dict] = field(default_factory=dict)
    # The last problem logged for each show, so one that repeats every check-in is logged once.
    problems: dict[str, str] = field(default_factory=dict)
    # A delivered show mixed into one MP3 (show id, title -> its path, and whether it was made just now
    # rather than found from Booth's page's Make one file), for the listener's phone; None: this machine
    # can't. It may take minutes, so it runs on a thread of its own (see send_file).
    one_file: Callable[[str, str], tuple[Path, bool]] | None = None
    busy: Callable[[bool], None] | None = None
    mixing: threading.Lock | None = None  # held while a file is made and uploaded (see send_file)


# Shows being sent as one file, across restarts of the check-in loop (which make new Stations).
_sending: dict[str, threading.Thread] = {}
_sending_lock = threading.Lock()
# Files made only for a phone: deleted once uploaded, so they don't pile up in Copies/ (a file the person
# made on Booth's page stays). Remembered across a retry, which finds the same file again.
_phone_only: set[Path] = set()


def sending(show_id: str | None = None) -> bool:
    """A show (that one, if given) is being made into one file or uploaded: not a moment to restart for an
    update, or to remove it."""
    with _sending_lock:
        return any(t.is_alive() for i, t in _sending.items() if show_id in (None, i))


def wait_sending(timeout: float | None = None) -> None:
    """Wait for files on their way (`booth run --once` would otherwise exit mid-upload)."""
    with _sending_lock:
        threads = list(_sending.values())
    for t in threads:
        t.join(timeout)


def send_file(link: Link, station: Station, item: dict) -> threading.Thread | None:
    """Start sending a show as one file, unless that's under way already. Returns the thread, if started."""
    show_id = item["show_id"]
    if station.one_file is None:
        return None
    with _sending_lock:
        running = _sending.get(show_id)
        if running is not None and running.is_alive():
            return None
        thread = threading.Thread(
            target=_send_file, args=(link, station, show_id, str(item.get("title") or "")), daemon=True
        )
        _sending[show_id] = thread
        if station.busy:
            station.busy(True)
        try:
            thread.start()
        except BaseException:
            if station.busy:
                station.busy(False)
            raise
    return thread


def _send_file(link: Link, station: Station, show_id: str, title: str) -> None:
    """Make the show into one file (or find the one made before) and upload it. Network trouble ends this
    try quietly: Booth DJ asks again at the next check-in, and the file made already is used then."""
    try:
        link.file_making(show_id)
        # Held until the upload is done, so Booth's page can't make or replace the file meanwhile.
        with station.mixing or contextlib.nullcontext():
            station.log(f"{show_id}: making {title!r} into one file for your phone...")
            try:
                path, fresh = station.one_file(show_id, title)
                if fresh:
                    _phone_only.add(path)
                station.log(f"{show_id}: sending the file ({path.stat().st_size / 1e6:.0f} MB)...")
                link.file_upload(show_id, path)
            except LinkError:
                raise  # network trouble, or Booth DJ said no: below
            except Exception as e:  # the file couldn't be made or read, or storage refused it
                station.log(f"{show_id}: couldn't send the file to your phone: {e}")
                link.file_result(show_id, ok=False)
                return
        link.file_result(show_id, ok=True)
        station.log(f"{show_id}: the file is on its way to your phone.")
        if path in _phone_only:
            _phone_only.discard(path)
            with contextlib.suppress(OSError):
                path.unlink()
                path.with_suffix(".cue").unlink(missing_ok=True)
    except LinkError as e:
        if e.status == 409:  # nobody's waiting for it any more (timed out, or asked again elsewhere)
            station.log(f"{show_id}: the file isn't wanted any more ({e}).")
        elif e.status == 422:  # Booth DJ checked the upload and failed it; it says why on the phone
            station.log(f"{show_id}: {e}")
        elif e.status is not None and 400 <= e.status < 500 and e.status != 429:
            # Booth DJ won't take this as it is; trying again would only repeat it.
            station.log(f"{show_id}: {e}")
            with contextlib.suppress(LinkError):
                link.file_result(show_id, ok=False)
        else:
            station.log(f"{show_id}: {e} (Booth tries again shortly)")
    except Exception as e:  # noqa: BLE001 - a thread of its own: say what, and let the DJ ask again
        station.log(f"{show_id}: sending the file failed: {e}")
    finally:
        if station.busy:
            station.busy(False)


def handle(link: Link, station: Station, item: dict) -> None:
    """Do whatever one check-in entry asks for."""
    show_id, action = item["show_id"], item.get("action")
    if action == "send_catalog":
        if show_id not in station.problems:  # retrying after a logged problem: say nothing new
            station.log(f"{show_id}: reading the library for a new show...")
        catalog, skipped, why = check_catalog(station.catalog())
        if skipped and show_id not in station.problems:
            station.log(f"{show_id}: left out {skipped} tracks the catalog can't hold (the first: {why}).")
        try:
            link.send_catalog(item["catalog_url"], catalog)
        except LinkError as e:
            if e.status != 409:  # 409: already sent (another check-in got there first)
                raise
        station.log(f"{show_id}: sent {len(catalog['tracks'])} tracks; the DJ is on it.")
    elif action == "send_file":
        send_file(link, station, item)
    elif action == "deliver":
        if show_id not in station.unreported:
            station.unreported[show_id] = deliver(link, station, item)
        link.report(show_id, **station.unreported[show_id])  # LinkError: kept, retried next check-in
        del station.unreported[show_id]


def deliver(link: Link, station: Station, item: dict) -> dict:
    """Fetch and deliver one show; returns what to report. Only network trouble raises."""
    show_id = item["show_id"]
    station.log(f"{show_id}: {item.get('title')!r} is ready, delivering...")
    with tempfile.TemporaryDirectory(prefix="booth-show-") as tmp:
        try:
            link.download(item["files"], Path(tmp))
            playlist = station.deliver(Path(tmp))
        except LinkError:
            raise  # a network problem: try again on the next check-in
        except Exception as e:
            # The details can name local paths or the Plex address, so they stay in the local log.
            station.log(f"{show_id}: delivery failed: {e}")
            return {"error": GENERIC_FAILURE}
    station.log(f"{show_id}: playlist {playlist!r} is ready to play.")
    return {"playlist": playlist}


def check_in(link: Link, station: Station, backoff: float = 0.0) -> tuple[float, float]:
    """One check-in and whatever it asks for. Returns how long to wait before the next one, and the backoff
    to carry: on network trouble it doubles, 10 s up to 5 minutes. Only a 401 (not paired) raises."""
    try:
        reply = link.checkin()
        for item in reply["shows"]:
            show_id = item["show_id"]
            try:
                handle(link, station, item)
            except LinkError:
                raise
            except Exception as e:  # e.g. Plex unreachable while reading the library: try next time
                if station.problems.get(show_id) != str(e):
                    station.problems[show_id] = str(e)
                    station.log(f"{show_id}: {e} (Booth keeps trying; this is logged once)")
            else:
                station.problems.pop(show_id, None)
        return reply["next_checkin_s"], 0.0
    except LinkError as e:
        if e.status == 401:
            raise
        backoff = min(max(backoff * 2, 10.0), 300.0)
        station.log(f"{e} (trying again in {backoff:.0f} s)")
        return backoff, backoff


def run(link: Link, station: Station, *, once: bool = False, sleep=None) -> None:
    """Check in, act, and wait as long as Booth DJ asks; on network trouble back off up to 5 minutes."""
    run_all([(link, station)], once=once, sleep=sleep)


def run_all(
    desks: list[tuple[Link, Station]],
    *,
    once: bool = False,
    sleep=None,
    unpaired: Callable[[int], None] | None = None,
) -> None:
    """`run` for each Booth account this computer is connected to (the first is its own; the others are
    people sharing it), one at a time, each checking in when its Booth DJ asks it to.

    A 401 on the first stops everything: this computer isn't paired any more. On another one it stops only
    that person's check-ins, and `unpaired(index)` hears about it; without `unpaired`, it raises too."""
    sleep = sleep or time.sleep
    now = 0.0  # time passes here only by waiting, so a wait is exactly what was asked for
    due = dict.fromkeys(range(len(desks)), 0.0)
    backoff = dict.fromkeys(due, 0.0)
    while due:
        i = min(due, key=lambda k: (due[k], k))
        if due[i] > now:
            sleep(due[i] - now)
            now = due[i]
        link, station = desks[i]
        try:
            wait, backoff[i] = check_in(link, station, backoff[i])
        except LinkError:
            if i == 0 or unpaired is None:
                raise
            unpaired(i)
            del due[i]
            continue
        if once:
            del due[i]
        else:
            due[i] = now + wait
