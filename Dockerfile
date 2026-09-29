# --- build stage: install the package into a self-contained venv -------------
FROM python:3.12-alpine AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /src

# Only what the build backend needs, so a source-only change does not
# invalidate the dependency layer. Every runtime dependency is pure Python, so
# no toolchain is needed even on musl.
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir .

# --- runtime stage: just the venv, on a non-root user ------------------------
FROM python:3.12-alpine AS runtime

LABEL org.opencontainers.image.title="quakewatch" \
      org.opencontainers.image.description="Monitor recent earthquakes from the USGS and EMSC catalogs." \
      org.opencontainers.image.source="https://github.com/fregas/agentbench-quakewatch-v2-01-a" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=build /opt/venv /opt/venv

# A dedicated unprivileged user, with a writable home for the response cache.
RUN adduser -D -u 10001 -h /home/quakewatch -s /sbin/nologin quakewatch \
 && mkdir -p /home/quakewatch/.cache/quakewatch \
 && chown -R quakewatch:quakewatch /home/quakewatch

USER quakewatch
WORKDIR /home/quakewatch

ENTRYPOINT ["quakewatch"]
CMD ["--help"]
