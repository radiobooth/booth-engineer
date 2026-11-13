"""Deliver a finished show as a playlist file, for music kept in a plain folder.

Each show becomes one .m3u8 playlist in the Booth shows folder, beside a breaks/ folder holding its breaks.
The playlist lists the user's own files where they are (nothing is copied or moved) and the breaks between
them, so any player that opens playlists plays the show: foobar2000, MusicBee, VLC, Winamp, Music on a Mac.
Paths are written relative to the playlist, with forward slashes, whenever the music is on the same drive or
share as the shows folder, so the same playlist plays on any computer that reaches that share.

A playlist names its show on a comment line, so delivering the same show again rewrites its own playlist,
and Booth's page can list and remove shows without keeping a list of its own.

A show can also be copied whole into a folder of its own (`copy_out`): its songs and breaks as numbered files
plus a playlist, to put on a phone, a USB stick or a car's drive, where it plays in order even without the
playlist. Or it can be made into one MP3 (`one_file`), mixed like a radio show with a chapter per song and
break, in the same Copies folder.
"""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from radiobooth import config
from radiobooth.targets.plex import folder_name, load_package

MARK = "#BOOTH-SHOW:"  # show id, on its own line in each playlist Booth writes
BREAKS = "breaks"
COPIES = "Copies"  # in the shows folder: shows copied whole, to take along
FILE_MARK = "BOOTH-SHOW"  # the ID3 TXXX tag a one-file show keeps its show id in
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


def _header(playlist: Path) -> dict[str, str]:
    """The `#PLAYLIST:` title and Booth's show mark from the top of a playlist file, as far as it has them."""
    found = {}
    try:
        with playlist.open(encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(5), f, strict=False):
                for key, start in (("show_id", MARK), ("title", "#PLAYLIST:")):
                    if line.startswith(start) and (value := line[len(start) :].strip()):
                        found[key] = value
    except OSError:
        pass
    return found


def show_of(playlist: Path) -> str | None:
    """The show id a playlist file names, or None for one Booth didn't write."""
    return _header(playlist).get("show_id")


def _line(text: str) -> str:
    """One line of playlist text: no line breaks, whatever a tag holds."""
    return re.sub(r"[\r\n]+", " ", text).strip()


def _ref(path: Path, root: Path) -> str:
    """How the playlist in `root` names a file: relative to it, with forward slashes, so it plays wherever the
    drive or share is reached; the full path when there's no way there from `root` (another Windows drive)."""
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return str(path)
    rel = rel.replace(os.sep, "/")
    return f"./{rel}" if rel.startswith("#") else rel  # a line starting "#" would read as a comment


def _free(folder: Path, base: str, ext: str, mine: Callable[[Path], bool]) -> Path | None:
    """`folder/<base><ext>`, or `<base> (2)<ext>` and so on: the first that's free or already `mine`."""
    for n in range(1, 1000):
        candidate = folder / (f"{base}{ext}" if n == 1 else f"{base} ({n}){ext}")
        if not candidate.exists() or mine(candidate):
            return candidate
    return None


def _place(out_root: Path, title: str, show_id: str) -> Path:
    """The show's playlist file: its own from an earlier delivery, else a free name."""
    base = file_name(title)
    found = _free(out_root, base, ".m3u8", lambda p: show_of(p) == show_id)
    if found is None:
        raise PlaylistError(f"Too many playlists named {base!r} in {out_root}.")
    return found


def _music_file(music_root: Path, rel: str) -> Path | None:
    """The file a track's path inside the music folder names, if it's still there. Linked folders inside the
    music folder are fine (the scan follows them), so this checks the path itself, not where links lead."""
    parts = PurePosixPath(rel).parts
    if not parts or PurePosixPath(rel).is_absolute() or ".." in parts or ":" in parts[0]:
        return None
    path = music_root.joinpath(*parts)
    if path.is_file():
        return path
    # The index keeps names composed (NFC); a disk that doesn't fold names (Linux, most NAS) may hold some
    # of them decomposed, folder by folder, as they were copied from a Mac. Look each part up as it is there.
    here = music_root
    for part in parts:
        if not (here / part).exists():
            try:
                names = [n for n in os.listdir(here) if unicodedata.normalize("NFC", n) == part]
            except OSError:
                return None
            if not names:
                return None
            part = min(names)  # two spellings side by side: the scan used the first, so the same here
        here = here / part
    return here if here.is_file() else None


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
            lines += [f"#EXTINF:{secs},{host} - Break {breaks}", _ref(folder / src.name, root)]
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
        lines += [f"#EXTINF:{secs},{name or path.stem}", _ref(path, root)]
    if not tracks:
        raise PlaylistError("None of this show's tracks are in the music folder any more.")

    folder.mkdir(parents=True, exist_ok=True)
    for src, dest in copies:
        shutil.copyfile(src, dest)
    playlist = _place(root, title, show_id)
    config.write_atomically(playlist, "\n".join(lines) + "\n")
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
        header = _header(p)
        if "show_id" not in header:
            continue
        try:
            made = p.stat().st_mtime
        except OSError:
            continue
        found.append(Show(header["show_id"], header.get("title") or p.stem, p, made))
    return sorted(found, key=lambda s: s.made_at, reverse=True)


def _entries(playlist: Path) -> list[tuple[str, Path]]:
    """What a playlist plays, in order: (its #EXTINF info, "seconds,name"; the file, read relative to the
    playlist)."""
    found, info = [], "-1,"
    for line in playlist.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#EXTINF:"):
            info = line.removeprefix("#EXTINF:").strip()
        elif line.strip() and not line.startswith("#"):
            found.append((info, playlist.parent / line.strip()))
            info = "-1,"
    return found


