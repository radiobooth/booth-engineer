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
import threading
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from radiobooth import catalog as catalogs
from radiobooth import history
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
READERS = 8  # files read at once
# Folder names stand in for missing tags only where at least this share of the tagged files (and at least
# LAYOUT_MIN of them) sit in Artist/Album folders that match their tags.
LAYOUT_SHARE, LAYOUT_MIN = 0.6, 5
READER = 2  # bump when tags.py reads differently, so the index reads every file again

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


def _stat_dir(here: str) -> os.stat_result:
    return os.stat(here)


def walk(folder: Path, report: Report, skip: list[Path]) -> list[tuple[Path, os.stat_result]]:
    """Every music file under the folder, with its size and time, in a steady order."""
    found = []
    skipped = set()  # the folders to leave out, known the way visited ones are (no path work per folder)
    for s in skip:
        try:
            st = _stat_dir(str(s))
        except OSError:
            continue
        skipped.add((st.st_dev, st.st_ino) if st.st_ino else os.path.realpath(s))

    def refused(_error: OSError) -> None:
        report.unopened_folders += 1

    visited: set = set()
    # Linked folders are followed (a music folder often links to another drive), each folder once.
    for here, dirs, files in os.walk(folder, onerror=refused, followlinks=True):
        try:
            st = _stat_dir(here)
        except OSError:
            report.unopened_folders += 1
            dirs[:] = []
            continue
        # Some file systems (FAT, network drives on Windows) report no inode numbers: use the real path.
        seen = (st.st_dev, st.st_ino) if st.st_ino else os.path.realpath(here)
        if seen in visited or seen in skipped:
            dirs[:] = []
            continue
        visited.add(seen)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in SKIP_DIRS)
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
                # OR REPLACE: `booth scan` and the app may read the same folder at once; the last one wins.
                "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f.rel, f.size, f.mtime, f.id, json.dumps(f.tags) if f.tags else None, f.problem)
                    for f in changed
                ],
            )
            self.db.execute(f"PRAGMA user_version = {READER}")
        self.stale = False

    def lookup(self, track: str) -> tuple[str, dict] | None:
        """(the file inside the music folder, its tags) for a catalog id."""
        row = self.db.execute("SELECT rel, tags FROM files WHERE id = ?", (track,)).fetchone()
        if not row:
            return None
        tags = json.loads(row[1]) if row[1] else {}
        return row[0], tags.get("fields", {})


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
    to_read: list[tuple[Path, Found]] = []
    rels: set[str] = set()
    for path, st in files:
        rel = relative(folder, path)
        if rel in rels:  # "Björk" written two ways (macOS and others), side by side on one disk
            report.skipped[SAME_NAME] += 1
            report.note(SAME_NAME, rel)
            continue
        rels.add(rel)
        old = known.get(rel)
        # A file that couldn't be read is tried again each scan: the problem may have been a dropped share.
        if old and (old.size, old.mtime) == (st.st_size, st.st_mtime_ns) and not (old.problem or index.stale):
            current.append(old)
        else:
            f = Found(rel, st.st_size, st.st_mtime_ns)
            current.append(f)
            to_read.append((path, f))
    done = len(current) - len(to_read)
    if progress and done:
        progress(done, len(current))
    # Reading tags waits on the disk (or the network, for a NAS), so a few files are read at once.
    with ThreadPoolExecutor(max_workers=READERS) as pool:
        for (_, f), (tags, problem) in zip(to_read, pool.map(_read, (p for p, _ in to_read)), strict=True):
            f.tags, f.problem = tags, problem
            done += 1
            if progress:
                progress(done, len(current))
    assign_ids(current, known, key)
    index.save(current, known)
    return current


def assign_ids(current: list[Found], known: dict[str, Found], key: bytes) -> None:
    """Give each file its id. Ids go with the music: an unchanged file keeps its id; a file whose content
    matches what another path (or this one) held before takes that id, so moves, renames, swaps and
    renumbering keep each song's show history; a file retagged where it is keeps its own; anything else
    is new to Booth."""
    unchanged = {f.rel for f in current if f.id is not None}
    # Ids whose file vanished or changed are up for grabs, found by what their music was.
    free: set[str] = set()
    by_signature: dict[tuple, list[str]] = defaultdict(list)
    for old in known.values():
        if old.rel not in unchanged:
            free.add(old.id)
            if sig := _signature(old):
                by_signature[sig].append(old.id)

    def take(f: Found, prefer: str | None = None) -> bool:
        ids = [i for i in by_signature.get(_signature(f) or (), []) if i in free]
        if not ids:
            return False
        f.id = prefer if prefer in ids else ids[0]
        free.discard(f.id)
        return True

    changed = [f for f in current if f.id is None and f.rel in known]
    added = [f for f in current if f.id is None and f.rel not in known]
    for f in changed:  # the same path now holding music that was somewhere (or here) before
        take(f, prefer=known[f.rel].id)
    for f in added:  # moved or renamed here
        take(f)
    # Retagged in place: its own id, unless its old music turned up unchanged elsewhere (then the id went
    # with the music, even if that's a copy made before the retag).
    for f in changed:
        if f.id is None and known[f.rel].id in free:
            f.id = known[f.rel].id
            free.discard(f.id)
    used = {f.id for f in current if f.id}
    for f in current:
        if f.id is None:
            f.id, n = track_id(key, f.rel), 1
            while f.id in used or f.id in free:  # never reuse an id another file just had
                f.id, n = track_id(key, f"{f.rel}\0{n}"), n + 1
            used.add(f.id)


