"""JSON-safe serialization (single source of truth).

``to_jsonable`` recursively converts arbitrary runtime values (dicts, lists,
numpy scalars, pandas Series/Timestamp, Paths, non-finite floats) into a form
``json.dumps`` can serialize without emitting bare ``NaN``/``Infinity`` tokens.

Previously ``web/service._to_jsonable`` (7 branches) and
``web/session_manager._jsonable`` (4 branches) diverged — the session_manager
copy lacked ``pd.Series`` / ``pd.Timestamp`` / ``np.generic`` handling, so a
pandas value reaching the JSONL persistence path leaked as a non-JSON-safe
repr (ISS-041, same family as the ``_safe_number`` divergence fixed in
``common/numeric.py``). Centralizing here gives the serialization policy one
owner so the two copies cannot drift again.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

from quantflow.common.numeric import safe_number


def series_payload(series: Any, *, max_points: int = 300) -> dict[str, list[Any]]:
    """Down-sample a pandas Series to a {labels, values} JSON payload.

    Large series are sampled to ``max_points`` points (always including the
    last) so an HTTP/JSONL payload stays bounded. Non-finite values become
    ``None`` via :func:`safe_number`.
    """
    if len(series) <= max_points:
        sampled = series
    else:
        step = max(1, len(series) // max_points)
        indexes = list(range(0, len(series), step))
        if indexes[-1] != len(series) - 1:
            indexes.append(len(series) - 1)
        sampled = series.iloc[indexes]

    labels = [str(index) for index in sampled.index]
    values: list[Any] = []
    for value in sampled.tolist():
        number = safe_number(float(value))
        values.append(None if number is None else round(float(number), 6))
    return {"labels": labels, "values": values}


def to_jsonable(value: Any) -> Any:
    """Recursively coerce ``value`` to a JSON-safe form.

    Handles dict / list / tuple / set / Path / numpy scalar / pandas Series /
    pandas Timestamp / non-finite float. Anything else passes through
    :func:`safe_number` (which returns it unchanged if not numeric).
    """
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    # numpy + pandas are imported lazily so this module has no hard dep on them
    # (callers that never serialize pandas values pay nothing).
    np = _maybe_import("numpy")
    if np is not None and isinstance(value, np.generic):
        return safe_number(value.item())
    pd = _maybe_import("pandas")
    if pd is not None and isinstance(value, pd.Series):
        return series_payload(value)
    if pd is not None and isinstance(value, pd.Timestamp):
        return value.isoformat()
    return safe_number(value)


def _maybe_import(name: str) -> ModuleType | None:
    """Import ``name`` lazily, returning ``None`` if unavailable.

    Centralizes the try/except so the type checker sees a single ``Optional``
    assignment rather than per-branch ``None`` reassignments (which mypy
    flags as incompatible with the imported ``Module`` type).
    """
    try:
        return importlib.import_module(name)
    except ImportError:  # pragma: no cover - numpy/pandas are core deps
        return None
