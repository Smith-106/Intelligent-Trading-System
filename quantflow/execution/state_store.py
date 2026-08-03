"""Checkpoint state store — crash-recovery persistence for trading sessions.

T-s1-03: a paper/live session periodically snapshots its authoritative L4
state (cash + positions + open orders) to a JSON checkpoint. After an
unplanned exit (kill -9, crash, host reboot) the next ``TradingSession.start``
restores the snapshot and verifies it against the exchange via the
ReconciliationEngine before new-entry signals are allowed (fail-closed).

Contract:
- ``save_checkpoint`` writes via tmp file + ``os.replace`` so a crash mid-write
  can never leave a half-written checkpoint (atomic on POSIX and Windows).
- ``load_checkpoint`` returns ``None`` when no checkpoint exists (fresh start)
  AND when the file is corrupt or carries an unknown schema version. The two
  cases are distinguished by ``last_error`` (``None`` = no file, str = load
  failure) so callers can fail-closed on corruption without failing a first
  run.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1
CHECKPOINT_FILENAME = "session_checkpoint.json"


@dataclass
class SessionSnapshot:
    """Serializable session state (authoritative L4 view).

    ``schema_version`` guards forward compatibility: a loader that meets an
    unknown version refuses to restore rather than guessing field semantics.
    """

    saved_at_ms: int = 0
    mode: str = ""
    cash: float = 0.0
    positions: list[dict[str, Any]] = field(default_factory=list)
    open_orders: list[dict[str, Any]] = field(default_factory=list)
    equity: float = 0.0
    schema_version: int = CURRENT_SCHEMA_VERSION


_FIELD_NAMES = {f.name for f in fields(SessionSnapshot)}


class StateStore:
    """Atomic JSON checkpoint persistence for one session."""

    def __init__(self, checkpoint_dir: str) -> None:
        self._dir = Path(checkpoint_dir)
        # None = no load error (file absent or loaded fine); str = the load
        # failed (corrupt JSON / unknown schema version). Fail-closed callers
        # branch on this instead of treating every None as "fresh start".
        self.last_error: str | None = None

    def _checkpoint_path(self) -> Path:
        return self._dir / CHECKPOINT_FILENAME

    def save_checkpoint(self, snapshot: SessionSnapshot) -> None:
        """Persist the snapshot atomically (tmp file + os.replace)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._checkpoint_path()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(
            json.dumps(asdict(snapshot), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        # os.replace is atomic on POSIX and Windows: readers see either the
        # previous complete file or the new complete file, never a fragment.
        os.replace(tmp, target)
        logger.info(
            "Checkpoint saved: mode=%s cash=%.2f positions=%d orders=%d",
            snapshot.mode,
            snapshot.cash,
            len(snapshot.positions),
            len(snapshot.open_orders),
        )

    def load_checkpoint(self) -> SessionSnapshot | None:
        """Load the latest snapshot, or None (fresh start / corrupt file).

        Corrupt JSON or a schema-version mismatch logs at CRITICAL and sets
        ``last_error`` so callers can fail-closed; a missing file is a normal
        first run and leaves ``last_error`` as None.
        """
        self.last_error = None
        path = self._checkpoint_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                msg = f"checkpoint root is {type(data).__name__}, not an object"
                raise ValueError(msg)
            version = data.get("schema_version")
            if version != CURRENT_SCHEMA_VERSION:
                self.last_error = f"schema version mismatch: {version!r}"
                logger.critical(
                    "Checkpoint schema version mismatch (%s != %s) — refusing to restore",
                    version,
                    CURRENT_SCHEMA_VERSION,
                )
                return None
            known = {k: v for k, v in data.items() if k in _FIELD_NAMES}
            return SessionSnapshot(**known)
        except Exception as e:
            self.last_error = str(e)
            logger.critical("Checkpoint corrupt or unreadable: %s", e)
            return None

    def clear(self) -> None:
        """Remove the checkpoint file (idempotent)."""
        with contextlib.suppress(FileNotFoundError):
            self._checkpoint_path().unlink()
