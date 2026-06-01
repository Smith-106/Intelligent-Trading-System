FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" || pip install --no-cache-dir \
    ccxt pandas numpy pyyaml duckdb optuna pyarrow pydantic typer rich \
    redis prometheus-client structlog scikit-learn aiohttp \
    pytest pytest-asyncio pytest-cov ruff mypy scipy

COPY . .

EXPOSE 8000

CMD ["quantflow", "run", "--mode", "paper"]
