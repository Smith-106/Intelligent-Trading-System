FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

# Package metadata and source
COPY pyproject.toml README.md ./
COPY quantflow ./quantflow

# Runtime deps
RUN pip install --no-cache-dir .

# Runtime assets
COPY docker ./docker
COPY scripts ./scripts

# ISS-005 (SEC-012): run as a non-root user so a container escape / RCE inside
# the process does not immediately have root privileges over the filesystem.
RUN groupadd --system --gid 1001 quantflow \
    && useradd --system --uid 1001 --gid quantflow --no-create-home --home-dir /app quantflow \
    && chown -R quantflow:quantflow /app
USER quantflow

EXPOSE 8000

CMD ["quantflow", "run", "--mode", "paper", "--interval", "60"]
