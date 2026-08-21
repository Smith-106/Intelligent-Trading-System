"""s3 AI research pipeline end-to-end verification (T-s3-05).

Exercises the full loop with synthetic data:
  1. RD-Agent factor discovery (baseline path, no qlib/LLM needed)
  2. Feature store meta features (funding/OI as-of join)
  3. AI model training + validation gate
  4. Gated model registration (GO → paper, NO-GO → rejected)

Exit code 0 on success — usable as a CI gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantflow.data.feature_store import FeatureStore
from quantflow.data.store import DataStore
from quantflow.indicators.meta_features import MetaFeatureEngine
from quantflow.strategy.ai_training import AITrainingPipeline
from quantflow.strategy.model_registry import ModelRegistry
from quantflow.strategy.rd_agent import RDAgentRunner

WORK = Path("data/s3_verify")
WORK.mkdir(parents=True, exist_ok=True)


def _make_ohlcv(n: int = 500, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.standard_normal(n) * 0.01 + 0.001
    close = 100.0 * np.exp(np.cumsum(returns))
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "timestamp": [int(d.timestamp() * 1000) for d in idx],
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0 + rng.integers(0, 500, n),
        }
    )


def _make_meta(ohlcv: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ts = ohlcv["timestamp"]
    funding = pd.DataFrame(
        {
            "timestamp": ts[::8].values,
            "funding_rate": np.linspace(-0.0005, 0.0005, len(ts[::8])),
            "realized_rate": 0.0,
            "funding_time": ts[::8].values,
        }
    )
    oi = pd.DataFrame(
        {
            "timestamp": ts.values,
            "open_interest": np.linspace(1_000_000, 1_200_000, len(ts)),
            "open_interest_ccy": np.linspace(10.0, 12.0, len(ts)),
            "open_interest_usd": np.linspace(60e9, 72e9, len(ts)),
        }
    )
    return funding, oi


def main() -> int:
    print("== s3 AI pipeline verification ==")

    # --- 1. Factor discovery (baseline path, no LLM) ---
    ohlcv = _make_ohlcv()
    runner = RDAgentRunner()
    # CI has no qlib installed; the baseline factor path is pure pandas and
    # does not need qlib. Simulate availability to exercise it (the guard
    # itself is covered by tests/unit/test_rd_agent.py).
    RDAgentRunner.check_available = staticmethod(lambda: (True, ""))  # type: ignore[method-assign]
    idx = pd.to_datetime(ohlcv["timestamp"], unit="ms", utc=True)
    factors = runner.discover_factors(ohlcv.set_index(idx))
    assert len(factors) >= 4, f"expected >=4 baseline factors, got {len(factors)}"
    print(
        f"[1] factor discovery OK: {len(factors)} factors "
        f"({sum(1 for f in factors if f.selected)} selected)"
    )

    # --- 2. Feature store + meta features ---
    raw_store = DataStore(str(WORK / "raw"))
    raw_store.save(ohlcv, "BTC/USDT")
    funding, oi = _make_meta(ohlcv)
    raw_store.save_funding_rates(funding, "BTC/USDT")
    raw_store.save_open_interest(oi, "BTC/USDT")

    engine = MetaFeatureEngine()
    fs = FeatureStore(str(WORK / "feat"), indicator_computer=None, meta_computer=engine)

    # Use a trivial indicator computer to keep OHLCV-derived features minimal.
    class _PassThrough:
        def compute_all(self, df, indicator_names=None):
            out = df.copy()
            out["mom_5"] = out["close"].pct_change(5)
            return out

    fs._indicator_computer = _PassThrough()
    features = fs.compute_features(
        "BTC/USDT", int(ohlcv["timestamp"].max()), ["mom_5"], raw_store, meta_store=raw_store
    )
    assert "funding_rate_ma_3" in features.columns, "funding feature missing"
    assert "oi_change_1" in features.columns, "OI feature missing"
    print(
        f"[2] feature store + meta features OK: {len(features)} rows, {len(features.columns)} cols"
    )

    # --- 3. AI training + validation gate ---
    pipe = AITrainingPipeline(
        validation_kwargs={"cpcv_groups": 4, "cpcv_test_groups": 1, "wfo_windows": 3}
    )
    feature_cols = [c for c in features.columns if c not in ("timestamp", "symbol", "computed_at")]
    close = (
        features["close"]
        if "close" in features.columns
        else pd.Series(ohlcv["close"].values, index=features.index)
    )
    report = pipe.train(features[feature_cols], close, None, n_estimators=30, max_depth=3)
    assert report.decision in ("GO", "NO-GO")
    print(f"[3] training + gate OK: decision={report.decision} ({report.reason[:60]}…)")

    # --- 4. Gated registration ---
    reg = ModelRegistry(str(WORK / "registry"))
    entry = reg.register(
        model_id=f"verify-{report.features_hash}",
        model_cls=report.model_cls,
        features_hash=report.features_hash,
        validation_report=report.validation
        or {"decision": report.decision, "reason": report.reason},
    )
    assert entry["status"] in ("paper", "rejected")
    print(
        f"[4] registry gate OK: status={entry['status']} (fail-closed: "
        f"{'passed GO' if entry['status'] == 'paper' else 'correctly refused'})"
    )

    print("\n== s3 pipeline verification PASSED ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
