"""Build the merged spot+perp feature dataset for spot_perp_arb validation.

Sources (standard store, downloaded by scripts/download_spot_perp_data.py +
the CLI spot download):
  * spot klines 1h        (BTC_USDT)
  * perp klines 1h        (BTC-USDT-SWAP)
  * funding history       (meta_funding_rate/BTC-USDT-SWAP, 8h settlement)
  * OI history 1H         (meta_open_interest/BTC-USDT-SWAP)

Alignment (point-in-time safe):
  * funding_rate[t] = the last settlement rate with funding_time <= bar t
  * open_interest[t] = the last OI sample with timestamp <= bar t

Outputs:
  data/spot_perp_real/dataset.parquet   (hourly feature frame)
  data/spot_perp_real/quality.json      (coverage + event counts)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantflow.common.config import load_config
from quantflow.data.store import DataStore

SPOT_SYMBOL = "BTC/USDT"
PERP_SYMBOL = "BTC-USDT-SWAP"
TIMEFRAME = "1h"
OUT_DIR = Path("data/spot_perp_real")


def _load_klines(store: DataStore, symbol: str) -> pd.DataFrame:
    df = store.query(symbol, timeframe=TIMEFRAME)
    if df.empty:
        raise RuntimeError(f"No klines for {symbol}")
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    df["ts_dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df[["timestamp", "ts_dt", "open", "close"]]


def _load_funding(store: DataStore) -> pd.DataFrame:
    df = store.query_funding_rates(PERP_SYMBOL)
    if df.empty:
        raise RuntimeError("No funding history")
    df = df.sort_values("funding_time").drop_duplicates(subset=["funding_time"])
    return df[["funding_time", "funding_rate"]]


def _load_oi(store: DataStore) -> pd.DataFrame:
    df = store.query_open_interest(PERP_SYMBOL)
    if df.empty:
        raise RuntimeError("No OI history")
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    return df[["timestamp", "open_interest"]]


def main() -> None:
    cfg = load_config("quantflow/config/default.yaml")
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    try:
        spot = _load_klines(store, SPOT_SYMBOL)
        perp = _load_klines(store, PERP_SYMBOL)
        funding = _load_funding(store)
        oi = _load_oi(store)

        # Hourly index = union of spot/perp bar timestamps (intersection of
        # the two price series).
        idx = pd.Index(sorted(set(spot["timestamp"]) & set(perp["timestamp"])), name="timestamp")
        frame = pd.DataFrame(index=idx)
        frame["spot_close"] = spot.set_index("timestamp")["close"].reindex(idx)
        frame["spot_open"] = spot.set_index("timestamp")["open"].reindex(idx)
        frame["perp_close"] = perp.set_index("timestamp")["close"].reindex(idx)
        frame["perp_open"] = perp.set_index("timestamp")["open"].reindex(idx)

        # Point-in-time asof alignment (no future data at bar t).
        funding_aligned = pd.merge_asof(
            frame.reset_index(),
            funding,
            left_on="timestamp",
            right_on="funding_time",
            direction="backward",
        )
        frame["funding_rate"] = funding_aligned.set_index("timestamp")["funding_rate"]
        # Settlement mask: bar t is an actual funding settlement (8h cadence).
        frame["funding_settle"] = frame.index.isin(set(funding["funding_time"])).astype(int)
        frame["open_interest"] = pd.merge_asof(
            frame.reset_index(),
            oi,
            left_on="timestamp",
            right_on="timestamp",
            direction="backward",
        ).set_index("timestamp")["open_interest"]

        frame = frame.dropna(subset=["spot_close", "perp_close"])
        frame = frame.sort_index()
        frame.index = pd.to_datetime(frame.index, unit="ms", utc=True).rename("datetime")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(OUT_DIR / "dataset.parquet")

        # ---- quality report ----
        funding_cov = frame["funding_rate"].notna().mean()
        oi_cov = frame["open_interest"].notna().mean()
        f = frame["funding_rate"].dropna()
        spread = frame["perp_close"] / frame["spot_close"] - 1.0
        quality = {
            "n_bars": len(frame),
            "start": str(frame.index[0]),
            "end": str(frame.index[-1]),
            "funding_coverage": float(funding_cov),
            "oi_coverage": float(oi_cov),
            "n_funding_points": int(f.notna().sum()),
            "funding_min": float(f.min()),
            "funding_max": float(f.max()),
            "funding_mean_abs": float(f.abs().mean()),
            "funding_extreme_gt_10bp": int((f.abs() > 0.001).sum()),
            "funding_extreme_gt_5bp": int((f.abs() > 0.0005).sum()),
            "funding_extreme_gt_3bp": int((f.abs() > 0.0003).sum()),
            "oi_min": float(frame["open_interest"].dropna().min()),
            "oi_max": float(frame["open_interest"].dropna().max()),
            "spread_mean_bps": float(spread.mean() * 10_000),
            "spread_std_bps": float(spread.std() * 10_000),
            "spread_min_bps": float(spread.min() * 10_000),
            "spread_max_bps": float(spread.max() * 10_000),
        }
        (OUT_DIR / "quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
        print(json.dumps(quality, indent=2, ensure_ascii=False))
        print(f"\n✓ dataset saved: {OUT_DIR / 'dataset.parquet'}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
