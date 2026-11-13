"""One-file shows: songs and breaks mixed into a single MP3 with chapters."""

import array
import math

import av
import pytest
from mutagen.mp3 import MP3

from radiobooth import render


def tone(path, codec, secs, freq, amp, rate=48000, layout="mono", silence_end=0.0):
    """A sine tone of `amp` (0..1), ending in `silence_end` seconds of silence."""
    channels = 1 if layout == "mono" else 2
    n, quiet = int(secs * rate), int(silence_end * rate)
    samples = array.array(
        "h",
        (
            int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)) if i < n - quiet else 0
            for i in range(n)
            for _ in range(channels)
        ),
    )
    with av.open(str(path), "w") as container:
        stream = container.add_stream(codec, rate=rate, layout=layout)
        frame = av.AudioFrame(format="s16", layout=layout, samples=n)
        frame.sample_rate = rate
        frame.planes[0].update(samples.tobytes())
        frame.pts = 0
        container.mux(stream.encode(frame))
        container.mux(stream.encode(None))
    return path


def test_measure_reads_level_and_trailing_silence(tmp_path):
    m = render.measure(tone(tmp_path / "a.flac", "flac", 6, 440, 0.05, silence_end=2))
    assert m.loudness is not None and m.loudness < -25
    assert abs(m.tail / render.RATE - 2) < 0.1
    assert m.lead == 0


def test_gain_cuts_freely_and_boosts_within_peak():
    loud = render.Measured(1, loudness=-6.0, peak=-0.1)
    quiet = render.Measured(1, loudness=-30.0, peak=-12.0)
    hot_quiet = render.Measured(1, loudness=-20.0, peak=-0.5)
    assert render.gain(loud) == -8.0
    assert render.gain(quiet) == render.MAX_BOOST
    assert render.gain(hot_quiet) == 0.0  # already near its peak: left alone, never cut for being quiet


def test_gapless_album_tracks_share_one_gain():
    soft = render.Measured(100, loudness=-24.0, peak=-12.0)  # a quiet intro, running straight into
    loud = render.Measured(100, loudness=-10.0, peak=-0.5)  # the loud track after it
    other = render.Measured(100, loudness=-10.0, peak=-0.5)
    a1 = render.Item(None, "a1", album="X|Y", track=1)
    a2 = render.Item(None, "a2", album="X|Y", track=2)
    brk = render.Item(None, "break", kind="break")
    levels = render.gains([a1, a2, brk, render.Item(None, "b")], [soft, loud, soft, other])
    assert levels[0] == levels[1] < 0  # one cut for the pair, so nothing jumps between them
    assert levels[2:] == [render.MAX_BOOST, render.gain(other)]  # others each get their own


def test_joins():
    a1 = render.Item(None, "a1", album="X|Y", track=1)
    a2 = render.Item(None, "a2", album="X|Y", track=2)
    other = render.Item(None, "other")
    brk = render.Item(None, "break", kind="break")
    brk2 = render.Item(None, "break 2", kind="break")
    assert [j[0] for j in render.joins([a1, a2, other, brk, brk2, a1])] == [
        "concat",  # next track of the same album stays gapless
        "acrossfade",
        "acrossfade",
        "concat",
        "acrossfade",
    ]
    assert render.joins([other, brk])[0][2:] == ("qsin", "nofade")  # the DJ never fades in
    assert render.joins([brk, other])[0][2:] == ("nofade", "qsin")  # or out


