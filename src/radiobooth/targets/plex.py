"""Deliver a finished show to Plex.

Copies the show's break files into a folder that a Plex music library watches (normally a library of its
own, so breaks never mix into the user's music), asks Plex to scan that folder, waits for the breaks to
appear, then builds an ordinary playlist of the user's tracks and the breaks in running order.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from radiobooth.sources.plex import TRACK, PlexError, _paged

SCAN_TIMEOUT = 180  # seconds to wait for Plex to pick up new breaks


@dataclass
class Delivery:
    playlist_key: str
    title: str
    tracks: int
    breaks: int
    folder: Path


def load_package(show_dir: Path) -> dict:
    package = json.loads((show_dir / "show.json").read_text(encoding="utf-8"))
    if package.get("protocol") != "radiobooth/show-package@0":
        raise PlexError(f"{show_dir / 'show.json'} is not a radiobooth/show-package@0 file.")
    for item in package["items"]:
        if item["type"] == "break":
            path = show_dir / item["file"]
            if not path.is_file():
                raise PlexError(f"Missing break file {path}.")
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise PlexError(f"{path} doesn't match its checksum in show.json.")
    return package


def folder_name(package: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", package["title"].lower()).strip("-")[:40] or "show"
    return f"{package['created_at'][:10]}-{slug}-{package['show_id'][-6:]}"


def section_named(client, name: str) -> dict:
    sections = client.get("/library/sections")["MediaContainer"].get("Directory", [])
    for s in sections:
        if s.get("title") == name:
            if s.get("type") != "artist":
                raise PlexError(f"Plex library {name!r} isn't a music library.")
            return s
    raise PlexError(f"No Plex library named {name!r}.")


def copy_breaks(show_dir: Path, package: dict, dest: Path) -> dict[str, str]:
    """Copy break files to dest; returns break id -> file name."""
    dest.mkdir(parents=True, exist_ok=True)
    names = {}
    for item in package["items"]:
        if item["type"] == "break":
            src = show_dir / item["file"]
            shutil.copyfile(src, dest / src.name)
            names[item["id"]] = src.name
    return names


def find_breaks(client, section_key: str, folder: str, names: dict[str, str]) -> dict[str, str]:
    """Break id -> Plex ratingKey for the breaks Plex has scanned so far."""
    wanted = {f"/{folder}/{name}": bid for bid, name in names.items()}
    found = {}
    for meta in _paged(client, section_key, TRACK):
        for media in meta.get("Media", []):
            for part in media.get("Part", []):
                f = part.get("file", "").replace("\\", "/")
                for suffix, bid in wanted.items():
                    if f.endswith(suffix):
                        found[bid] = str(meta["ratingKey"])
    return found


def deliver(client, show_dir: Path, library: str, dest_root: Path, *, wait=SCAN_TIMEOUT, sleep=time.sleep):
    package = load_package(show_dir)
    section = section_named(client, library)
    folder = folder_name(package)
    names = copy_breaks(show_dir, package, dest_root / folder)

    # Scan the whole breaks library: Plex (1.43, on a NAS) ignored a scan scoped to the new folder, and this
    # library only holds breaks, so a full scan stays quick.
    locations = [loc["path"] for loc in section.get("Location", [])]
    client.get(f"/library/sections/{section['key']}/refresh")

    deadline, found = time.monotonic() + wait, {}
    while True:
        found = find_breaks(client, section["key"], folder, names)
        if len(found) == len(names) or time.monotonic() > deadline:
            break
        sleep(3)
    missing = sorted(set(names) - set(found))
    if missing:
        raise PlexError(
            f"Plex didn't pick up breaks {missing} within {wait} s. Check that {dest_root} is the folder "
            f"the {library!r} library watches ({', '.join(locations) or 'no folders'})."
        )

    keys = [found[i["id"]] if i["type"] == "break" else i["track_id"] for i in package["items"]]
    machine = client.get("/identity")["MediaContainer"]["machineIdentifier"]
    uri = f"server://{machine}/com.plexapp.plugins.library/library/metadata/{','.join(keys)}"
    out = client.request(
        "POST", "/playlists", {"type": "audio", "title": package["title"], "smart": 0, "uri": uri}
    )
    playlist = out["MediaContainer"]["Metadata"][0]
    return Delivery(
        playlist_key=str(playlist["ratingKey"]),
        title=playlist.get("title", package["title"]),
        tracks=sum(1 for i in package["items"] if i["type"] == "track"),
        breaks=len(names),
        folder=dest_root / folder,
    )
