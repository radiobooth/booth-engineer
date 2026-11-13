"""Render a show into one MP3 with chapters, on the listener's own computer.

Each song and break is decoded in turn (any format FFmpeg reads, through PyAV), measured for loudness and
for silence at its edges, brought to a common level, and mixed into the next: songs crossfade, the next
track of the same album follows gapless, and the DJ comes in over a song's tail and out under the next song's
intro without fading. FFmpeg does every sample of that work; Python only plans it. The music files are only
read, and nothing leaves the computer.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import av
from mutagen import MutagenError
from mutagen.id3 import APIC, CHAP, CTOC, ID3, TALB, TIT2, TPE1, TXXX, CTOCFlags

from radiobooth.targets.playlist import FILE_MARK as MARK

RATE = 44100
LAYOUT = "stereo"
FORMAT = "flt"  # floats, so a hot master's decoded overs survive until its gain brings them down
BYTES = 8  # per sample frame of packed float stereo
BITRATE = 192_000
TARGET = -14.0  # LUFS every song and break is brought towards
MAX_BOOST = 6.0  # dB: a quiet master is raised at most this much, and never past its peak
PEAK = -1.0  # dBTP a raised item's true peak stays under
SILENCE = "n=-50dB:d=0.3"  # what counts as dead air at an item's edges
SONG_FADE = 4.0  # seconds songs overlap
BREAK_IN = 1.5  # the DJ starts this long before a song ends
BREAK_OUT = 1.0  # the next song starts this long before the DJ finishes


class RenderError(Exception):
    """The show couldn't be rendered."""


@dataclass
class Item:
    path: Path
    title: str  # the chapter's name
    kind: str = "song"  # or "break"
    album: str | None = None  # album artist, album and disc, to tell the next track of the same album
    track: int | None = None


@dataclass
class Measured:
    samples: int  # the item's length, in samples at RATE
    loudness: float | None  # integrated LUFS, None for silence
    peak: float | None  # true peak, dBTP
    lead: int = 0  # samples of silence at the start
    tail: int = 0  # samples of silence at the end


@dataclass
class Rendered:
    path: Path
    seconds: float
    items: int
    skipped: list[str] = field(default_factory=list)  # files that couldn't be read
    chapters: list[tuple[str, int, int]] = field(default_factory=list)  # (title, start ms, end ms)


def decode(path: Path) -> Iterator[av.AudioFrame]:
    """The file's first audio stream as packed float stereo frames at RATE. A damaged stretch is skipped, as
    players skip it, and a file whose format changes partway (joined from two encodes) carries on."""
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        resampler, shape = None, None
        for packet in container.demux(stream):
            try:
                frames = packet.decode()
            except av.error.InvalidDataError:
                continue
            for frame in frames:
                now = (frame.format.name, frame.layout.name, frame.sample_rate)
                if now != shape:  # one resampler takes one input format only
                    if resampler is not None:
                        yield from resampler.resample(None)
                    resampler, shape = av.AudioResampler(format=FORMAT, layout=LAYOUT, rate=RATE), now
                yield from resampler.resample(frame)
        if resampler is not None:
            yield from resampler.resample(None)


def _drain(sink) -> Iterator[av.AudioFrame]:
    while True:
        try:
            yield sink.pull()
        except (BlockingIOError, av.error.EOFError):
            return


def _abuffer(graph: av.filter.Graph):
    return graph.add_abuffer(format=FORMAT, sample_rate=RATE, layout=LAYOUT, time_base=Fraction(1, RATE))


def measure(path: Path) -> Measured:
    """Decode an item and measure it: loudness (EBU R128), true peak, and silence at its edges."""
    graph = av.filter.Graph()
    src = _abuffer(graph)
    meter = graph.add("ebur128", "metadata=1:peak=true")
    quiet = graph.add("silencedetect", SILENCE)
    sink = graph.add("abuffersink")
    src.link_to(meter)
    meter.link_to(quiet)
    quiet.link_to(sink)
    graph.configure()
    samples, meta = 0, {}
    silences: list[list[float | None]] = []

    def take(out: av.AudioFrame) -> None:
        m = out.metadata
        meta.update({k: v for k, v in m.items() if k.startswith("lavfi.r128.")})
        if "lavfi.silence_start" in m:
            silences.append([float(m["lavfi.silence_start"]), None])
        if "lavfi.silence_end" in m and silences:
            silences[-1][1] = float(m["lavfi.silence_end"])

    for frame in decode(path):
        frame.pts, frame.time_base = samples, Fraction(1, RATE)
        samples += frame.samples
        src.push(frame)
        for out in _drain(sink):
            take(out)
    src.push(None)
    for out in _drain(sink):
        take(out)
    if not samples:
        raise RenderError(f"No audio in {path.name}.")
    loud = float(meta["lavfi.r128.I"]) if "lavfi.r128.I" in meta else None
    peak = float(meta.get("lavfi.r128.true_peak", 0))  # linear
    item = Measured(
        samples,
        loud if loud is not None and loud > -70 else None,
        20 * math.log10(peak) if peak > 0 else None,
    )
    if silences and silences[0][0] <= 0.05 and silences[0][1] is not None:
        item.lead = int(silences[0][1] * RATE)
    if silences and silences[-1][1] is None:  # silent through to the end
        item.tail = samples - int(silences[-1][0] * RATE)
    if item.lead + item.tail >= samples:
        item.lead = item.tail = 0
    return item


