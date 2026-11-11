"""Read a folder of music files into a catalog: the music source for listeners without a music server.

Booth only reads: files are opened read-only, nothing in the music folder is written, moved or renamed.
What leaves the computer is the catalog (tags only). Paths, file names, sizes and formats never do, and a
track's id is a keyed hash of its path (the key stays in local settings), so the service can't confirm a
guessed path.

A small SQLite index per music folder, next to Booth's settings, remembers each file's size, modification
time, id and tags, so a rescan only re-reads files that changed. When a file vanishes and one with the same
size, length and names appears, it's taken as moved and keeps its id, and so its show history.

The scan also makes the tag report: what was used and left out, and why, with example paths. It stays on
this computer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from radiobooth.sources import tags as tagreader

# Folders that hold no music of the listener's: NAS thumbnails and recycle bins, OS bookkeeping.
SKIP_DIRS = {"@eadir", "#recycle", "#snapshot", "$recycle.bin", "system volume information", "lost+found"}
DUPLICATE_SECONDS = 2  # copies of one recording can differ this much in length
PLAY_COUNT_SHARE = 0.5  # send play counts only when at least this share of tracks has one

# Why a file was left out, as the tag report says it.
NO_NAMES = "no title or artist tag"
NO_LENGTH = "no audio length"
UNREADABLE = "couldn't be read"
UNSUPPORTED = "a file type Booth can't read yet"
ONE_FILE_ALBUM = "a whole album in one file, with a CUE sheet (not split into tracks yet)"
SAME_NAME = "another file has the same name, written with different accent characters"
READER = 1  # bump when tags.py reads differently, so the index reads every file again

# What each piece of coverage gives the DJ, for the tag report. Keys are tagreader Bag names.
COVERAGE = {
    "date": ("year", "With years, the DJ can place songs in time and pick by decade."),
    "originaldate": (
        "original release year",
        "With original release years, the DJ can say when a song first came out, not when your copy did.",
    ),
    "albumartist": (
        "album artist",
        "With album artists, compilations and guest spots are told apart from an artist's own albums.",
    ),
    "genre": ("genre", "With genres, the DJ can build shows around a sound."),
    "mb_recording": (
        "MusicBrainz ids",
        "With MusicBrainz ids (MusicBrainz Picard writes them), the DJ can look up the exact recording.",
    ),
}


def relative(root: Path, path: Path) -> str:
    """The path inside the music folder, the same on every computer: forward slashes, NFC."""
    return unicodedata.normalize("NFC", path.relative_to(root).as_posix())


def track_id(key: bytes, rel: str) -> str:
    return hmac.new(key, rel.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def index_path(folder: Path, key: bytes, home: Path) -> Path:
    """Where this music folder's index lives: one per folder, named by a keyed hash, not the path."""
    name = hmac.new(key, str(folder).encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return home / "folders" / f"{name}.sqlite"


@dataclass
class Found:
    """One music file as the index knows it."""

    rel: str
    size: int
    mtime: int
    id: str | None = None
    tags: dict | None = None  # tagreader.Tags as a dict; None when unreadable
    problem: str | None = None


@dataclass
class Report:
    """The tag report: what the scan found, kept on this computer."""

    examples: int = 20
    files: int = 0  # music files found
    used: int = 0
    skipped: Counter = field(default_factory=Counter)  # reason -> count
    other_types: Counter = field(default_factory=Counter)  # extension -> count, audio Booth doesn't read
    unopened_folders: int = 0
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (left out, kept)
    from_path: int = 0
    repaired: int = 0
    garbled: int = 0
    play_counts_dropped: int = 0
    coverage: Counter = field(default_factory=Counter)  # Bag name -> tracks that have it
    samples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))  # issue -> paths

    def note(self, issue: str, rel: str) -> None:
        if len(self.samples[issue]) < self.examples:
            self.samples[issue].append(rel)

    def lines(self) -> list[str]:
        """The report as plain lines, for a terminal."""
        out = [f"Music files found: {self.files}. Used: {self.used}."]
        for reason, n in self.skipped.most_common():
            out.append(f"Left out, {reason}: {n}")
            out += [f"    {p}" for p in self.samples[reason]]
        if self.duplicates:
            out.append(
                f"Left out as extra copies of a track: {len(self.duplicates)} (Booth keeps the best copy)"
            )
            out += [f"    {d}  (kept {k})" for d, k in self.duplicates[: self.examples]]
        if self.other_types:
            kinds = ", ".join(f"{ext} {n}" for ext, n in self.other_types.most_common())
            out.append(f"Audio files of types Booth can't read yet: {kinds}")
        if self.unopened_folders:
            out.append(f"Folders Booth wasn't allowed to open: {self.unopened_folders}")
        if self.from_path:
            out.append(
                f"Named from folder and file names (no tags): {self.from_path}. The DJ checks these names"
                " before saying much about them."
            )
            out += [f"    {p}" for p in self.samples["from_path"]]
        if self.repaired:
            out.append(f"Tags stored in the wrong text encoding, read correctly anyway: {self.repaired}")
            out += [f"    {p}" for p in self.samples["repaired"]]
        if self.garbled:
            out.append(f"Tags that look garbled (wrong text encoding), sent as they are: {self.garbled}")
            out += [f"    {p}" for p in self.samples["garbled"]]
        if self.play_counts_dropped:
            out.append(
                f"Play counts left out: only {self.play_counts_dropped} tracks have one, too few to say what"
                " you play most."
            )
        if self.used:
            out.append("Tag coverage:")
            for key, (name, why) in COVERAGE.items():
                share = 100 * self.coverage[key] // self.used
                out.append(f"  {name}: {share}%. {why}")
        return out


