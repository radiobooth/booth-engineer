"""Deliver a finished show as a playlist file, for music kept in a plain folder.

Each show becomes one .m3u8 playlist in the Booth shows folder, beside a breaks/ folder holding its breaks.
The playlist lists the user's own files where they are (nothing is copied or moved) and the breaks between
them, so any player that opens playlists plays the show: foobar2000, MusicBee, VLC, Winamp, Music on a Mac.

A playlist names its show on a comment line, so delivering the same show again rewrites its own playlist,
and Booth's page can list and remove shows without keeping a list of its own.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from radiobooth.targets.plex import folder_name, load_package

MARK = "#BOOTH-SHOW:"  # show id, on its own line in each playlist Booth writes
BREAKS = "breaks"
# Names Windows keeps for devices, with or without an extension.
_RESERVED = {"con", "prn", "aux", "nul", *(f"{d}{i}" for d in ("com", "lpt") for i in range(1, 10))}


class PlaylistError(Exception):
    """The show couldn't be written as a playlist."""


@dataclass
class Delivery:
    title: str
    playlist: Path
    tracks: int
    breaks: int
    missing: int  # tracks no longer in the music folder, left out of the playlist
    folder: Path  # the show's breaks


def file_name(title: str) -> str:
    """A playlist file name every system accepts, close to the title."""
    name = unicodedata.normalize("NFC", title)
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\s*:\s*", " - ", name)
    name = re.sub(r"[/\\|]", "-", name)
    name = re.sub(r'[<>"?*\x00-\x1f\x7f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")[:100].strip(" .")
    if not name or name.split(".")[0].lower() in _RESERVED:
        name = f"Booth show {name}".strip()
    return name


def show_of(playlist: Path) -> str | None:
    """The show id a playlist file names, or None for one Booth didn't write."""
    try:
        with playlist.open(encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(5), f, strict=False):
                if line.startswith(MARK):
                    return line[len(MARK) :].strip() or None
    except OSError:
        return None
    return None


def _line(text: str) -> str:
    """One line of playlist text: no line breaks, whatever a tag holds."""
    return re.sub(r"[\r\n]+", " ", text).strip()


def _place(out_root: Path, title: str, show_id: str) -> Path:
    """The show's playlist file: its own from an earlier delivery, else a free name."""
    base = file_name(title)
    for n in range(1, 1000):
        candidate = out_root / (f"{base}.m3u8" if n == 1 else f"{base} ({n}).m3u8")
        if not candidate.exists() or show_of(candidate) == show_id:
            return candidate
    raise PlaylistError(f"Too many playlists named {base!r} in {out_root}.")


def _music_file(music_root: Path, rel: str) -> Path | None:
    """The file a track's path inside the music folder names, if it's still there. Linked folders inside the
    music folder are fine (the scan follows them), so this checks the path itself, not where links lead."""
    parts = PurePosixPath(rel).parts
    if not parts or PurePosixPath(rel).is_absolute() or ".." in parts or ":" in parts[0]:
        return None
    for form in ("NFC", "NFD"):  # the index keeps names composed; a Linux disk may hold them decomposed
        path = music_root.joinpath(*(unicodedata.normalize(form, p) for p in parts))
        if path.is_file():
            return path
    return None


def write_atomically(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".booth-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def deliver(
    show_dir: Path,
    out_root: Path,
    music_root: Path,
    lookup: Callable[[str], tuple[str, dict] | None],
    prefix: str = "",
) -> Delivery:
    """Write the show's playlist and copy its breaks into `out_root`. `lookup(track id)` gives the track's
    file inside `music_root` and its tags, or None when it's gone; `prefix` goes before the title (whose
    show it is, when people share this Booth)."""
    package = load_package(show_dir)
    show_id = str(package["show_id"])
    title = f"{prefix}{package['title']}"
    root = out_root.resolve()
    folder = root / BREAKS / folder_name(package)
    if not folder.resolve().is_relative_to(root):
        raise PlaylistError(f"Refusing to write outside {out_root}.")
    music_root = music_root.resolve()
    host = _line(package.get("dj", {}).get("name") or "") or "Booth"

    lines = ["#EXTM3U", f"#PLAYLIST:{_line(title)}", f"{MARK}{_line(show_id)}"]
    tracks = breaks = missing = 0
    copies: list[tuple[Path, Path]] = []
    for item in package["items"]:
        if item["type"] == "break":
            breaks += 1
            src = show_dir / item["file"]
            copies.append((src, folder / src.name))
            secs = max(1, round(item["duration_ms"] / 1000))
            lines += [f"#EXTINF:{secs},{host} - Break {breaks}", str(folder / src.name)]
            continue
        found = lookup(item["track_id"])
        path = _music_file(music_root, found[0]) if found else None
        if path is None:
            missing += 1
            continue
        tracks += 1
        tags = found[1]
        ms = tags.get("duration_ms")
        secs = max(1, round(ms / 1000)) if isinstance(ms, int) and ms > 0 else -1
        name = " - ".join(_line(str(tags[k])) for k in ("artist", "title") if tags.get(k))
        lines += [f"#EXTINF:{secs},{name or path.stem}", str(path)]
    if not tracks:
        raise PlaylistError("None of this show's tracks are in the music folder any more.")

    folder.mkdir(parents=True, exist_ok=True)
    for src, dest in copies:
        shutil.copyfile(src, dest)
    playlist = _place(root, title, show_id)
    write_atomically(playlist, "\n".join(lines) + "\n")
    return Delivery(title, playlist, tracks, breaks, missing, folder)


@dataclass
class Show:
    show_id: str
    title: str
    playlist: Path
    made_at: float  # when the playlist was written (seconds since the epoch)


def shows(out_root: Path) -> list[Show]:
    """The shows Booth has delivered into this folder, newest first."""
    found = []
    try:
        entries = list(out_root.glob("*.m3u8"))
    except OSError:
        return []
    for p in entries:
        show_id = show_of(p)
        if not show_id:
            continue
        try:
            made = p.stat().st_mtime
        except OSError:
            continue
        found.append(Show(show_id, _title(p) or p.stem, p, made))
    return sorted(found, key=lambda s: s.made_at, reverse=True)


def _title(playlist: Path) -> str | None:
    try:
        with playlist.open(encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(5), f, strict=False):
                if line.startswith("#PLAYLIST:"):
                    return line[len("#PLAYLIST:") :].strip() or None
    except OSError:
        return None
    return None


def remove(out_root: Path, show_id: str) -> bool:
    """Delete a show's playlist and its breaks (never the user's music). False when there's no such show."""
    root = out_root.resolve()
    gone = False
    for s in shows(root):
        if s.show_id != show_id:
            continue
        for line in s.playlist.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#"):
                continue
            p = Path(line)
            breaks = p.parent
            if breaks.parent == root / BREAKS and breaks.resolve().is_relative_to(root / BREAKS):
                shutil.rmtree(breaks, ignore_errors=True)
                break
        s.playlist.unlink(missing_ok=True)
        gone = True
    return gone
