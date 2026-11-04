"""The link to Booth DJ: pairing, check-ins, sending the catalog for a show, and fetching finished shows.

Every connection goes out from this machine; nothing here listens. What is sent is exactly what
protocol/api.md documents: this machine's name and Booth Engineer version, a catalog when a show asks for
one, and the outcome of each delivery.
"""

from __future__ import annotations

import gzip
import http.client
import json
import shutil
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

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PackageError(Exception):
    """Booth DJ sent a show package this machine won't use (reported back as a failed delivery)."""


GENERIC_FAILURE = "Delivery failed on this machine; details are in the booth run log there."


class Link:
    def __init__(self, server: str, token: str | None = None, timeout: float = 60):
        self.server = server.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        url = path if path.startswith("http") else f"{self.server}{path}"
        h = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read()).get("error") or f"HTTP {e.code}"
            except ValueError:
                message = f"HTTP {e.code}"
            raise LinkError(f"Booth DJ: {message}", e.code) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
            raise LinkError(f"Could not reach Booth DJ at {self.server}: {getattr(e, 'reason', e)}") from None

    def post(self, path: str, data: dict) -> tuple[int, dict]:
        body = json.dumps(data).encode()
        return self._call("POST", path, body, {"Content-Type": "application/json"})

    # Pairing

    def start_pairing(self, name: str) -> dict:
        return self.post("/v0/pair/start", {"name": name})[1]

    def claim(self, poll_token: str) -> str | None:
        """The device token once the code is confirmed on the phone; None while waiting."""
        status, data = self.post("/v0/pair/claim", {"poll_token": poll_token})
        return data["device_token"] if status == 200 else None

    # Shows

    def checkin(self) -> dict:
        return self.post("/v0/checkin", {"version": __version__})[1]

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
            dest = into / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp, dest.open("wb") as f:
                    shutil.copyfileobj(resp, f)
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
                raise LinkError(f"Couldn't download {name}: {getattr(e, 'reason', e)}") from None


def pair(link: Link, name: str, *, show: Callable[[dict], None], sleep=None, poll_s: float = 3) -> str:
    """Start pairing, show the code, wait until it's confirmed on the phone; returns the device token."""
    sleep = sleep or time.sleep
    start = link.start_pairing(name)
    show(start)
    deadline = time.monotonic() + start.get("expires_in", 600)
    while time.monotonic() < deadline:
        sleep(poll_s)
        try:
            if token := link.claim(start["poll_token"]):
                return token
        except LinkError as e:
            if e.status == 410:
                break
            if e.status is not None:
                raise
    raise LinkError("The pairing code expired before it was entered. Run `booth pair` again.")


@dataclass
class Station:
    """What `booth run` needs from this machine: how to read the catalog and how to deliver a show."""

    catalog: Callable[[], dict]
    deliver: Callable[[Path], str]  # show folder -> playlist title
    log: Callable[[str], None]
    # Outcomes not yet accepted by Booth DJ, so a lost report is retried instead of delivering twice.
    unreported: dict[str, dict] = field(default_factory=dict)


def handle(link: Link, station: Station, item: dict) -> None:
    """Do whatever one check-in entry asks for."""
    show_id, action = item["show_id"], item.get("action")
    if action == "send_catalog":
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
            for item in reply.get("shows", []):
                try:
                    handle(link, station, item)
                except LinkError:
                    raise
                except Exception as e:  # e.g. Plex unreachable while reading the library
                    station.log(f"{item['show_id']}: {e}")
            wait, backoff = float(reply.get("next_checkin_s", 60)), 0.0
        except LinkError as e:
            if e.status == 401:
                raise
            backoff = min(max(backoff * 2, 10.0), 300.0)
            station.log(f"{e} (trying again in {backoff:.0f} s)")
            wait = backoff
        if once:
            return
        sleep(wait)