def test_render_mixes_a_show_with_chapters(tmp_path):
    a = tone(tmp_path / "a.flac", "flac", 8, 440, 0.05, silence_end=2)
    b = tone(tmp_path / "b.mp3", "libmp3lame", 6, 660, 0.6, rate=44100, layout="stereo")
    brk = tone(tmp_path / "break.mp3", "libmp3lame", 4, 220, 0.3, rate=24000)
    c = tone(tmp_path / "c.m4a", "aac", 6, 550, 0.3)
    bad = tmp_path / "bad.flac"
    bad.write_bytes(b"not audio")
    items = [
        render.Item(a, "A song", album="X|Y", track=1),
        render.Item(b, "B song", album="X|Y", track=2),
        render.Item(brk, "Penrose - Break 1", kind="break"),
        render.Item(bad, "Broken"),
        render.Item(c, "C song"),
    ]
    seen = []
    out = tmp_path / "show.mp3"
    result = render.render(
        items,
        out,
        title="Test show",
        artist="Penrose",
        show_id="show_abc",
        progress=lambda *p: seen.append(p),
    )

    assert result.items == 4 and result.skipped == [str(bad)]
    assert seen[-1] == (10, 10)
    assert not list(tmp_path.glob("*.partial"))
    mp3 = MP3(str(out))
    # a: 8s gapless into b: 6s, 1.5s under the break: 4s, 1s under c: 6s
    assert abs(mp3.info.length - (8 + 6 - 1.5 + 4 - 1 + 6)) < 0.2
    chapters = sorted(mp3.tags.getall("CHAP"), key=lambda f: f.start_time)
    assert [str(f.sub_frames["TIT2"]) for f in chapters] == [
        "A song",
        "B song",
        "Penrose - Break 1",
        "C song",
    ]
    assert [round(f.start_time / 1000, 1) for f in chapters] == [0.0, 8.0, 12.5, 15.5]
    assert chapters[-1].end_time == round(result.seconds * 1000)
    assert mp3.tags.getall("TXXX")[0].text == ["show_abc"]
    assert str(mp3.tags["TIT2"]) == "Test show"


def test_render_evens_levels(tmp_path):
    soft = tone(tmp_path / "soft.flac", "flac", 6, 440, 0.3)
    loud = tone(tmp_path / "loud.flac", "flac", 6, 440, 0.9)
    out = tmp_path / "show.mp3"
    render.render(
        [render.Item(soft, "soft"), render.Item(loud, "loud")], out, title="t", artist="a", show_id="s"
    )
    levels = []
    for start, stop in ((0.5, 1.5), (6.5, 7.5)):  # either side of the 4s crossfade
        frames = list(render.decode(out))
        whole = b"".join(bytes(f.planes[0])[: f.samples * render.BYTES] for f in frames)
        part = array.array(
            "f", whole[int(start * render.RATE) * render.BYTES : int(stop * render.RATE) * render.BYTES]
        )
        levels.append(20 * math.log10(math.sqrt(sum(s * s for s in part) / len(part))))
    assert abs(levels[0] - levels[1]) < 1.0


def test_render_fails_without_songs(tmp_path):
    bad = tmp_path / "bad.flac"
    bad.write_bytes(b"not audio")
    with pytest.raises(render.RenderError):
        render.render([render.Item(bad, "Broken")], tmp_path / "show.mp3", title="t", artist="a", show_id="s")


def test_one_file_lands_in_copies_and_goes_with_remove(tmp_path):
    from radiobooth.targets import playlist

    shows = tmp_path / "Booth shows"
    breaks = shows / "breaks" / "Night drive"
    breaks.mkdir(parents=True)
    music = tmp_path / "Music"
    music.mkdir()
    tone(music / "one.flac", "flac", 5, 440, 0.3)
    tone(breaks / "01.mp3", "libmp3lame", 3, 220, 0.3, rate=24000)
    lines = [
        "#EXTM3U",
        "#PLAYLIST:Night drive",
        "#BOOTH-SHOW:show_abc",
        "#EXTINF:3,Penrose - Break 1",
        "breaks/Night drive/01.mp3",
        "#EXTINF:5,A - One",
        "../Music/one.flac",
        "#EXTINF:5,A - Gone",
        "../Music/gone.flac",
    ]
    (shows / "Night drive.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")
    other = shows / "Copies" / "Night drive.mp3"  # another show of the same name
    other.parent.mkdir()
    other.write_bytes(b"someone else's")

    made = playlist.one_file(shows, "show_abc")
    assert made.path == shows.resolve() / "Copies" / "Night drive (2).mp3"
    assert made.missing == 1 and abs(made.seconds - (3 + 5 - render.BREAK_OUT)) < 0.2
    assert playlist.file_show(made.path) == "show_abc"
    assert str(MP3(str(made.path)).tags["TPE1"]) == "Penrose"
    assert playlist.one_file(shows, "show_abc").path == made.path  # made again, it replaces itself

    assert playlist.remove(shows, "show_abc")
    assert not made.path.exists() and other.exists()


