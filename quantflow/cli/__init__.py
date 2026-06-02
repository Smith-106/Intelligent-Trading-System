"""QuantFlow CLI package exports."""

from __future__ import annotations

from typing import Any

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from quantflow.cli.main import app

        return app
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
