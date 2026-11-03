# Booth Engineer

Home client for Radio Booth. Python package `radiobooth`, command `booth`, managed with uv.

- Run checks before pushing: `uv run ruff check && uv run ruff format --check && uv run pytest`.
- Outbound connections only. Never open a listening port.
- Only metadata leaves the user's machine, and only what `protocol/` documents. Never upload audio.
- Code is split by music source (`sources/`) and delivery target (`targets/`). Plex is the launch target.
- Keep dependencies few: this ships via `uv tool install radiobooth` and a GHCR image.
- No secrets in the repo. Plex tokens and pairing tokens come from the environment or local config.
- Open source, closed contribution: don't add contributor tooling that invites PRs.
- Radio jargon is fine in code names; user-facing text says "Booth", "show", "break", "DJ".