def gain(m: Measured) -> float:
    """dB to bring an item towards TARGET: cut freely, raise at most MAX_BOOST and never past PEAK."""
    if m.loudness is None:
        return 0.0
    g = TARGET - m.loudness
    if g > 0:
        g = max(0.0, min(g, MAX_BOOST, PEAK - m.peak if m.peak is not None else MAX_BOOST))
    return round(max(g, -30.0), 2)


def gains(items: list[Item], measured: list[Measured]) -> list[float]:
    """dB per item. Songs that play gapless (the next track of the same album) share one gain, from their
    combined loudness and highest peak, so the album's own level changes survive and nothing jumps where
    one track runs into the next."""
    out = [gain(m) for m in measured]
    gapless = [k == "concat" and a.kind == "song" for (k, *_), a in zip(joins(items), items, strict=False)]
    i = 0
    while i < len(items):
        j = i
        while j < len(gapless) and gapless[j]:
            j += 1
        loud = [(m.samples, m.loudness) for m in measured[i : j + 1] if m.loudness is not None]
        if j > i and loud:
            total = sum(n for n, _ in loud)
            level = 10 * math.log10(sum(n * 10 ** (lufs / 10) for n, lufs in loud) / total)
            peaks = [m.peak for m in measured[i : j + 1] if m.peak is not None]
            out[i : j + 1] = [gain(Measured(total, level, max(peaks) if peaks else None))] * (j + 1 - i)
        i = j + 1
    return out


def _quiet(samples: int) -> av.AudioFrame:
    """`samples` of silence, in the mixing format."""
    f = av.AudioFrame(format=FORMAT, layout=LAYOUT, samples=samples)
    f.sample_rate = RATE
    f.planes[0].update(bytes(samples * BYTES))
    return f


def _trimmed(frames: Iterable[av.AudioFrame], start: int, stop: int) -> Iterator[av.AudioFrame]:
    """The samples start..stop of an item, as frames (packed stereo is one plane of BYTES per sample)."""
    at = 0
    for f in frames:
        if at >= stop:  # the rest is the tail left out: no need to decode it
            return
        lo, hi = max(start - at, 0), min(stop - at, f.samples)
        at += f.samples
        if hi <= lo:
            continue
        if lo == 0 and hi == f.samples:
            yield f
            continue
        out = av.AudioFrame(format=FORMAT, layout=LAYOUT, samples=hi - lo)
        out.sample_rate = RATE
        out.planes[0].update(bytes(f.planes[0])[lo * BYTES : hi * BYTES])
        yield out


def joins(items: list[Item]) -> list[tuple[str, float, str, str]]:
    """How each item meets the next: (filter, seconds of overlap, curve out, curve in)."""
    out = []
    for a, b in zip(items, items[1:], strict=False):
        if a.kind == "song" and b.kind == "song":
            same = a.album and a.album == b.album and a.track and b.track == a.track + 1
            out.append(("concat", 0.0, "", "") if same else ("acrossfade", SONG_FADE, "qsin", "qsin"))
        elif a.kind == "song":
            out.append(("acrossfade", BREAK_IN, "qsin", "nofade"))
        elif b.kind == "song":
            out.append(("acrossfade", BREAK_OUT, "nofade", "qsin"))
        else:
            out.append(("concat", 0.0, "", ""))
    return out


def _chapters(items: list[Item], lengths: list[int], how: list) -> list[tuple[str, int, int]]:
    """(title, start ms, end ms) per item: each starts where it begins to be heard."""
    starts, at = [], 0.0
    for i, n in enumerate(lengths):
        starts.append(at)
        at += n / RATE - (how[i][1] if i < len(how) else 0.0)
    ends = starts[1:] + [at]
    return [
        (it.title, round(s * 1000), round(e * 1000)) for it, s, e in zip(items, starts, ends, strict=True)
    ]


