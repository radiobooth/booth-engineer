"""Deliver a finished show to Plex.

Copies the show's break files into a folder that a Plex music library watches (normally a library of its
own, so breaks never mix into the user's music), asks Plex to scan that folder, waits for the breaks to
appear, then builds an ordinary playlist of the user's tracks and the breaks in running order.

A delivered show can be found again from its id (its breaks folder's name ends with part of it, and a small
note beside the breaks names its playlist): to copy it whole into a folder, mix it into one file, or remove
it. Songs for a copy are fetched from the Plex server to this computer; nothing goes anywhere else.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from radiobooth.sources.plex import TRACK, PlexAuthError, PlexError, _paged

SCAN_TIMEOUT = 180  # seconds to wait for Plex to pick up new breaks
NOTE = ".booth-show.json"  # beside a show's breaks: its id, title and playlist, to find it again


@dataclass
class Delivery:
    playlist_key: str
    title: str
    tracks: int
    breaks: int
    folder: Path
    machine: str = ""  # the server's machineIdentifier, for sharing the playlist


def load_package(show_dir: Path) -> dict:
    package = json.loads((show_dir / "show.json").read_text(encoding="utf-8"))
    if package.get("protocol") != "radiobooth/show-package@0":
        raise PlexError(f"{show_dir / 'show.json'} is not a radiobooth/show-package@0 file.")
    root = show_dir.resolve()
    for item in package["items"]:
        if item["type"] == "break":
            path = show_dir / item["file"]
            if not path.resolve().is_relative_to(root):
                raise PlexError(f"Refusing break file {item['file']!r} outside the show folder.")
            if not path.is_file():
                raise PlexError(f"Missing break file {path}.")
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise PlexError(f"{path} doesn't match its checksum in show.json.")
    return package


def folder_name(package: dict) -> str:
    """A plain folder name (letters, digits, dashes only), whatever the package says."""
    slug = re.sub(r"[^a-z0-9]+", "-", package["title"].lower()).strip("-")[:40] or "show"
    date = re.sub(r"[^0-9-]", "", str(package["created_at"])[:10]) or "undated"
    tail = re.sub(r"[^a-z0-9]", "", str(package["show_id"]).lower())[-6:] or "show"
    return f"{date}-{slug}-{tail}"


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


def deliver(
    client, show_dir: Path, library: str, dest_root: Path, *, wait=SCAN_TIMEOUT, sleep=time.sleep, prefix=""
):
    """`prefix` goes before the playlist's title: whose show it is, when people share this Booth."""
    package = load_package(show_dir)
    title = f"{prefix}{package['title']}"
    section = section_named(client, library)
    folder = folder_name(package)
    if not (dest_root / folder).resolve().is_relative_to(dest_root.resolve()):
        raise PlexError(f"Refusing to write outside {dest_root}.")
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
    out = client.request("POST", "/playlists", {"type": "audio", "title": title, "smart": 0, "uri": uri})
    playlist = out["MediaContainer"]["Metadata"][0]
    _note(dest_root / folder, package["show_id"], str(playlist["ratingKey"]), playlist.get("title", title))
    return Delivery(
        playlist_key=str(playlist["ratingKey"]),
        title=playlist.get("title", title),
        tracks=sum(1 for i in package["items"] if i["type"] == "track"),
        breaks=len(names),
        folder=dest_root / folder,
        machine=machine,
    )


def _note(folder: Path, show_id: str, playlist_key: str, title: str) -> None:
    """Note beside the breaks which show and playlist they are. Without it, finding them is only slower."""
    try:
        note = {"show_id": show_id, "playlist_key": playlist_key, "title": title}
        (folder / NOTE).write_text(json.dumps(note), encoding="utf-8")
    except OSError:
        pass


