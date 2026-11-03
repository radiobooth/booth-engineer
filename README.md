# Booth Engineer

The home client for **Radio Booth**: personal radio shows made from the music you own, with an AI DJ
talking between songs.

Booth Engineer runs next to your music server (Plex first). It reads your library's metadata, sends it to the
Booth DJ service, picks up finished shows, puts the DJ breaks where your server can see them and builds the
playlist. It only makes outbound connections, your music never leaves your machine, and your server is never
exposed to the internet.

Status: early development. Nothing works yet.

## Development

```sh
uv sync
uv run booth --help
uv run pytest
uv run ruff check && uv run ruff format --check
```

## License

Apache-2.0. This project is open source but not open to contributions; see [CONTRIBUTING.md](CONTRIBUTING.md).
