"""Shared helpers for the validation layer (CPCV / WFO / PBO / DSR).

Extracted from per-module copies (odyssey-review ARCH finding):
``_sanitize_metric_array`` previously existed byte-identically in cpcv.py,
pbo.py, and wfo.py — a fix in one would not propagate to the others,
letting PBO/CPCV/WFO results silently diverge. Centralizing here gives the
metric-sanitization policy a single owner.
"""

from __future__ import annotations

from typing import cast

import numpy as np
import numpy.typing as npt


def sanitize_metric_array(values: list[float]) -> npt.NDArray[np.float64]:
    """Normalize validation metrics to finite floats to avoid numeric warnings."""
    arr = np.asarray(values, dtype=float)
    sanitized = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return cast(npt.NDArray[np.float64], sanitized.astype(np.float64, copy=False))
