<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-horizontal-on-dark.svg">
  <img alt="Radio Booth" src="docs/images/logo-horizontal-on-light.svg" width="280">
</picture>

# Booth Engineer

The home client for **Radio Booth**: personal radio shows made from the music you own, with an AI DJ
talking between songs.

Booth Engineer runs next to your music server (Plex first). When you ask for a show, it reads your library's
metadata and sends it to the Booth DJ service, picks up the finished show, puts the DJ breaks where your
server can see them and builds the playlist. It only makes outbound connections, your music never leaves your machine, and your server is never
exposed to the internet.

Status: early development. Exactly what is sent, and when, is in [`protocol/`](protocol/).

## Using it

**Setting it up for the first time?** Follow [docs/getting-started.md](docs/getting-started.md): download
the app for Windows or macOS (or `booth setup` if you installed the command), and it walks you through
signing in to Plex and connecting to your Booth account. It saves its settings in the config file below, so
nothing needs to be set in the environment.

**Plex on another computer, Linux, Docker or an Intel Mac?** See
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

So new shows don't repeat what you've just heard, Booth Engineer remembers which tracks were in the shows it
delivered, in `history.json` next to its config file (normally `~/.config/radiobooth/`). That history stays
on your machine except inside a show's catalog. Delete the file to start over.

## Development

```sh
uv sync
uv run booth --help
uv run pytest
uv run ruff check && uv run ruff format --check
```

## License

Apache-2.0. This project is open source but not open to contributions; see [CONTRIBUTING.md](CONTRIBUTING.md).
