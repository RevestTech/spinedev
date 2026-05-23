# spine_watcher - drains per-role outbox.jsonl files into Postgres.
#
# Built and run from db/docker-compose.yml as the "watcher" service.
# The container mounts the team workspace read-only and connects to the
# postgres service over the spine_net network.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root runtime user. The watcher only needs to READ the mounted
# team dir and TALK to postgres; nothing it does requires root.
RUN groupadd --system --gid 10001 spine \
 && useradd  --system --uid 10001 --gid spine --home-dir /app --shell /usr/sbin/nologin spine \
 && mkdir -p /app /spine-cursors \
 && chown -R spine:spine /app /spine-cursors

# Pre-creating /spine-cursors with `spine` ownership matters: when docker
# attaches a fresh named volume at this path it copies the image's directory
# ownership onto the new volume. Without this, the volume mounts root-owned
# and the watcher silently fails to persist cursor state (every tick
# re-ingests the same outbox lines, producing duplicate events).

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY spine_watcher.py /app/spine_watcher.py
RUN chown spine:spine /app/spine_watcher.py

USER spine

# Lightweight liveness check: shell echo "ok". The watcher's real
# health signal is its log stream + cursor advancement; a fancier check
# would need a sidecar HTTP server, which we don't want here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD echo ok || exit 1

CMD ["python", "-u", "/app/spine_watcher.py"]
