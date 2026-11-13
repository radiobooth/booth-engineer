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
from mutagen.id3 import APIC, CHAP, CTOC, ID3, TALB, TIT2, TPE1, TXXX, CTOCFlags

RATE = 44100
LAYOUT = "stereo"
FORMAT = "s16"  # what each item is held as between its passes: half the memory of floats
BYTES = 4  # per sample frame of s16 stereo
BITRATE = 192_000
TARGET = -14.0  # LUFS every song and break is brought towards
MAX_BOOST = 6.0  # dB: a quiet master is raised at most this much, and never past its peak
PEAK = -1.0  # dBTP a raised item's true peak stays under
SILENCE = "n=-50dB:d=0.3"  # what counts as dead air at an item's edges
SONG_FADE = 4.0  # seconds songs overlap
BREAK_IN = 1.5  # the DJ starts this long before a song ends
BREAK_OUT = 1.0  # the next song starts this long before the DJ finishes
MARK = "BOOTH-SHOW"


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


def decode(path: Path) -> Iterator[av.AudioFrame]:
    """The file's first audio stream as s16 stereo frames at RATE."""
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format=FORMAT, layout=LAYOUT, rate=RATE)
        for frame in container.decode(stream):
            yield from resampler.resample(frame)
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


def _trimmed(frames: Iterable[av.AudioFrame], start: int, stop: int) -> Iterator[av.AudioFrame]:
    """The samples start..stop of an item, as frames (s16 stereo is one plane of BYTES per sample)."""
    at = 0
    for f in frames:
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
    # A very short item can't be overlapped by more than half of itself.
    how = [(k, min(s, heard[i] / 2, heard[i + 1] / 2), c1, c2) for i, (k, s, c1, c2) in enumerate(how)]

    graph = av.filter.Graph()
    sources, chain = [], None
    for i, (_item, m) in enumerate(ready):
        src = _abuffer(graph)
        sources.append(src)
        vol = graph.add("volume", f"volume={gain(m)}dB")
        src.link_to(vol)
        if chain is None:
            chain = vol
            continue
        kind, secs, c1, c2 = how[i - 1]
        if kind == "concat":
            join = graph.add("concat", "n=2:v=0:a=1")
        else:
            join = graph.add("acrossfade", f"d={secs}:c1={c1}:c2={c2}")
        chain.link_to(join, 0, 0)
        vol.link_to(join, 0, 1)
        chain = join
    limit = graph.add("alimiter", "limit=0.95:level=false")
    fmt = graph.add("aformat", "sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo")
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
                lead = m.lead if i > 0 and how[i - 1][0] != "concat" else 0
                tail = m.tail if i < len(how) and how[i][0] != "concat" else 0
                stop = max(m.samples - tail, lead + 1)
                pts = 0
                try:
                    for f in _trimmed(decode(item.path), lead, stop):
                        f.pts, f.time_base = pts, Fraction(1, RATE)
                        pts += f.samples
                        sources[i].push(f)
                        flush()
                except (OSError, av.error.FFmpegError, IndexError) as e:
                    raise RenderError(f"{item.path.name} couldn't be read while mixing ({e}).") from None
                lengths.append(pts)
                sources[i].push(None)
                flush()
            flush()
            container.mux(stream.encode(None))
        _tag(
            partial,
            title=title,
            artist=artist,
            show_id=show_id,
            cover=cover,
            chapters=_chapters(kept, lengths, how),
        )
        os.replace(partial, out)
    finally:
        partial.unlink(missing_ok=True)
    if progress:
        progress(2 * len(items), 2 * len(items))
    seconds = sum(lengths) / RATE - sum(h[1] for h in how)
    return Rendered(out, seconds, len(ready), skipped)


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


def from_playlist(playlist: Path) -> tuple[list[Item], dict]:
    """The items a Booth playlist plays, and what the show file is called and tagged with."""
    from mutagen import File as AudioFile

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
                try:
                    found = AudioFile(str(path))
                except Exception:  # noqa: BLE001  # a file that can't be read is left out when rendering
                    found = None
                if found is not None and hasattr(found.tags, "getall"):
                    pics = found.tags.getall("APIC")
                    cover = pics[0].data if pics else None
        else:
            try:
                fields = tag_reader.read(path).fields
            except Exception:  # noqa: BLE001  # a file that can't be read is left out when rendering
                fields = {}
            if fields.get("album"):
                lead = fields.get("album_artist") or fields.get("artist")
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
