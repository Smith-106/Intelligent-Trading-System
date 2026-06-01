#!/usr/bin/env python3
"""Pre-flight check — verify environment before starting QuantFlow."""

import sys


def check_python_version():
    print(f"OK: Python {sys.version_info.major}.{sys.version_info.minor}")
    return True


def check_dependencies():
    required = {
        "ccxt": "ccxt",
        "pandas": "pandas",
        "numpy": "numpy",
        "duckdb": "duckdb",
        "pyarrow": "pyarrow",
        "pydantic": "pydantic",
        "typer": "typer",
        "rich": "rich",
        "yaml": "pyyaml",
        "optuna": "optuna",
        "pandas_ta": "pandas-ta",
        "prometheus_client": "prometheus-client",
    }
    optional = {
        "vectorbt": "vectorbt",
        "redis": "redis",
        "structlog": "structlog",
        "scipy": "scipy",
        "sklearn": "scikit-learn",
        "transformers": "transformers",
        "torch": "torch",
        "aiohttp": "aiohttp",
    }

    all_ok = True
    for module, package in required.items():
        try:
            __import__(module)
            print(f"  OK: {package}")
        except ImportError:
            print(f"  MISSING: {package} (required)")
            all_ok = False

    for module, package in optional.items():
        try:
            __import__(module)
            print(f"  OK: {package} (optional)")
        except ImportError:
            print(f"  SKIP: {package} (optional, not installed)")

    return all_ok


def check_env_vars():
    import os
    vars_to_check = [
        ("OKX_API_KEY", False),
        ("OKX_SECRET", False),
        ("OKX_PASSPHRASE", False),
        ("TELEGRAM_BOT_TOKEN", False),
    ]
    for var, required in vars_to_check:
        val = os.environ.get(var)
        if val:
            print(f"  OK: {var} is set")
        elif required:
            print(f"  MISSING: {var} (required for live mode)")
            return False
        else:
            print(f"  SKIP: {var} (not set, needed for live/alerts)")
    return True


def check_data_dir():
    from pathlib import Path
    data_dir = Path("data")
    if data_dir.exists():
        parquet_count = len(list(data_dir.rglob("*.parquet")))
        print(f"  OK: data/ exists ({parquet_count} parquet files)")
    else:
        print("  WARN: data/ directory not found (will be created on first download)")
    return True


def main():
    print("=== QuantFlow Environment Check ===\n")

    print("[1/4] Python version:")
    py_ok = check_python_version()

    print("\n[2/4] Dependencies:")
    dep_ok = check_dependencies()

    print("\n[3/4] Environment variables:")
    check_env_vars()

    print("\n[4/4] Data directory:")
    check_data_dir()

    print("\n" + "=" * 40)
    if py_ok and dep_ok:
        print("READY: All required checks passed. Run 'quantflow status' to start.")
    else:
        print("NOT READY: Fix missing items above before running.")
        sys.exit(1)


if __name__ == "__main__":
    main()
