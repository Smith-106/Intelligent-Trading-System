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

EXPOSE 8000

CMD ["quantflow", "run", "--mode", "paper", "--interval", "60"]