def walk(folder: Path, report: Report, skip: list[Path]) -> list[tuple[Path, os.stat_result]]:
    """Every music file under the folder, with its size and time, in a steady order."""
    found = []
    skip_resolved = {s.resolve() for s in skip}

    def refused(_error: OSError) -> None:
        report.unopened_folders += 1

    visited: set[tuple[int, int]] = set()
    # Linked folders are followed (a music folder often links to another drive), each folder once.
    for here, dirs, files in os.walk(folder, onerror=refused, followlinks=True):
        try:
            st = os.stat(here)
        except OSError:
            report.unopened_folders += 1
            dirs[:] = []
            continue
        if (st.st_dev, st.st_ino) in visited:
            dirs[:] = []
            continue
        visited.add((st.st_dev, st.st_ino))
        dirs[:] = sorted(
            d
            for d in dirs
            if not d.startswith(".")
            and d.lower() not in SKIP_DIRS
            and not (skip_resolved and (Path(here) / d).resolve() in skip_resolved)
        )
        files = [f for f in sorted(files) if not f.startswith(".")]  # also macOS "._" files
        # A whole album kept as one file with a CUE sheet: Booth can't split it yet, and one 45-minute
        # "track" doesn't belong in a show. Spotted by the sheet's name, or a lone audio file beside it.
        cues = {os.path.splitext(f)[0].casefold() for f in files if f.lower().endswith(".cue")}
        audio = [f for f in files if os.path.splitext(f)[1].lower() in tagreader.EXTENSIONS]
        for name in files:
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if ext in tagreader.OTHER_AUDIO:
                report.other_types[ext] += 1
            elif ext in tagreader.EXTENSIONS:
                report.files += 1
                path = Path(here) / name
                if cues and (stem.casefold() in cues or len(audio) == 1):
                    report.skipped[ONE_FILE_ALBUM] += 1
                    report.note(ONE_FILE_ALBUM, relative(folder, path))
                    continue
                try:
                    found.append((path, path.stat()))
                except OSError:
                    report.skipped[UNREADABLE] += 1
                    report.note(UNREADABLE, relative(folder, path))
    return found