def _read_note(folder: Path) -> dict:
    try:
        note = json.loads((folder / NOTE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return note if isinstance(note, dict) else {}


def show_folder(dest_root: Path, show_id: str) -> Path | None:
    """The breaks folder of the show with this id, if it's still there."""
    tail = re.sub(r"[^a-z0-9]", "", show_id.lower())[-6:]
    if not tail:
        return None
    try:
        found = [d for d in dest_root.glob(f"*-{tail}") if d.is_dir()]
    except OSError:
        return None
    noted = [d for d in found if _read_note(d).get("show_id") == show_id]
    if noted:
        return noted[0]
    unnoted = [d for d in found if not _read_note(d)]  # delivered before the note: only if it's the only one
    return unnoted[0] if len(unnoted) == 1 else None


def shows_here(dest_root: Path, show_ids: list[str]) -> set[str]:
    """Which of these shows still have their breaks folder here."""
    return {i for i in show_ids if show_folder(dest_root, i) is not None}


def _part(meta: dict) -> dict:
    for media in meta.get("Media") or []:
        for part in media.get("Part") or []:
            return part
    return {}


def _items(client, key: str) -> list[dict] | None:
    """A playlist's items, or None if Plex has no such playlist."""
    try:
        return client.get(f"/playlists/{key}/items")["MediaContainer"].get("Metadata", [])
    except PlexAuthError:
        raise
    except PlexError:
        return None


def _holds(items: list[dict], folder: Path) -> bool:
    """Whether a playlist plays breaks from this folder."""
    mark = f"/{folder.name}/"
    return any(mark in _part(m).get("file", "").replace("\\", "/") for m in items)


@dataclass
class PlexShow:
    show_id: str
    title: str
    folder: Path  # its breaks, on this computer
    playlist_key: str | None
    items: list[dict] = field(default_factory=list)  # the playlist's items, as Plex lists them


def find_show(client, dest_root: Path, show_id: str, hint: str = "") -> PlexShow:
    """A delivered show: its breaks folder and its playlist (found from the note beside the breaks, or for
    older shows by looking through the audio playlists for one that plays them; `hint` is its title, to
    look at likely playlists first). The playlist is None when it's been deleted in Plex."""
    folder = show_folder(dest_root, show_id)
    if folder is None:
        raise PlexError("That show's breaks aren't in Booth's breaks folder any more.")
    note = _read_note(folder)
    key = note.get("playlist_key")
    items = _items(client, key) if key else None
    if items is None or not _holds(items, folder):
        key, items = None, None
        listed = client.get("/playlists", {"playlistType": "audio"})["MediaContainer"].get("Metadata", [])
        hint = (hint or note.get("title") or "").lower()
        listed.sort(key=lambda p: not (hint and hint in str(p.get("title", "")).lower()))
        for p in listed:
            if p.get("smart"):
                continue
            found = _items(client, str(p.get("ratingKey")))
            if found and _holds(found, folder):
                key, items = str(p["ratingKey"]), found
                title = p.get("title") or hint
                _note(folder, show_id, key, title)
                note = {"title": title}
                break
    title = note.get("title") or hint or folder.name
    return PlexShow(show_id, title, folder, key, items or [])


@dataclass
class Song:
    """One item of a Plex show's playlist, ready to copy or mix."""

    label: str  # "Artist - Title", for numbered file names and chapters
    seconds: int
    kind: str  # "song" or "break"
    ext: str
    local: Path | None  # a break's file on this computer
    part_key: str | None  # a song's file on the Plex server
    album: str | None
    track: int | None
    artist: str


def songs(show: PlexShow) -> list[Song]:
    out = []
    for m in show.items:
        part = _part(m)
        file = str(part.get("file") or "").replace("\\", "/")
        is_break = f"/{show.folder.name}/" in file
        name = PurePosixPath(file).name
        ext = PurePosixPath(name).suffix or (f".{part['container']}" if part.get("container") else ".mp3")
        artist = str(m.get("originalTitle") or m.get("grandparentTitle") or "")
        title = str(m.get("title") or name)
        album = None
        if m.get("parentRatingKey"):
            album = f"{m['parentRatingKey']}|{m.get('parentIndex') or 1}"
        out.append(
            Song(
                label=f"{artist} - {title}" if artist and not is_break else title,
                seconds=round((m.get("duration") or 0) / 1000),
                kind="break" if is_break else "song",
                ext=ext,
                local=show.folder / name if is_break and name else None,
                part_key=None if is_break else part.get("key"),
                album=None if is_break else album,
                track=m.get("index") if not is_break else None,
                artist=artist,
            )
        )
    return out


def _fetch(client, song: Song, dest: Path) -> None:
    if song.local is not None:
        shutil.copyfile(song.local, dest)
    elif song.part_key:
        try:
            client.download(song.part_key, dest)
        except PlexAuthError:
            raise
        except PlexError as e:
            raise OSError(str(e)) from None
    else:
        raise OSError("no file for this item")


def _playlist_show(client, dest_root: Path, show_id: str, hint: str) -> tuple[PlexShow, list[Song]]:
    show = find_show(client, dest_root, show_id, hint)
    if show.playlist_key is None:
        raise PlexError("That show's playlist isn't in Plex any more.")
    return show, songs(show)


def copy_out(client, dest_root: Path, copies: Path, show_id: str, hint: str = "", progress=None):
    """Copy a Plex show whole into `copies/<title>/`: songs fetched from Plex, breaks from their folder."""
    from radiobooth.targets import playlist

    show, items = _playlist_show(client, dest_root, show_id, hint)
    entries = [(f"{s.seconds},{s.label}", s.ext, lambda dest, s=s: _fetch(client, s, dest)) for s in items]
    return playlist.write_copy(copies, show.title, show_id, entries, progress)


def one_file(client, dest_root: Path, copies: Path, show_id: str, hint: str = "", progress=None):
    """Mix a Plex show into `copies/<title>.mp3`. Its songs are fetched from Plex into a folder beside it
    first (the mix reads each one twice), and deleted after."""
    from radiobooth import render
    from radiobooth.targets import playlist

    show, items = _playlist_show(client, dest_root, show_id, hint)
    fetch = [s for s in items if s.local is None]
    total = len(fetch) + 2 * len(items)
    copies.mkdir(parents=True, exist_ok=True)
    work = copies / f".{playlist.file_name(show.title)}.songs"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        ready, missing, got = [], 0, 0
        for n, s in enumerate(items):
            path = s.local
            if path is None:
                if progress:
                    progress(got, total)
                path = work / f"{n:03d}{s.ext.lower()}"
                try:
                    _fetch(client, s, path)
                except OSError:
                    missing += 1
                    continue
                finally:
                    got += 1
            elif not path.is_file():
                missing += 1
                continue
            ready.append(render.Item(path, s.label, s.kind, s.album, s.track))
        if not ready:
            raise PlexError("None of this show's files could be fetched from Plex.")
        dj = next((s.artist for s in items if s.kind == "break" and s.artist), "") or "Booth"
        cover = next(
            (c for s in items if s.kind == "break" and s.local for c in [_cover(s.local)] if c), None
        )
        tags = {"title": show.title, "show_id": show_id, "artist": dj, "cover": cover}
        total = len(fetch) + 2 * len(ready)  # what's left to do now that the missing are known
        step = (lambda done, _t: progress(len(fetch) + done, total)) if progress else None
        made = playlist.render_into(copies, show.title, show_id, ready, tags, step)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    made.missing += missing
    return made


def _cover(path: Path) -> bytes | None:
    from mutagen import File as AudioFile

    try:
        found = AudioFile(str(path))
    except Exception:  # noqa: BLE001  # no cover is fine
        return None
    if found is None or not hasattr(found.tags, "getall"):
        return None
    pics = found.tags.getall("APIC")
    return pics[0].data if pics else None


def remove(client, dest_root: Path, library: str, show_id: str, hint: str = "") -> bool:
    """Delete a show from Plex: its playlist and its breaks (never the user's music). False when its breaks
    folder isn't here."""
    if show_folder(dest_root, show_id) is None:
        return False
    show = find_show(client, dest_root, show_id, hint)
    if show.playlist_key:
        client.request("DELETE", f"/playlists/{show.playlist_key}")
    if not show.folder.resolve().is_relative_to(dest_root.resolve()):
        raise PlexError(f"Refusing to delete outside {dest_root}.")
    shutil.rmtree(show.folder)
    try:  # so Plex drops the breaks from its breaks library
        client.get(f"/library/sections/{section_named(client, library)['key']}/refresh")
    except PlexAuthError:
        raise
    except PlexError:
        pass
    return True
