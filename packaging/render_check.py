"""Check a packaged app can make a one-file show: it must carry FFmpeg, its MP3 encoder and the filters.

python packaging/render_check.py make DIR   writes a two-song show (tones) into DIR
python packaging/render_check.py check DIR  checks DIR/show.mp3, which the packaged app rendered from it
"""

import math
import sys
from array import array
from pathlib import Path

import av
from mutagen.mp3 import MP3


def tone(path: Path, codec: str, freq: float) -> None:
    rate, n = 44100, 44100 * 5
    samples = array("h", (int(9000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))
    with av.open(str(path), "w") as container:
        stream = container.add_stream(codec, rate=rate, layout="mono")
        frame = av.AudioFrame(format="s16", layout="mono", samples=n)
        frame.sample_rate = rate
        frame.planes[0].update(samples.tobytes())
        frame.pts = 0
        container.mux(stream.encode(frame))
        container.mux(stream.encode(None))


def main(action: str, folder: str) -> None:
    d = Path(folder)
    if action == "make":
        d.mkdir(parents=True, exist_ok=True)
        tone(d / "one.flac", "flac", 440)
        tone(d / "two.mp3", "libmp3lame", 550)
        (d / "show.m3u8").write_text(
            "#EXTM3U\n#PLAYLIST:Check\n#BOOTH-SHOW:show_check\n#EXTINF:5,One\none.flac\n#EXTINF:5,Two\ntwo.mp3\n",
            encoding="utf-8",
        )
        return
    made = MP3(str(d / "show.mp3"))
    chapters = made.tags.getall("CHAP")
    if len(chapters) != 2 or not 5 < made.info.length < 10:
        raise SystemExit(f"Bad one-file show: {made.info.length:.1f} s, {len(chapters)} chapters.")
    print(f"One-file show OK: {made.info.length:.1f} s, {len(chapters)} chapters.")


if __name__ == "__main__":
    main(*sys.argv[1:3])
