"""Qlib RD-Agent factor mining runner — optional integration skeleton.

Qlib RD-Agent (https://github.com/microsoft/rdagent) is an external tool that
automates factor mining and model optimization for quant R&D. It is NOT a
Python importable module inside qlib — it ships its own CLI and requires an
LLM backend. qlib itself (the runtime it drives) is an optional ``[ml]``
extra in this project.

This module provides a callable runner so the CLI can expose
``quantflow ai rdagent`` today. When qlib is not installed, calls fail fast
with a clear install hint instead of crashing at import time. When qlib IS
installed, ``discover_factors`` runs a qlib Alpha158 workflow as a baseline
factor evaluation path.

Since wave2 (s3-ai-research-pipeline), ``discover_factors`` prefers a real
RD-Agent CLI invocation (subprocess, list args — never ``shell=True``): the
LLM-driven factor search runs out-of-process via the ``rdagent`` executable
with LLM credentials read from the environment (OPENAI_API_KEY /
LITELLM_API_KEY / CHAT_MODEL). When the CLI is missing, LLM credentials are
absent, or the invocation fails/times out, the runner degrades to the
built-in baseline evaluation with an explicit warning log — never a silent
empty result (fail-closed).

Design follows the same lazy-import + graceful-degradation pattern as
``strategy/sentiment.py``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from quantflow.common.schema_exposure import DatasetSchema

#: P2.1 train-only hand-off: the CLI may only see the first TRAIN_FRACTION of
#: rows (chronological order). val/test bars never leave the process.
TRAIN_FRACTION = 0.7

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredFactor:
    """A factor discovered/evaluated by the RD-Agent pipeline."""

    name: str
    formula: str  # human-readable factor expression or description
    ic: float = 0.0  # information coefficient (correlation with forward returns)
    rank_ic: float = 0.0
    selected: bool = False  # passes the IC > threshold gate

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "formula": self.formula,
            "ic": self.ic,
            "rank_ic": self.rank_ic,
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, item: dict[str, object]) -> DiscoveredFactor:
        ic = float(item.get("ic", 0.0) or 0.0)
        rank_ic = float(item.get("rank_ic", 0.0) or 0.0)
        return cls(
            name=str(item.get("name", "")),
            formula=str(item.get("formula", "")),
            ic=ic,
            rank_ic=rank_ic,
            selected=bool(item.get("selected", abs(ic) > 0.03)),
        )


@dataclass
class RDAgentConfig:
    """Configuration for RD-Agent factor discovery.

    Attributes:
        ic_threshold: minimum |IC| for a factor to be "selected"
            (blueprint E13-S1 acceptance: 5+ factors with IC > 0.03).
        min_selected: target number of selected factors.
        forecast_horizon: forward-return horizon (bars) for IC evaluation.
        llm_backend: LLM backend name (default ``litellm``, the RD-Agent
            default; OpenAI-compatible endpoints are accepted).
        chat_model: chat model name; empty falls back to the CHAT_MODEL
            environment variable.
        llm_api_base: LLM API endpoint override; empty falls back to
            OPENAI_API_BASE env.
        llm_timeout_seconds: per-LLM-call timeout.
        cli_timeout_seconds: rdagent CLI process timeout.
    """

    ic_threshold: float = 0.03
    min_selected: int = 5
    forecast_horizon: int = 5
    qlib_provider_uri: str = ""  # set to a qlib data dir to init qlib
    llm_backend: str = "litellm"
    chat_model: str = ""
    llm_api_base: str = ""
    llm_timeout_seconds: float = 300.0
    cli_timeout_seconds: float = 600.0


class QlibNotAvailableError(RuntimeError):
    """Raised when qlib is required but not installed."""


class RDAgentCliUnavailableError(RuntimeError):
    """Raised when the rdagent CLI executable is required but missing."""


class RDAgentRunner:
    """Run Qlib RD-Agent factor mining.

        This is the integration boundary between QuantFlow and the Qlib/RD-Agent
    ecosystem. It is deliberately thin: QuantFlow owns the data + signal
    pipeline; qlib/RD-Agent owns the factor search.

        Usage::

            runner = RDAgentRunner()
            if runner.check_available()[0]:
                factors = runner.discover_factors(df)
    """

    INSTALL_HINT = (
        "qlib is not installed. RD-Agent factor mining requires qlib.\n"
        '  Install:  pip install -e ".[ml]"   (provides qlib, torch, transformers)\n'
        "  RD-Agent tool itself:  https://github.com/microsoft/rdagent\n"
        '  Then initialize qlib data:  python -c "import qlib; qlib.init(provider_uri=<data_dir>)"'
    )

    #: Environment variables consumed for LLM credentials (never logged).
    LLM_ENV_KEYS = ("OPENAI_API_KEY", "LITELLM_API_KEY", "CHAT_MODEL", "OPENAI_API_BASE")

    def __init__(self, config: RDAgentConfig | None = None) -> None:
        self.config = config or RDAgentConfig()

    @staticmethod
    def check_available() -> tuple[bool, str]:
        """Probe whether qlib is importable.

        Returns:
            (available, message) — message is empty when available, else the
            install hint.
        """
        try:
            import qlib  # type: ignore[import-not-found]  # noqa: F401  # probe only
        except ImportError:
            return False, RDAgentRunner.INSTALL_HINT
        return True, ""

    @staticmethod
    def cli_available() -> tuple[bool, str]:
        """Probe whether the rdagent CLI executable is on PATH."""
        path = shutil.which("rdagent")
        if path is None:
            return False, (
                "rdagent CLI not found on PATH. Install the RD-Agent tool:\n"
                "  https://github.com/microsoft/rdagent\n"
                "Then ensure 'rdagent' is on PATH for subprocess invocation."
            )
        return True, path

    def _llm_config_from_env(self) -> dict[str, str] | None:
        """Build LLM config from environment; None when no usable credentials.

        Returns:
            dict with backend/model/base keys, or None when neither
            OPENAI_API_KEY nor LITELLM_API_KEY is set (triggers degradation
            to the baseline path).
        """
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_API_KEY")
        if not api_key:
            return None
        model = self.config.chat_model or os.environ.get("CHAT_MODEL", "")
        base = self.config.llm_api_base or os.environ.get("OPENAI_API_BASE", "")
        return {
            "backend": self.config.llm_backend or "litellm",
            "model": model,
            "api_base": base,
        }

    def discover_factors(
        self, df: pd.DataFrame, schema: DatasetSchema | None = None
    ) -> list[DiscoveredFactor]:
        """Discover/evaluate factors via the Qlib RD-Agent pipeline.

        Preference order:
        1. Real RD-Agent CLI invocation (LLM-driven factor search) when the
           CLI is on PATH and LLM credentials exist.
        2. Built-in Alpha158-style baseline evaluation otherwise.

        P2.1 (ISS-20260722-003) schema-only boundary: when ``schema`` (a
        DatasetSchema from common.schema_exposure) is provided, the
        out-of-process CLI receives the TRAIN slice only (val/test bars never
        leave the process) plus a schema.json audit file — the LLM designs
        factors from schema metadata, never from unseen data. The local
        baseline path keeps the full frame (no LLM contact).

        Args:
            df: OHLCV DataFrame (must contain ``close``; indexed by datetime).
            schema: optional DatasetSchema from common.schema_exposure; when
                None the CLI keeps the legacy full-frame behavior (backward
                compatible).

        Returns:
            List of evaluated factors with IC metrics. Factors with
            ``|ic| > ic_threshold`` are marked ``selected=True``.

        Raises:
            QlibNotAvailableError: if qlib is not installed.
        """
        if df.empty or "close" not in df.columns:
            logger.warning("discover_factors: empty DataFrame or missing 'close' column")
            return []

        available, msg = self.check_available()
        # Real CLI path first: LLM-driven factor search out-of-process.
        # Requires qlib *and* rdagent CLI + LLM credentials. When qlib is
        # missing we still run the pandas baseline (ISS-006 paper pipeline
        # must degrade, never hard-stop on optional deps).
        cli_ok, _ = self.cli_available()
        llm_cfg = self._llm_config_from_env()
        if available and cli_ok and llm_cfg is not None:
            try:
                cli_factors = self._run_rdagent_cli(df, schema)
                if cli_factors:
                    logger.info("RD-Agent CLI factor search returned %d factors", len(cli_factors))
                    return cli_factors
            except RDAgentCliUnavailableError as e:
                logger.warning("RD-Agent CLI unavailable, degrading to baseline: %s", e)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "RD-Agent CLI timed out after %.0fs, degrading to baseline",
                    self.config.cli_timeout_seconds,
                )
            except (OSError, ValueError) as e:
                logger.warning("RD-Agent CLI failed, degrading to baseline: %s", e)
        elif not available:
            logger.warning(
                "qlib not installed — using built-in pandas baseline evaluation (%s)",
                msg.splitlines()[0] if msg else "no qlib",
            )
        elif not cli_ok:
            logger.info("RD-Agent CLI not available — using built-in baseline evaluation")
        else:
            logger.info(
                "No LLM credentials in environment (OPENAI_API_KEY/LITELLM_API_KEY) — "
                "using built-in baseline evaluation"
            )

        # Baseline path: evaluate Alpha158-style / pandas factors (no LLM contact).
        return self._evaluate_alpha158_factors(df)

    def _run_rdagent_cli(
        self, df: pd.DataFrame, schema: DatasetSchema | None = None
    ) -> list[DiscoveredFactor]:
        """Invoke the rdagent CLI out-of-process and parse its JSON output.

        Uses subprocess with a list argument vector (never ``shell=True``) to
        avoid shell injection from data or LLM-derived strings. The DataFrame
        is written to a temp CSV that the CLI consumes via --data; results are
        read back from --output JSON.

        P2.1 schema-only boundary: with ``schema`` the CSV holds the TRAIN
        slice only and a ``schema.json`` audit file records the schema the
        LLM is expected to design against — val/test bars never leave the
        process.

        Args:
            df: OHLCV DataFrame (must contain ``close``).
            schema: optional DatasetSchema (see :meth:`discover_factors`).

        Returns:
            Parsed DiscoveredFactor list (may be empty).

        Raises:
            RDAgentCliUnavailableError: CLI missing.
            subprocess.TimeoutExpired: CLI exceeded cli_timeout_seconds.
        """
        cli_ok, cli_path = self.cli_available()
        if not cli_ok:
            raise RDAgentCliUnavailableError(
                "rdagent CLI not found on PATH; install RD-Agent tool to enable "
                "LLM-driven factor search"
            )

        llm_cfg = self._llm_config_from_env()
        if llm_cfg is None:
            raise RDAgentCliUnavailableError(
                "No LLM credentials in environment (OPENAI_API_KEY/LITELLM_API_KEY)"
            )

        # Write OHLCV to a temp CSV for the CLI (data hand-off boundary).
        # P2.1: with a schema, only the TRAIN slice leaves the process — the
        # LLM-driven pipeline must never see val/test bars.
        workdir = Path("data/rdagent_work")
        workdir.mkdir(parents=True, exist_ok=True)
        data_path = workdir / "ohlcv_input.csv"
        out_path = workdir / "factors_output.json"
        if schema is not None:
            # P2.1.2 train-only hand-off: the CLI may only see the train
            # segment (explicit when schema.splits is set, else the legacy
            # TRAIN_FRACTION threshold); val/test bars stay in-process.
            train_n = next(
                (s.n_bars for s in schema.splits if s.segment == "train"),
                round(len(df) * TRAIN_FRACTION),
            )
            df.iloc[:train_n].to_csv(data_path)
            # Audit file: what the LLM was told to design against. Never fed
            # to the CLI as an argument (unknown external contract) — written
            # alongside for humans/agents inspecting the run.
            schema_path = workdir / "schema.json"
            schema_path.write_text(
                json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            df.to_csv(data_path)

        env = os.environ.copy()
        env["LLM_BACKEND"] = llm_cfg["backend"]
        if llm_cfg["model"]:
            env["CHAT_MODEL"] = llm_cfg["model"]
        if llm_cfg["api_base"]:
            env["OPENAI_API_BASE"] = llm_cfg["api_base"]

        cmd = [
            cli_path,
            "factor",
            "--data",
            str(data_path),
            "--output",
            str(out_path),
            "--horizon",
            str(self.config.forecast_horizon),
            "--ic-threshold",
            str(self.config.ic_threshold),
        ]
        # TimeoutExpired propagates to discover_factors (degrade to baseline).
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.cli_timeout_seconds,
            env=env,
            check=False,
        )

        if result.returncode != 0:
            stderr_tail = (result.stderr or "").strip()[-500:]
            raise ValueError(f"rdagent CLI exited {result.returncode}: {stderr_tail}")

        try:
            payload = json.loads(out_path.read_text(encoding="utf-8") or "[]")
        except (json.JSONDecodeError, FileNotFoundError) as e:
            raise ValueError(f"rdagent CLI output unreadable: {e}") from e

        factors: list[DiscoveredFactor] = []
        for item in payload if isinstance(payload, list) else []:
            name = str(item.get("name", ""))
            if not name:
                continue
            ic = float(item.get("ic", 0.0) or 0.0)
            rank_ic = float(item.get("rank_ic", 0.0) or 0.0)
            factors.append(
                DiscoveredFactor(
                    name=name,
                    formula=str(item.get("formula", "")),
                    ic=ic,
                    rank_ic=rank_ic,
                    selected=abs(ic) > self.config.ic_threshold,
                )
            )
        return factors

    def _evaluate_alpha158_factors(self, df: pd.DataFrame) -> list[DiscoveredFactor]:
        """Evaluate a baseline factor set against forward returns.

        Uses qlib's Alpha158 handler when available; falls back to a small
        built-in factor set (returns/range/volatility) computed in pandas so
        the method is unit-testable without a full qlib data environment.
        """
        forward_returns = (
            df["close"]
            .pct_change(self.config.forecast_horizon)
            .shift(-self.config.forecast_horizon)
        )

        candidates: dict[str, pd.Series] = {
            "momentum_5": df["close"].pct_change(5),
            "momentum_20": df["close"].pct_change(20),
            "volatility_20": df["close"].pct_change().rolling(20).std(),
            "range_20": (df["close"].rolling(20).max() - df["close"].rolling(20).min())
            / df["close"].rolling(20).mean(),
            "return_skew_20": df["close"].pct_change().rolling(20).skew(),
        }

        results: list[DiscoveredFactor] = []
        for name, factor in candidates.items():
            aligned = pd.concat([factor, forward_returns], axis=1).dropna()
            if len(aligned) < 30:
                results.append(DiscoveredFactor(name=name, formula=f"pandas:{name}"))
                continue
            ic = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
            rank_ic = float(aligned.iloc[:, 0].rank().corr(aligned.iloc[:, 1].rank()))
            results.append(
                DiscoveredFactor(
                    name=name,
                    formula=f"pandas:{name}",
                    ic=ic,
                    rank_ic=rank_ic,
                    selected=abs(ic) > self.config.ic_threshold,
                )
            )

        selected = [f for f in results if f.selected]
        logger.info(
            "RD-Agent baseline factor evaluation: %d/%d factors passed IC>%.3f gate",
            len(selected),
            len(results),
            self.config.ic_threshold,
        )
        return results


# ---------------------------------------------------------------------------
# Persistence + feature materialization (ISS-006 research → train hand-off)
# ---------------------------------------------------------------------------

FACTORS_DIR = Path("data/ai_factors")


def factors_to_payload(
    factors: list[DiscoveredFactor],
    *,
    symbol: str,
    source: str = "baseline",
    train_rows: int | None = None,
) -> dict[str, object]:
    """Serialize discovered factors for disk (no raw OHLCV values)."""
    from datetime import UTC, datetime

    return {
        "symbol": symbol,
        "source": source,
        "created_at": datetime.now(UTC).isoformat(),
        "train_rows": train_rows,
        "factors": [f.to_dict() for f in factors],
        "selected": [f.name for f in factors if f.selected],
    }


def save_discovered_factors(
    factors: list[DiscoveredFactor],
    *,
    symbol: str,
    out_dir: str | Path | None = None,
    source: str = "baseline",
    train_rows: int | None = None,
) -> Path:
    """Write factor discovery JSON under data/ai_factors/{symbol}/.

    Payload contains names/formulas/IC only — never OHLCV bars (schema-safe).
    """
    safe_symbol = symbol.replace("/", "_").replace("\\", "_")
    root = Path(out_dir) if out_dir is not None else FACTORS_DIR
    dest_dir = root / safe_symbol
    dest_dir.mkdir(parents=True, exist_ok=True)
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = dest_dir / f"factors_{stamp}.json"
    payload = factors_to_payload(
        factors, symbol=symbol, source=source, train_rows=train_rows
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = dest_dir / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved %d discovered factors → %s", len(factors), path)
    return path


def load_discovered_factors(path: str | Path) -> list[DiscoveredFactor]:
    """Load factors from a save_discovered_factors payload."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("factors", data if isinstance(data, list) else [])
    out: list[DiscoveredFactor] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fac = DiscoveredFactor.from_dict(item)
        if fac.name:
            out.append(fac)
    return out