def render(
    items: list[Item],
    out: Path,
    *,
    title: str,
    artist: str,
    show_id: str,
    cover: bytes | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Rendered:
    """Render the items, in order, into `out` (an MP3 with a chapter per item). A file that can't be read
    is left out; only a show with nothing left fails."""
    ready: list[tuple[Item, Measured]] = []
    skipped = []
    # First pass: measure every item, so the mix can be planned whole. Items are decoded again in the
    # second pass rather than held, and streamed through both passes, so memory stays small.
    for n, item in enumerate(items):
        if progress:
            progress(n, 2 * len(items))
        try:
            m = measure(item.path)
        except (OSError, av.error.FFmpegError, RenderError, IndexError):
            skipped.append(str(item.path))
            continue
        ready.append((item, m))
    if not any(it.kind == "song" for it, _ in ready):
        raise RenderError("None of this show's songs could be read.")
    kept = [it for it, _ in ready]
    how = joins(kept)
    heard = [(m.samples - m.lead - m.tail) / RATE for _, m in ready]
    # A very short item can't be overlapped by more than half of itself. Overlaps are whole samples, so the
    # crossfade FFmpeg makes is exactly the one the chapters count; one too short to make is a plain join.
    how = [
        (k, math.floor(min(s, heard[i] / 2, heard[i + 1] / 2) * RATE), c1, c2)
        for i, (k, s, c1, c2) in enumerate(how)
    ]
    how = [("concat", 0.0, "", "") if not n else (k, n / RATE, c1, c2) for k, n, c1, c2 in how]

    levels = gains(kept, [m for _, m in ready])

    graph = av.filter.Graph()
    sources, chain = [], None
    for i in range(len(ready)):
        src = _abuffer(graph)
        sources.append(src)
        vol = graph.add("volume", f"volume={levels[i]}dB")
        src.link_to(vol)
        if chain is None:
            chain = vol
            continue
        kind, secs, c1, c2 = how[i - 1]
        if kind == "concat":
            join = graph.add("concat", "n=2:v=0:a=1")
        else:
            join = graph.add("acrossfade", f"ns={round(secs * RATE)}:c1={c1}:c2={c2}")
        chain.link_to(join, 0, 0)
        vol.link_to(join, 0, 1)
        chain = join
    # latency=1: the limiter's lookahead mustn't delay the mix, shifting the chapters and cutting the end
    limit = graph.add("alimiter", "limit=0.95:level=false:latency=1")
    fmt = graph.add("aformat", f"sample_fmts=fltp:sample_rates={RATE}:channel_layouts={LAYOUT}")
    sink = graph.add("abuffersink")
    chain.link_to(limit)
    limit.link_to(fmt)
    fmt.link_to(sink)
    graph.configure()

    partial = out.with_name(f".{out.name}.partial")
    lengths = []
    try:
        with av.open(str(partial), "w", format="mp3") as container:
            stream = container.add_stream("libmp3lame", rate=RATE, layout=LAYOUT)
            stream.bit_rate = BITRATE

            def flush() -> None:
                for f in _drain(sink):
                    f.pts = None
                    container.mux(stream.encode(f))

            for i, (item, m) in enumerate(ready):
                if progress:
                    progress(len(items) + i, 2 * len(items))
                # Dead air goes wherever items overlap, and at the show's very start and end; gapless joins
                # keep theirs.
                lead = m.lead if i == 0 or how[i - 1][0] != "concat" else 0
                tail = m.tail if i == len(how) or how[i][0] != "concat" else 0
                stop = max(m.samples - tail, lead + 1)
                pts = 0
                frames = _trimmed(decode(item.path), lead, stop)
                while True:
                    try:  # only reading the item: a write error below is the output's, not this file's
                        f = next(frames, None)
                    except (OSError, av.error.FFmpegError, IndexError):
                        # It read fine a moment ago (a share dropping, a file being replaced): cut it short
                        # here rather than lose the whole show, with enough quiet for its crossfades.
                        skipped.append(str(item.path))
                        overlap = max(how[i - 1][1] if i else 0.0, how[i][1] if i < len(how) else 0.0)
                        short = max(round(overlap * RATE) * 2 - pts, 0)
                        f, frames = (_quiet(short) if short else None), iter(())
                    if f is None:
                        break
                    f.pts, f.time_base = pts, Fraction(1, RATE)
                    pts += f.samples
                    sources[i].push(f)
                    flush()
                lengths.append(pts)
                sources[i].push(None)
                flush()
            flush()
            container.mux(stream.encode(None))
        chapters = _chapters(kept, lengths, how)
        _tag(partial, title=title, artist=artist, show_id=show_id, cover=cover, chapters=chapters)
        os.replace(partial, out)
    except OSError:
        raise
    except (av.error.FFmpegError, MutagenError) as e:  # encoding or tagging failed, not a disk error
        raise RenderError(f"The show couldn't be mixed ({e}).") from None
    finally:
        partial.unlink(missing_ok=True)
    if progress:
        progress(2 * len(items), 2 * len(items))
    seconds = sum(lengths) / RATE - sum(h[1] for h in how)
    return Rendered(out, seconds, len(ready), skipped, chapters)


def _cue_text(text: str) -> str:
    return " ".join(str(text).replace('"', "'").split())


def write_cue(
    mp3: Path, *, title: str, artist: str, show_id: str, chapters: list[tuple[str, int, int]]
) -> Path:
    """A cue sheet beside the show file, `<name>.cue`, listing each song and break as a track: for players
    that skip by cue sheet rather than by the MP3's own chapters (foobar2000, MusicBee, Winamp, VLC)."""
    lines = [
        f"REM {MARK} {_cue_text(show_id)}",
        f'PERFORMER "{_cue_text(artist)}"',
        f'TITLE "{_cue_text(title)}"',
        f'FILE "{mp3.name}" MP3',
    ]
    for n, (name, start, _end) in enumerate(chapters, 1):
        frames = round(start * 75 / 1000)  # cue sheets count in 1/75 s
        stamp = f"{frames // 4500:02d}:{frames // 75 % 60:02d}:{frames % 75:02d}"
        lines += [f"  TRACK {n:02d} AUDIO", f'    TITLE "{_cue_text(name)}"', f"    INDEX 01 {stamp}"]
    cue = mp3.with_suffix(".cue")
    partial = cue.with_name(f".{cue.name}.partial")
    partial.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
    os.replace(partial, cue)
    return cue


def _tag(path: Path, *, title: str, artist: str, show_id: str, cover: bytes | None, chapters) -> None:
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.add(TALB(encoding=3, text="Booth shows"))
    tags.add(TXXX(encoding=3, desc=MARK, text=show_id))
    if cover:
        mime = "image/png" if cover.startswith(b"\x89PNG") else "image/jpeg"
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover))
    ids = [f"ch{n}" for n in range(len(chapters))]
    tags.add(
        CTOC(
            element_id="toc",
            flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids=ids,
            sub_frames=[TIT2(encoding=3, text=title)],
        )
    )
    for cid, (name, start, end) in zip(ids, chapters, strict=True):
        tags.add(
            CHAP(element_id=cid, start_time=start, end_time=end, sub_frames=[TIT2(encoding=3, text=name)])
        )
    tags.save(path, v2_version=3)


