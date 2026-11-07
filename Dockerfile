FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.33 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH"
# Plex answering on 127.0.0.1 (host networking) still isn't "on this computer": it can't see our folders.
ENV BOOTH_IN_CONTAINER=1
ENTRYPOINT ["booth"]
# Pairing settings live here; mount a volume so they survive restarts.
ENV BOOTH_CONFIG=/config/config.json
VOLUME /config
CMD ["run"]