@dataclass
class Copy:
    folder: Path
    files: int
    missing: int  # files the playlist names that weren't there to copy


def _show(root: Path, show_id: str) -> Show:
    """The show with this id in the shows folder `root`."""
    show = next((s for s in shows(root) if s.show_id == show_id), None)
    if show is None:
        raise PlaylistError("That show isn't in your Booth shows folder any more.")
    return show


def copy_out(out_root: Path, show_id: str, progress: Callable[[int, int], None] | None = None) -> Copy:
    """Copy a show whole into `Copies/<title>/` in the shows folder: each song and break as a numbered file,
    in playing order, and a playlist of them. Copied again, it replaces its own earlier copy."""
    root = out_root.resolve()
    show = _show(root, show_id)
    listed = _entries(show.playlist)
    entries = [(info, path) for info, path in listed if path.is_file()]
    if not entries:
        raise PlaylistError("None of this show's files are there to copy.")
    copies = root / COPIES
    base = file_name(show.title)
    folder = _free(copies, base, "", lambda d: any(show_of(p) == show_id for p in d.glob("*.m3u8")))
    if folder is None:
        raise PlaylistError(f"Too many copies named {base!r} in {copies}.")
    partial = copies / f".{folder.name}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    width = max(2, len(str(len(entries))))
    lines = ["#EXTM3U", f"#PLAYLIST:{_line(show.title)}", f"{MARK}{_line(show_id)}"]
    for n, (info, src) in enumerate(entries, 1):
        if progress:
            progress(n - 1, len(entries))
        label = info.partition(",")[2].strip() or src.stem
        name = f"{n:0{width}d} {file_name(label)}{src.suffix.lower()}"
        shutil.copyfile(src, partial / name)
        lines += [f"#EXTINF:{info}", name]
    (partial / f"{base}.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.rmtree(folder, ignore_errors=True)  # this show's earlier copy
    partial.rename(folder)
    if progress:
        progress(len(entries), len(entries))
    return Copy(folder, len(entries), len(listed) - len(entries))


@dataclass
class OneFile:
    path: Path
    seconds: float
    missing: int  # files the playlist names that weren't there or couldn't be read, left out


def file_show(path: Path) -> str | None:
    """The show id a one-file show was tagged with, or None for any other MP3."""
    from mutagen import MutagenError
    from mutagen.id3 import ID3

    try:
        marks = ID3(str(path)).getall(f"TXXX:{FILE_MARK}")
    except (OSError, MutagenError, ValueError):  # not tagged, or tagged in a way mutagen doesn't read
        return None
    return str(marks[0].text[0]) if marks and marks[0].text else None


def one_file_path(copies: Path, title: str, show_id: str) -> Path:
    """Where a show's one file goes in `copies`: its own from an earlier time, else a free name after its
    title, so it never replaces another show's file."""
    base = file_name(title)
    out = _free(copies, base, ".mp3", lambda p: file_show(p) == show_id)
    if out is None:
        raise PlaylistError(f"Too many files named {base!r} in {copies}.")
    return out


def one_file(out_root: Path, show_id: str, progress: Callable[[int, int], None] | None = None) -> OneFile:
    """Mix a show into one MP3, `Copies/<title>.mp3` in the shows folder, with a chapter per song and break.
    Made again, it replaces its own earlier file."""
    from radiobooth import render

    root = out_root.resolve()
    show = _show(root, show_id)
    items, tags = render.from_playlist(show.playlist)
    listed = len(items)
    items = [it for it in items if it.path.is_file()]
    if not items:
        raise PlaylistError("None of this show's files are there to make it from.")
    copies = root / COPIES
    copies.mkdir(parents=True, exist_ok=True)
    for stale in copies.glob(
        ".*.mp3.partial"
    ):  # left by a render Booth was closed during (one runs at a time)
        stale.unlink(missing_ok=True)
    out = one_file_path(copies, show.title, show_id)
    try:
        made = render.render(items, out, progress=progress, **tags)
    except render.RenderError as e:
        raise PlaylistError(str(e)) from None
    return OneFile(made.path, made.seconds, listed - len(items) + len(made.skipped))


def _drop_copies(copies: Path, show_id: str) -> None:
    """Delete the show's copies in `Copies/` (found by the mark in their playlists) and its one file."""
    try:
        entries = [d for d in copies.iterdir() if not d.name.startswith(".")]
    except OSError:
        return
    for d in entries:
        if d.is_dir() and any(show_of(p) == show_id for p in d.glob("*.m3u8")):
            shutil.rmtree(d, ignore_errors=True)
        elif d.suffix.lower() == ".mp3" and d.is_file() and file_show(d) == show_id:
            d.unlink(missing_ok=True)


def remove(out_root: Path, show_id: str) -> bool:
    """Delete a show's playlist, its breaks and any copy of it (never the user's music). False when there's
    no such show."""
    root = out_root.resolve()
    gone = False
    for s in shows(root):
        if s.show_id != show_id:
            continue
        for line in s.playlist.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#"):
                continue
            breaks = (root / line).parent  # relative to the playlist; older playlists name full paths
            if breaks.parent == root / BREAKS and breaks.resolve().is_relative_to(root / BREAKS):
                shutil.rmtree(breaks, ignore_errors=True)
                break
        s.playlist.unlink(missing_ok=True)
        gone = True
    if gone:
        _drop_copies(root / COPIES, show_id)
    return gone