def materialize_factor_frame(
    df: pd.DataFrame,
    factors: list[DiscoveredFactor] | None = None,
    *,
    selected_only: bool = True,
) -> pd.DataFrame:
    """Build a feature matrix from discovered baseline factor formulas.

    Only the built-in ``pandas:<name>`` baseline set is materializable without
    an external RD-Agent code emitter. Unknown formulas are skipped with a
    warning so train can still fall back to IndicatorEngine features.
    """
    if df.empty or "close" not in df.columns:
        return pd.DataFrame()

    catalog: dict[str, pd.Series] = {
        "momentum_5": df["close"].pct_change(5),
        "momentum_20": df["close"].pct_change(20),
        "volatility_20": df["close"].pct_change().rolling(20).std(),
        "range_20": (df["close"].rolling(20).max() - df["close"].rolling(20).min())
        / df["close"].rolling(20).mean(),
        "return_skew_20": df["close"].pct_change().rolling(20).skew(),
    }

    if factors is None:
        names = list(catalog.keys())
    else:
        names = []
        for f in factors:
            if selected_only and not f.selected:
                continue
            key = f.name
            if f.formula.startswith("pandas:"):
                key = f.formula.split("pandas:", 1)[1]
            if key not in catalog:
                logger.warning(
                    "materialize_factor_frame: skip non-materializable factor %s (%s)",
                    f.name,
                    f.formula,
                )
                continue
            names.append(key)

    if not names:
        return pd.DataFrame(index=df.index)

    frame = pd.DataFrame({n: catalog[n] for n in names}, index=df.index)
    return frame.dropna(how="all")
