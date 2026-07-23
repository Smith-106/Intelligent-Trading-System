"""JSON-safe numeric coercion (single source of truth).

``_safe_number`` converts non-finite numeric values to ``None`` for JSON-safe
payloads. Two web modules (``web/service.py`` and ``web/session_manager.py``)
previously maintained divergent copies — service.py handled ``np.floating`` /
``np.integer`` while session_manager.py did not, letting a ``np.float64`` NaN
fall through to ``json.dumps`` and emit a bare ``NaN`` token into the
persisted JSONL audit trail (odyssey-review ARCH+SEC finding).

Centralizing here gives the NaN/inf policy a single owner so the two coercers
cannot drift again. numpy is imported lazily inside the function body so this
module stays import-light for callers that never coerce numpy scalars.
"""

from __future__ import annotations

import math
from typing import Any


def safe_number(value: Any) -> Any:
    """Convert a numeric value to a JSON-safe form, dropping non-finite floats.

    - ``bool`` / ``int`` → returned unchanged (bool before int so True≠1).
    - ``float`` → ``None`` if NaN/±inf, else the float.
    - ``np.floating`` → coerced to native ``float``, then ``None`` if non-finite.
    - ``np.integer`` → coerced to native ``int``.
    - anything else → returned unchanged (caller's fallback handles it).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    # numpy scalars (imported lazily so this module has no hard numpy dep).
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is a core dep
        return value
    if isinstance(value, np.floating):
        cast = float(value)
        return cast if math.isfinite(cast) else None
    if isinstance(value, np.integer):
        return int(value)
    return value
