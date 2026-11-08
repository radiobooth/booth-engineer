# Booth Engineer

Home client for Radio Booth. Python package `radiobooth`, command `booth`, managed with uv.

- Run checks before pushing: `uv run ruff check && uv run ruff format --check && uv run pytest`.
- Outbound connections only: nothing may require the user to open a port on their router or firewall, and
  nothing on the network may reach Booth. The one exception is Booth's own page, served on 127.0.0.1 only
  (never 0.0.0.0 or a LAN address), locked with the page key and Host/Origin checks (see `web.py`).
- Only metadata leaves the user's machine, and only what `protocol/` documents. Never upload audio.
- Code is split by music source (`sources/`) and delivery target (`targets/`). Plex is the launch target.
- Keep dependencies few: this ships via `uv tool install radiobooth` and a GHCR image.
- Dependency cooldown (supply-chain safety): never adopt a package, GitHub Action, tool or image version published
  less than 7 days ago. `exclude-newer = "7 days"` in `pyproject.toml` enforces it for Python packages; override
  it with `exclude-newer-package` only when Thomas says so (e.g. an urgent security fix). Actions are pinned by
  commit SHA and uv/tool versions are pinned exactly: bump those only to releases at least 7 days old.
- No secrets in the repo. Plex tokens and pairing tokens come from the environment or local config.
- Open source, closed contribution: don't add contributor tooling that invites PRs.
- Radio jargon is fine in code names; user-facing text says "Booth", "show", "break", "DJ".
