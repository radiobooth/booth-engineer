"""The link to Booth DJ: pairing, check-ins, sending the catalog for a show, fetching finished shows, and
asking for shows from Booth's page.

Every connection goes out from this machine; nothing here listens. What is sent is exactly what
protocol/api.md documents: this machine's name and Booth Engineer version, a catalog when a show asks for
one, the outcome of each delivery, and the show requests typed into Booth's page.
"""

from __future__ import annotations

import gzip
import http.client
import json
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from radiobooth import __version__

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
        body = json.dumps(data).encode()
        return self._call("POST", path, body, {"Content-Type": "application/json"})

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
        reply = self.post("/v0/checkin", {"version": __version__})[1]
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


def handle(link: Link, station: Station, item: dict) -> None:
    """Do whatever one check-in entry asks for."""
    show_id, action = item["show_id"], item.get("action")
    if action == "send_catalog":
        if show_id not in station.problems:  # retrying after a logged problem: say nothing new
            station.log(f"{show_id}: reading the library for a new show...")
        catalog = station.catalog()
        try:
            link.send_catalog(item["catalog_url"], catalog)
        except LinkError as e:
            if e.status != 409:  # 409: already sent (another check-in got there first)
                raise
        station.log(f"{show_id}: sent {len(catalog['tracks'])} tracks; the DJ is on it.")
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


def run(link: Link, station: Station, *, once: bool = False, sleep=None) -> None:
    """Check in, act, and wait as long as Booth DJ asks; on network trouble back off up to 5 minutes."""
    sleep, backoff = sleep or time.sleep, 0.0
    while True:
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
            wait, backoff = reply["next_checkin_s"], 0.0
        except LinkError as e:
            if e.status == 401:
                raise
            backoff = min(max(backoff * 2, 10.0), 300.0)
            station.log(f"{e} (trying again in {backoff:.0f} s)")
            wait = backoff
        if once:
            return
        sleep(wait)