def cover_of(path: Path) -> bytes | None:
    """A file's embedded picture (a break's cover), or None."""
    from mutagen import File as AudioFile

    try:
        found = AudioFile(str(path))
    except Exception:  # noqa: BLE001  # a file that can't be read just has no cover
        return None
    if found is None or not hasattr(found.tags, "getall"):
        return None
    pics = found.tags.getall("APIC")
    return pics[0].data if pics else None


def from_playlist(playlist: Path) -> tuple[list[Item], dict]:
    """The items a Booth playlist plays, and what the show file is called and tagged with."""
    from radiobooth.sources import tags as tag_reader
    from radiobooth.targets import playlist as target

    header = target._header(playlist)
    breaks = (playlist.parent / target.BREAKS).resolve()
    items, dj, cover = [], None, None
    for info, path in target._entries(playlist):
        name = info.partition(",")[2].strip() or path.stem
        is_break = path.parent.parent.resolve() == breaks
        album = track = None
        if is_break:
            dj = dj or name.rpartition(" - Break")[0] or None
            if cover is None:
                cover = cover_of(path)
        else:
            try:
                fields = tag_reader.read(path).fields
            except Exception:  # noqa: BLE001  # a file that can't be read is left out when rendering
                fields = {}
            if fields.get("album"):
                # A compilation's tracks each name their own artist: only its album artist, if any, is shared.
                lead = fields.get("album_artist") or (
                    "" if fields.get("compilation") else fields.get("artist")
                )
                album = f"{lead}|{fields['album']}|{fields.get('disc_number') or 1}"
            track = fields.get("track_number")
        items.append(Item(path, name, "break" if is_break else "song", album, track))
    show = {
        "title": header.get("title") or playlist.stem,
        "show_id": header.get("show_id") or "",
        "artist": dj or "Booth",
        "cover": cover,
    }
    return items, show