class Index:
    """The folder's file index (stdlib SQLite)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS files (rel TEXT PRIMARY KEY, size INTEGER, mtime INTEGER,"
            " id TEXT UNIQUE NOT NULL, tags TEXT, problem TEXT)"
        )
        # Tags saved by an older way of reading them are read again (ids are kept).
        self.stale = self.db.execute("PRAGMA user_version").fetchone()[0] != READER

    def close(self) -> None:
        self.db.close()

    def load(self) -> dict[str, Found]:
        rows = self.db.execute("SELECT rel, size, mtime, id, tags, problem FROM files")
        return {r[0]: Found(r[0], r[1], r[2], r[3], json.loads(r[4]) if r[4] else None, r[5]) for r in rows}

    def save(self, files: list[Found], known: dict[str, Found]) -> None:
        """Write what changed since `known` (the index as loaded)."""
        here = {f.rel for f in files}
        changed = [f for f in files if known.get(f.rel) != f]
        with self.db:  # one transaction: an interrupted scan leaves the old index whole
            # Old rows out first, so an id moving from one file to another never meets itself.
            self.db.executemany(
                "DELETE FROM files WHERE rel = ?",
                [(r,) for r in known if r not in here] + [(f.rel,) for f in changed if f.rel in known],
            )
            self.db.executemany(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f.rel, f.size, f.mtime, f.id, json.dumps(f.tags) if f.tags else None, f.problem)
                    for f in changed
                ],
            )
            self.db.execute(f"PRAGMA user_version = {READER}")
        self.stale = False

    def path_of(self, track: str) -> str | None:
        """The file (inside the music folder) a catalog id stands for."""
        row = self.db.execute("SELECT rel FROM files WHERE id = ?", (track,)).fetchone()
        return row[0] if row else None


def _read(path: Path) -> tuple[dict | None, str | None]:
    try:
        t = tagreader.read(path)
    except tagreader.Unreadable as e:
        return None, f"{UNREADABLE}: {e}"
    except Exception as e:  # a damaged file must never stop the scan
        return None, f"{UNREADABLE}: {type(e).__name__}"
    return {
        "fields": t.fields,
        "lossless": t.lossless,
        "bitrate": t.bitrate,
        "release_id": t.release_id,
        "repaired": t.repaired,
        "garbled": t.garbled,
        "seen": sorted(t.seen),
    }, None


def _signature(f: Found):
    """What a moved file still has in common with itself."""
    fields = (f.tags or {}).get("fields", {})
    if not fields.get("duration_ms"):
        return None
    return (f.size, fields["duration_ms"], fields.get("title"), fields.get("artist"), fields.get("album"))


def refresh(
    folder: Path,
    index: Index,
    key: bytes,
    report: Report,
    skip: list[Path] = (),
    progress: Callable | None = None,
) -> list[Found]:
    """Bring the index up to date with the folder and return every music file in it."""
    files = walk(folder, report, list(skip))
    known = index.load()
    current: list[Found] = []
    replaced: dict[tuple, list[Found]] = defaultdict(list)  # files at a known path whose content changed
    rels: set[str] = set()
    for n, (path, st) in enumerate(files, 1):
        if progress:
            progress(n, len(files))
        rel = relative(folder, path)
        if rel in rels:  # "Björk" written two ways (macOS and others), side by side on one disk
            report.skipped[SAME_NAME] += 1
            report.note(SAME_NAME, rel)
            continue
        rels.add(rel)
        old = known.get(rel)
        # A file that couldn't be read is tried again each scan: the problem may have been a dropped share.
        if (
            old
            and old.size == st.st_size
            and old.mtime == st.st_mtime_ns
            and not (old.problem or index.stale)
        ):
            current.append(old)
        else:
            tags, problem = _read(path)
            new = Found(rel, st.st_size, st.st_mtime_ns, old.id if old else None, tags, problem)
            current.append(new)
            if old and (sig := _signature(old)) and sig != _signature(new):
                replaced[sig].append(new)
    # Moves and renames: a file that vanished and one that appeared with the same size, length and names.
    here = {f.rel for f in current}
    gone: dict[tuple, list[str]] = defaultdict(list)
    for f in known.values():
        if f.rel not in here and (sig := _signature(f)):
            gone[sig].append(f.id)
    used = {f.id for f in current if f.id}
    for f in current:
        if f.id is not None or not (sig := _signature(f)):
            continue
        if gone.get(sig):
            f.id = gone[sig].pop(0)
            used.add(f.id)
        elif replaced.get(sig):
            # Moved away, and another file put at its old path: the id goes with the music, and the file
            # now at the old path is new to Booth. (A file only retagged in place keeps its id.)
            other = replaced[sig].pop(0)
            f.id, other.id = other.id, None
    for f in current:
        if f.id is None:
            f.id, n = track_id(key, f.rel), 1
            while f.id in used:  # a new file at a moved file's old path
                f.id, n = track_id(key, f"{f.rel}\0{n}"), n + 1
            used.add(f.id)
    index.save(current, known)
    return current


def from_path(rel: str) -> dict:
    """Names from a clean Artist/Album/NN Title layout, or nothing."""
    parts = rel.split("/")
    if len(parts) != 3:
        return {}
    artist, album, name = parts
    m = re.fullmatch(r"(\d{1,3})\s*[-._ ]\s*(.+)", os.path.splitext(name)[0])
    if not m or not artist.strip() or not album.strip() or not m.group(2).strip():
        return {}
    number = int(m.group(1))
    found = {"artist": artist.strip(), "album": album.strip(), "title": m.group(2).strip()}
    if number >= 1:
        found["track_number"] = number
    return found


def _quality(f: Found) -> tuple:
    t = f.tags or {}
    return (not t.get("lossless"), -t.get("bitrate", 0), len(f.rel), f.rel)


def _copies(tracks: list[tuple[Found, dict]]) -> list[list[tuple[Found, dict]]]:
    """Groups of copies of one recording: same MusicBrainz recording and release, or else the same album
    artist, album, disc, track number and title, with lengths within a couple of seconds."""
    groups: dict[tuple, list[tuple[Found, dict]]] = defaultdict(list)
    for f, t in tracks:
        release = (f.tags or {}).get("release_id")
        if t.get("musicbrainz_id") and release:
            k = ("mb", t["musicbrainz_id"], release)
        elif t.get("album") and t.get("title"):
            fold = lambda v: v.casefold() if isinstance(v, str) else v  # noqa: E731
            names = (t.get("album_artist") or t["artist"], t["album"], t["title"])
            k = ("tags", *map(fold, names), t.get("disc_number"), t.get("track_number"))
        else:
            continue
        groups[k].append((f, t))
    out = []
    for group in groups.values():
        group.sort(key=lambda ft: ft[1]["duration_ms"])
        run = [group[0]]
        for ft in group[1:]:
            if ft[1]["duration_ms"] - run[-1][1]["duration_ms"] <= DUPLICATE_SECONDS * 1000:
                run.append(ft)
            else:
                if len(run) > 1:
                    out.append(run)
                run = [ft]
        if len(run) > 1:
            out.append(run)
    return out


def tracks_of(files: list[Found], report: Report) -> list[dict]:
    """The catalog tracks for the indexed files, noting in the report what was left out and why."""
    usable: list[tuple[Found, dict]] = []
    for f in files:
        if f.tags is None:
            reason = UNSUPPORTED if f.problem and "not a format" in f.problem else UNREADABLE
            report.skipped[reason] += 1
            report.note(reason, f.rel)
            continue
        t = dict(f.tags["fields"])
        if not (t.get("title") and t.get("artist")):
            guess = from_path(f.rel)
            if not guess:
                report.skipped[NO_NAMES] += 1
                report.note(NO_NAMES, f.rel)
                continue
            t = {**{k: v for k, v in guess.items() if not t.get(k)}, **t}
            t["from_path"] = True
        if not t.get("duration_ms"):
            report.skipped[NO_LENGTH] += 1
            report.note(NO_LENGTH, f.rel)
            continue
        if t.get("from_path"):
            report.from_path += 1
            report.note("from_path", f.rel)
        if f.tags.get("repaired"):
            report.repaired += 1
            report.note("repaired", f.rel)
        if f.tags.get("garbled"):
            report.garbled += 1
            report.note("garbled", f.rel)
        usable.append((f, {"id": f.id} | t))
    extra: set[str] = set()
    for group in _copies(usable):
        best = min(group, key=lambda ft: _quality(ft[0]))
        for f, _ in group:
            if f is not best[0]:
                extra.add(f.rel)
                report.duplicates.append((f.rel, best[0].rel))
    kept = [(f, t) for f, t in usable if f.rel not in extra]
    # A few files with play counts (from some old player) would make the rest look never played.
    counted = sum("play_count" in t for _, t in kept)
    if counted and counted < PLAY_COUNT_SHARE * len(kept):
        report.play_counts_dropped = counted
        for _, t in kept:
            t.pop("play_count", None)
    for f, _ in kept:
        report.coverage.update(f.tags.get("seen", []))
    report.used = len(kept)
    return [t for _, t in kept]


def build_catalog(
    folder: str | Path,
    name: str,
    key: bytes,
    home: Path,
    skip: list[Path] = (),
    progress: Callable | None = None,
    examples: int = 20,
) -> tuple[dict, Report]:
    """The catalog for a music folder, and the tag report. `name` is what the service hears the library
    called (never the path, which could hold the listener's user name); `home` is where the index lives."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"No folder at {folder}")
    report = Report(examples=examples)
    index = Index(index_path(folder, key, home))
    try:
        files = refresh(folder, index, key, report, skip, progress)
    finally:
        index.close()
    catalog = {
        "protocol": "radiobooth/catalog@0",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {"kind": "folder", "library": name},
        "tracks": tracks_of(files, report),
    }
    return catalog, report