def from_path(rel: str) -> dict:
    """Names from the last three parts of a path, Artist/Album/NN Title, or nothing."""
    parts = rel.split("/")
    if len(parts) < 3:
        return {}
    artist, album, name = (p.strip() for p in parts[-3:])
    # "01 Title", "1 - Title", "01. Title", but a bare "50 Ways to Leave Your Lover" keeps its number: a
    # track number without a 0 in front or a mark after it can't be told from the title's own first word.
    m = re.fullmatch(r"(0\d{1,2})\s*[-._ ]\s*(.+)|(\d{1,3})\s*[-._]\s*(.+)", os.path.splitext(name)[0])
    if not m:
        return {}
    number, title = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    title = title.strip()
    for credit in (f"{artist} - ", f"{artist}-"):  # "01 - Nena - 99 Luftballons"
        if title.casefold().startswith(credit.casefold()) and len(title) > len(credit):
            title = title[len(credit) :].strip()
    if not artist or not album or tagreader.placeholder(title):
        return {}
    if tagreader.placeholder(artist) or tagreader.placeholder(album):
        return {}
    found = {"artist": artist, "album": album, "title": title}
    if int(number) >= 1:
        found["track_number"] = int(number)
    return found


def _top(rel: str) -> str:
    """The part of the library a file is in: its top folder when it's deeper than Artist/Album/Track."""
    parts = rel.split("/")
    return parts[0] if len(parts) > 3 else ""


def trusted_layouts(files: list[Found]) -> set[str]:
    """The parts of the library (see _top) whose folders are laid out Artist/Album/Track, learnt from the
    tagged files there: folder names are only trusted where they agree with the listener's own tags."""
    agree, total = Counter(), Counter()
    for f in files:
        t = (f.tags or {}).get("fields", {})
        parts = f.rel.split("/")
        if len(parts) < 3 or not (t.get("artist") and t.get("album")):
            continue
        top = _top(f.rel)
        artist_dir, album_dir = parts[-3].casefold(), parts[-2].casefold()
        names = {t["artist"].casefold(), t.get("album_artist", "").casefold()} - {""}
        total[top] += 1
        if any(n in artist_dir or artist_dir in n for n in names) and t["album"].casefold() in album_dir:
            agree[top] += 1
    return {top for top, n in total.items() if n >= LAYOUT_MIN and agree[top] >= LAYOUT_SHARE * n}


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
    layouts = trusted_layouts(files)
    for f in files:
        if f.tags is None:
            reason = UNSUPPORTED if f.problem and "not a format" in f.problem else UNREADABLE
            report.skipped[reason] += 1
            report.note(reason, f.rel)
            continue
        t = dict(f.tags["fields"])
        if not (t.get("title") and t.get("artist")):
            guess = from_path(f.rel) if _top(f.rel) in layouts else {}
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
    kept = []
    for f, t in usable:
        if f.rel in extra:
            continue
        t, why = catalogs.check_track(t)  # the same check as before upload, so the report matches it
        if t is None:
            report.skipped[f"details the catalog can't hold ({why})"] += 1
            report.note(f"details the catalog can't hold ({why})", f.rel)
            continue
        kept.append((f, t))
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


_scanning = threading.Lock()  # one scan at a time: a second one waits, then finds little left to read


def music_root(folder: str | Path) -> Path:
    """The music folder as the index knows it."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"No folder at {folder}")
    return folder


def open_index(folder: Path, key: bytes, home: Path) -> Index:
    """The index of a music folder (from `music_root`)."""
    return Index(index_path(folder, key, home))


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
    folder = music_root(folder)
    report = Report(examples=examples)
    with _scanning:
        index = open_index(folder, key, home)
        try:
            files = refresh(folder, index, key, report, skip, progress)
        finally:
            index.close()
    catalog = {
        "protocol": "radiobooth/catalog@0",
        "generated_at": history.stamp(),
        "source": {"kind": "folder", "library": name},
        "tracks": tracks_of(files, report),
    }
    return catalog, report
