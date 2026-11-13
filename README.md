<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-horizontal-on-dark.svg">
  <img alt="Radio Booth" src="docs/images/logo-horizontal-on-light.svg" width="280">
</picture>

# Booth Engineer

The home client for **Radio Booth**: personal radio shows made from the music you own, with an AI DJ
talking between songs.

Booth Engineer runs next to your music: in Plex, or in a plain folder of music files. When you ask for a
show, it reads your library's metadata and sends it to the Booth DJ service, picks up the finished show, puts
the DJ breaks where your player can see them and builds the playlist. It only makes outbound connections, your music never leaves your machine, and your server is never
exposed to the internet.

Status: early development. Exactly what is sent, and when, is in [`protocol/`](protocol/).

## Using it

**Setting it up for the first time?** Follow [docs/getting-started.md](docs/getting-started.md): download
the app for Windows or macOS and open it. Booth opens its page in your browser, which walks you through
choosing your music (signing in to Plex, or naming your music folder) and connecting to your Booth account, then shows how Booth is doing. The app runs in the
background with no window and keeps itself up to date. With the command installed, `booth app` does the
same, and `booth setup` is the step-by-step version in the terminal. Either saves its settings in the config
file below, so nothing needs to be set in the environment.

Booth's page is served only to this computer (on 127.0.0.1, behind a random key the app hands your
browser); nothing on your network can reach it.

**Plex on another computer, Linux or Docker?** See
[docs/other-setups.md](docs/other-setups.md).

### By hand

Every setting can also come from the environment, which wins over the config file. You need a Plex music library of its own for the DJ breaks (so they never mix into your music), and that
library's folder reachable from where Booth Engineer runs.

```sh
export PLEX_URL=http://your-server:32400 PLEX_TOKEN=...      # your Plex server
export BOOTH_MUSIC_LIBRARY="Music"                             # if Plex has more than one music library
export BOOTH_BREAKS_LIBRARY="Radio Booth"                      # the Plex library for breaks
export BOOTH_BREAKS_DIR=/path/to/that/library/folder           # the same folder, as seen from here

booth pair --server https://...   # once: asks for the code from the Booth page on your phone
booth run                         # stays connected; leave it running
```

`booth index` writes your catalog to a file so you can see exactly what would be sent, and
`booth deliver` puts a show folder into Plex by hand.

### Music in a folder

Booth can use a plain folder of music files (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV, AIFF) instead of Plex:
on Booth's page, choose **It's in a folder** and name your music folder and a folder for your shows. Each show
arrives there as an `.m3u8` playlist, with its DJ breaks in `breaks/` beside it, so any player that opens
playlists plays it (foobar2000, MusicBee, VLC, Winamp, Music on a Mac). The playlist points at your music
where it is: Booth only reads your files, and never changes, moves, renames or uploads them. **Remove** on
Booth's page deletes a show's playlist and breaks. **Copy to a folder** copies a show whole into
`Copies/<title>/` in the shows folder: its songs and breaks as numbered files in playing order, plus a
playlist, to put on a phone, a USB stick or a car's drive. **Make one file** mixes a show into one MP3,
`Copies/<title>.mp3`, the way it sounds on the radio: levels evened, songs crossfaded (the next track of the
same album stays gapless), the DJ talking over the ends and starts of songs, and a chapter for each song and
break. It's made on your computer; nothing is uploaded.

The same three buttons sit under shows delivered to Plex. **Remove** deletes the show's Plex playlist and its
breaks. **Copy to a folder** and **Make one file** fetch the show's songs from your Plex server to this
computer and write the copy into `Copies/` in the `Booth shows` folder in your home folder.

Booth reads the folder's tags when you set it up (with a progress bar: the first read of a big collection
takes a while) and again when Booth starts and for each show, reading only files that are new or changed. It
keeps what it read in an index next to its config file (`folders/`). Booth's page shows what it found in your
tags: how many tracks it can use, which files it left out and why, and how much of the library has years,
genres and other details. `booth scan ~/Music` prints the same report; add `--catalog catalog.json` to see
exactly what would be sent. By hand, set `BOOTH_SOURCE=folder`, `BOOTH_MUSIC_FOLDER` and
`BOOTH_SHOWS_FOLDER` instead of the Plex settings above.

So new shows don't repeat what you've just heard, Booth Engineer remembers which tracks were in the shows it
delivered, in `history.json` next to its config file (normally `~/.config/radiobooth/`), and in
`history-<id>.json` for each other person sharing this Booth (see below). That history stays
on your machine except inside a show's catalog. Delete the file to start over.

Someone with their own Radio Booth account can share this Booth: on Booth's page, under **Settings**, click
**Add another person** and type the pairing code from their phone. Their shows come from the same music and go
to the same place (Plex, or the shows folder), with their name at the start of each playlist's title, and
count against their own show time. With Plex, pick their Plex user next to their name and Booth shares each of
their new playlists with them in Plex.
`booth run` makes shows for everyone added there.

## Development

```sh
uv sync
uv run booth --help
uv run pytest
uv run ruff check && uv run ruff format --check
```

## License

Copyright © 2026 Thomas Bohmbach, Jr.

Booth Engineer is licensed under the GNU General Public License, version 3 or later ([LICENSE](LICENSE)).
Code published here up to commit 2349c50 (the last before this license change), including every release up
to v0.2.6, was released under Apache-2.0 and stays available under it for anyone who has it. The packaged
apps also contain Python, the PyInstaller bootloader and mutagen, whose licenses are in `NOTICES-*.txt` next to the
downloads and inside the apps (`booth license` shows them).

The protocol schemas and API docs in [`protocol/`](protocol/) are Apache-2.0 ([protocol/LICENSE](protocol/LICENSE)),
so anyone can build a compatible client or server under any license.

This project is open source but not open to contributions; see [CONTRIBUTING.md](CONTRIBUTING.md).
