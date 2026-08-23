"""Exchange health monitor — single-exchange circuit breaker (T-s1-04).

First layer of exchange-level risk isolation (roadmap s1.scope[3]): a sliding
window of REST/WS outcomes per exchange drives a fail-closed circuit breaker.
When the breaker opens, RiskEngine.check (the single signal entry point)
rejects all new signals with ``exchange_circuit_open`` — the interception
point is deliberately NOT ExecutionEngine.submit, so there is exactly one
place a signal can be blocked (plan locked contract; avoids dual-interception
semantic drift).

Trip conditions (either):
- sliding-window error rate > ``error_rate_threshold``
- ``rate_limit_streak_threshold`` consecutive OKX 50011 (rate limited) errors

Recovery is hysteretic (防抖): after ``cooldown_seconds`` the breaker enters a
half-open observation window and closes only after
``RECOVERY_SUCCESS_STREAK`` (3) consecutive successes. Any failure during the
open/half-open state re-anchors the cooldown. This prevents a flapping
exchange from spinning the breaker open/closed per bar.

Layering (arch-013): this module lives in L5 (execution) and depends only on
common/ (MonitoringSink Protocol, EventBus). RiskEngine (L4) receives the
monitor duck-typed (``Any | None``) so L4 never imports L5 concrete classes.

On the closed→open transition the monitor emits:
- ``MonitoringSink.record_risk_event('exchange_circuit_open', 'emergency')``
- ``MonitoringSink.send_alert(level='critical')`` (fire-and-forget)
- ``EVENT_RISK`` event with ``severity='emergency'`` so TradingSession's
  existing ``_on_risk_event`` path can route to the kill switch — no change
  to kill_switch.py itself (plan locked contract).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from quantflow.common.event_bus import EVENT_RISK, Event
from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink
from quantflow.common.redaction import redact_secrets

logger = logging.getLogger(__name__)

#: Consecutive successes required in the half-open window to close the
#: breaker (plan locked: 恢复需 cooldown 后连续 success 观察窗口 ≥3).
RECOVERY_SUCCESS_STREAK = 3


class ExchangeHealthMonitor:
    """Sliding-window health tracker + hysteretic circuit breaker.

    All ``record_*`` methods are synchronous and exception-safe: a health
    monitor MUST NOT raise into the gateway hot path (order submission /
    ws loops). Internal errors are logged and swallowed.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        error_rate_threshold: float = 0.5,
        rate_limit_streak_threshold: int = 3,
        cooldown_seconds: float = 300.0,
        monitoring_sink: MonitoringSink | None = None,
        event_bus: Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._window_seconds = float(window_seconds)
        self._error_rate_threshold = float(error_rate_threshold)
        self._rate_limit_streak_threshold = int(rate_limit_streak_threshold)
        self._cooldown_seconds = float(cooldown_seconds)
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        self._event_bus = event_bus
        self._clock = clock or time.monotonic
        # (monotonic stamp, is_success) outcomes inside the sliding window.
        self._events: deque[tuple[float, bool]] = deque()
        self._rate_limit_streak = 0
        self._open = False
        self._opened_at = 0.0
        self._recovery_streak = 0
        # Strong refs for fire-and-forget alert tasks (RUF006): without this
        # set the loop may garbage-collect a task before its alert is sent.
        self._background_tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ #
    # Recording API (called by OKXGateway REST / 50011 / WS paths)
    # ------------------------------------------------------------------ #
    def record_api_error(self, code: str | None = None) -> None:
        """Record a REST failure (timeout, HTTP error, exchange error code)."""
        self._record_failure()
        # REV-024-LOG8: every REST failure already logs an error at the
        # gateway layer; this per-call echo is breaker input telemetry.
        logger.debug("Exchange health: API error recorded (code=%s)", code)

    def record_rate_limited(self) -> None:
        """Record an OKX 50011 (Too Many Requests) failure.

        Counts toward the consecutive rate-limit streak; the breaker trips at
        ``rate_limit_streak_threshold`` consecutive occurrences even when the
        window error rate alone would not breach the threshold.
        """
        self._rate_limit_streak += 1
        self._record_failure()
        logger.warning("Exchange health: rate limited (50011) streak=%d", self._rate_limit_streak)

    def record_ws_disconnect(self) -> None:
        """Record a WebSocket watch-loop failure (counts as an API failure)."""
        self._record_failure()
        logger.warning("Exchange health: WS disconnect recorded")

    def record_success(self) -> None:
        """Record a successful exchange interaction.

        Resets the rate-limit streak; when the breaker is open and the
        cooldown has elapsed, accumulates toward the half-open recovery
        streak (≥ RECOVERY_SUCCESS_STREAK closes the breaker).
        """
        now = self._clock()
        self._rate_limit_streak = 0
        self._events.append((now, True))
        self._purge(now)
        if self._open and (now - self._opened_at) >= self._cooldown_seconds:
            self._recovery_streak += 1
            if self._recovery_streak >= RECOVERY_SUCCESS_STREAK:
                self._close_circuit(now)

    # ------------------------------------------------------------------ #
    # Query API
    # ------------------------------------------------------------------ #
    def circuit_open(self) -> bool:
        """True while the breaker is open (fail-closed gate for RiskEngine)."""
        return self._open

    def snapshot(self) -> dict[str, Any]:
        """Redaction-safe status snapshot (metrics/labels only, no credentials)."""
        now = self._clock()
        self._purge(now)
        total = len(self._events)
        errors = sum(1 for _, ok in self._events if not ok)
        return {
            "circuit_open": self._open,
            "window_seconds": self._window_seconds,
            "window_samples": total,
            "window_errors": errors,
            "error_rate": (errors / total) if total else 0.0,
            "error_rate_threshold": self._error_rate_threshold,
            "rate_limit_streak": self._rate_limit_streak,
            "recovery_streak": self._recovery_streak,
            "cooldown_remaining": (
                max(0.0, self._cooldown_seconds - (now - self._opened_at)) if self._open else 0.0
            ),
        }

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _purge(self, now: float) -> None:
        while self._events and (now - self._events[0][0]) > self._window_seconds:
            self._events.popleft()

    def _record_failure(self) -> None:
        now = self._clock()
        self._events.append((now, False))
        self._purge(now)
        if self._open:
            # Any failure during open/half-open restarts the cooldown and the
            # recovery observation (hysteresis: a flapping exchange cannot
            # ride 3 stale successes to re-close).
            self._opened_at = now
            self._recovery_streak = 0
            return
        if self._should_trip(now):
            self._trip(now)

    def _should_trip(self, now: float) -> bool:
        if self._rate_limit_streak >= self._rate_limit_streak_threshold:
            return True
        total = len(self._events)
        if total == 0:
            return False
        errors = sum(1 for _, ok in self._events if not ok)
        return (errors / total) > self._error_rate_threshold

    def _trip(self, now: float) -> None:
        self._open = True
        self._opened_at = now
        self._recovery_streak = 0
        snap = self.snapshot()
        logger.critical(
            "EXCHANGE CIRCUIT BREAKER OPEN: error_rate=%.2f rate_limit_streak=%d",
            snap["error_rate"],
            snap["rate_limit_streak"],
        )
        # Observability + kill-switch reachability (plan locked): sink risk
        # event (sync), critical alert (async fire-and-forget), EVENT_RISK
        # emergency via EventBus — TradingSession._on_risk_event is the
        # existing consumer that routes emergencies to the kill switch.
        try:
            self._sink.record_risk_event("exchange_circuit_open", "emergency")
        except Exception as e:  # monitoring must never break the hot path
            logger.debug("Health monitor sink.record_risk_event failed: %s", e)
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(
                self._sink.send_alert(
                    "Exchange circuit breaker OPEN — new orders blocked",
                    level="critical",
                    extra=snap,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            pass  # no running loop (sync test context) — alert skipped
        except Exception as e:
            logger.debug("Health monitor send_alert failed: %s", redact_secrets(str(e)))
        if self._event_bus is not None:
            try:
                self._event_bus.publish(
                    Event(
                        type=EVENT_RISK,
                        data={
                            "type": "exchange_circuit_open",
                            "severity": "emergency",
                            "snapshot": snap,
                        },
                    )
                )
            except Exception as e:
                logger.debug("Health monitor event publish failed: %s", e)

    def _close_circuit(self, now: float) -> None:
        self._open = False
        self._recovery_streak = 0
        self._rate_limit_streak = 0
        # Discard the stale open-window history so recovery starts from a
        # clean error-rate baseline (old failures inside the window would
        # instantly re-trip on the next record_failure).
        self._events.clear()
        logger.warning(
            "Exchange circuit breaker CLOSED after cooldown + %d consecutive "
            "successes — trading may resume",
            RECOVERY_SUCCESS_STREAK,
        )
        try:
            self._sink.record_risk_event("exchange_circuit_closed", "info")
        except Exception as e:
            logger.debug("Health monitor sink.record_risk_event failed: %s", e)
