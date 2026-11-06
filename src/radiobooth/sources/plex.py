"""Read a Plex music library into a catalog.

Talks to the Plex server's local HTTP API with the server token. Only metadata is read; file paths in Plex's
responses are dropped here and never reach the catalog.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Protocol

from radiobooth.sources.added import drop_bulk_dates

PAGE_SIZE = 500
TRACK, ALBUM = 10, 9  # Plex metadata type numbers


class PlexError(RuntimeError):
    pass


class Getter(Protocol):
    def get(self, path: str, params: dict | None = None) -> dict: ...


class PlexClient:
    def __init__(self, base_url: str, token: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def get(self, path: str, params: dict | None = None) -> dict:
        return self.request("GET", path, params)

    def request(self, method: str, path: str, params: dict | None = None) -> dict:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        headers = {"Accept": "application/json", "X-Plex-Token": self.token}
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body, ctype = resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise PlexError(f"Plex returned HTTP {e.code} for {method} {path}") from None
        except urllib.error.URLError as e:
            raise PlexError(f"Could not reach Plex at {self.base_url}: {e.reason}") from None
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except ValueError:
            raise PlexError(
                f"{self.base_url} answered with {ctype or 'something'} instead of Plex JSON."
                " Check PLEX_URL, including the port (Plex usually listens on 32400)."
            ) from None


def music_sections(client: Getter) -> list[dict]:
    sections = client.get("/library/sections")["MediaContainer"].get("Directory", [])
    return [s for s in sections if s.get("type") == "artist"]


def _paged(client: Getter, section_key: str, kind: int) -> Iterator[dict]:
    start = 0
    while True:
        params = {
            "type": kind,
            "includeGuids": 1,
            "X-Plex-Container-Start": start,
            "X-Plex-Container-Size": PAGE_SIZE,
        }
        mc = client.get(f"/library/sections/{section_key}/all", params)["MediaContainer"]
        items = mc.get("Metadata", [])
        yield from items
        start += len(items)
        if not items or start >= mc.get("totalSize", start):
            return


def _iso(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def _tags(meta: dict, key: str) -> list[str]:
    return [t["tag"] for t in meta.get(key, []) if t.get("tag")]


def _mbid(meta: dict) -> str | None:
    for g in meta.get("Guid", []):
        gid = g.get("id", "")
        if gid.startswith("mbid://"):
            return gid.removeprefix("mbid://")
    return None


def to_track(meta: dict, album: dict | None = None) -> dict | None:
    """One Plex track to a catalog track, or None if it lacks what the catalog requires."""
    album = album or {}
    title, album_artist = meta.get("title"), meta.get("grandparentTitle")
    artist = meta.get("originalTitle") or album_artist
    duration = meta.get("duration")
    if not (meta.get("ratingKey") and title and artist and duration):
        return None
    track = {
        "id": str(meta["ratingKey"]),
        "title": title,
        "artist": artist,
        "album_artist": album_artist if album_artist and album_artist != artist else None,
        "album": meta.get("parentTitle"),
        "disc_number": meta.get("parentIndex"),
        "track_number": meta.get("index"),
        "year": meta.get("parentYear") or meta.get("year") or album.get("year"),
        "genres": _tags(meta, "Genre") or album.get("genres") or None,
        "duration_ms": int(duration),
        "added_at": _iso(meta.get("addedAt")),
        "play_count": meta.get("viewCount"),
        "last_played_at": _iso(meta.get("lastViewedAt")),
        "rating": round(meta["userRating"] / 10, 2) if meta.get("userRating") is not None else None,
        "musicbrainz_id": _mbid(meta),
    }
    if not (isinstance(track["year"], int) and 1800 <= track["year"] <= 2200):
        track["year"] = None
    for key in ("disc_number", "track_number"):
        if not (isinstance(track[key], int) and track[key] >= 1):
            track[key] = None
    return {k: v for k, v in track.items() if v is not None}


def read_section(client: Getter, section: dict) -> tuple[list[dict], int]:
    """All usable tracks in one music section, and how many were skipped."""
    albums = {
        str(a["ratingKey"]): {"year": a.get("year"), "genres": _tags(a, "Genre")}
        for a in _paged(client, section["key"], ALBUM)
    }
    tracks, skipped = [], 0
    for meta in _paged(client, section["key"], TRACK):
        track = to_track(meta, albums.get(str(meta.get("parentRatingKey"))))
        if track is None:
            skipped += 1
        else:
            tracks.append(track)
    return tracks, skipped


def build_catalog(client: Getter, library: str | None = None, exclude: str | None = None) -> tuple[dict, int]:
    """The catalog for one music library (by name, or the only one), and the skipped-track count.

    `exclude` names a library to leave out, normally the one that holds Radio Booth's own breaks.
    """
    sections = [s for s in music_sections(client) if not exclude or s.get("title") != exclude]
    if library:
        sections = [s for s in sections if s.get("title") == library]
        if not sections:
            raise PlexError(f"No music library named {library!r} on this Plex server.")
    elif len(sections) > 1:
        names = ", ".join(repr(s.get("title")) for s in sections)
        raise PlexError(
            f"This Plex server has several music libraries ({names}); "
            "pick one with --library or $BOOTH_MUSIC_LIBRARY."
        )
    elif not sections:
        raise PlexError("This Plex server has no music library.")
    section = sections[0]
    tracks, skipped = read_section(client, section)
    drop_bulk_dates(tracks)
    catalog = {
        "protocol": "radiobooth/catalog@0",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {"kind": "plex", "library": section.get("title", "")},
        "tracks": tracks,
    }
    return catalog, skipped