def test_from_playlist_tells_breaks_by_the_shows_breaks_folder(tmp_path):
    from mutagen.flac import FLAC

    shows = tmp_path / "Booth shows"
    (shows / "breaks" / "Night drive").mkdir(parents=True)
    tone(shows / "breaks" / "Night drive" / "01.mp3", "libmp3lame", 1, 220, 0.3, rate=24000)
    album = tmp_path / "Music" / "breaks" / "Album"  # a music folder that happens to be called breaks
    album.mkdir(parents=True)
    for n in (1, 2):
        song = FLAC(tone(album / f"{n}.flac", "flac", 1, 440, 0.3))
        song.update({"artist": "A", "album": "Y", "tracknumber": f"{n}/9"})
        song.save()
    lines = ["#EXTM3U", "#BOOTH-SHOW:show_abc", "#EXTINF:1,Penrose - Break 1", "breaks/Night drive/01.mp3"]
    lines += ["../Music/breaks/Album/1.flac", "../Music/breaks/Album/2.flac"]
    (shows / "Night drive.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")

    items, show = render.from_playlist(shows / "Night drive.m3u8")
    assert [it.kind for it in items] == ["break", "song", "song"]
    assert [j[0] for j in render.joins(items)][1] == "concat"  # 1 then 2 of the same album
    assert show["artist"] == "Penrose"


def test_a_file_that_fails_while_mixing_is_cut_short_not_the_show(tmp_path, monkeypatch):
    a = tone(tmp_path / "a.flac", "flac", 6, 440, 0.3)
    b = tone(tmp_path / "b.flac", "flac", 6, 550, 0.3)
    c = tone(tmp_path / "c.flac", "flac", 6, 660, 0.3)
    real, calls = render.decode, []

    def flaky(path):
        calls.append(path)
        frames = real(path)
        if path == b and calls.count(b) == 2:  # measured fine, then the share drops while mixing
            yield next(frames)
            raise OSError("Host is down")
        yield from frames

    monkeypatch.setattr(render, "decode", flaky)
    items = [render.Item(a, "A"), render.Item(b, "B"), render.Item(c, "C")]
    made = render.render(items, tmp_path / "show.mp3", title="t", artist="a", show_id="s")
    assert made.skipped == [str(b)] and made.items == 3
    chapters = sorted(MP3(str(made.path)).tags.getall("CHAP"), key=lambda f: f.start_time)
    assert [str(f.sub_frames["TIT2"]) for f in chapters] == ["A", "B", "C"]
    assert abs(MP3(str(made.path)).info.length - made.seconds) < 0.2


def test_a_damaged_stretch_is_skipped_not_the_song(tmp_path):
    song = tone(tmp_path / "a.mp3", "libmp3lame", 10, 440, 0.3, rate=44100, layout="stereo")
    data = bytearray(song.read_bytes())
    for k in range(len(data) // 2, len(data) // 2 + 2000, 7):  # a few frames garbled, as in an old rip
        data[k] ^= 0x5A
    song.write_bytes(bytes(data))
    assert render.measure(song).samples / render.RATE > 9


def test_a_file_whose_format_changes_partway_is_read_whole(tmp_path):
    first = tone(tmp_path / "a.mp3", "libmp3lame", 3, 440, 0.3, rate=44100, layout="stereo")
    second = tone(tmp_path / "b.mp3", "libmp3lame", 3, 440, 0.3, rate=32000, layout="mono").read_bytes()
    size = (second[6] << 21) | (second[7] << 14) | (second[8] << 7) | second[9]  # past its ID3 header
    joined = tmp_path / "joined.mp3"
    joined.write_bytes(first.read_bytes() + second[10 + size :])
    assert abs(render.measure(joined).samples / render.RATE - 6) < 0.2


def test_from_playlist_keeps_a_compilation_gapless(tmp_path):
    from mutagen.flac import FLAC

    shows = tmp_path / "Booth shows"
    shows.mkdir()
    album = tmp_path / "Music" / "Mix"
    album.mkdir(parents=True)
    for n, artist in ((1, "A"), (2, "B")):
        song = FLAC(tone(album / f"{n}.flac", "flac", 1, 440, 0.3))
        song.update({"artist": artist, "album": "Mix", "tracknumber": str(n), "compilation": "1"})
        song.save()
    lines = ["#EXTM3U", "#BOOTH-SHOW:show_abc", "../Music/Mix/1.flac", "../Music/Mix/2.flac"]
    (shows / "Mix.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")

    items, _ = render.from_playlist(shows / "Mix.m3u8")
    assert render.joins(items)[0][0] == "concat"
