# W25 — B4 meta-window + Elliott assert + multi-symbol trades

**Date**: 2026-08-10  
**Parent**: [w24-b4-reseat-watch.md](./w24-b4-reseat-watch.md)

## Delivered

### W25a — B4 meta-window scaffold
- `run_baseline4_challenger.py --meta-window --run-id <id>`
- Independent artifacts under `baseline4/<run_id>/`
- BLOCKED when OHLCV/funding sparse; META_SMOKE when replay ok
- Still refuses `baseline3/`; default KEEP_B0

### W25b — Elliott cost package assert
- `scripts/assert_elliott_cost_package.py`
- Path + fee×slip + funding_tca structure
- `--build` synthetic package; exit 1 on structure fail
- **Not** auto-GO

### W25c — Multi-symbol trades
- `quantflow/data/multi_symbol_trades.py`
- `build_multi_symbol_trades_ingest` + per-symbol stats

## Tests
```bash
pytest tests/unit/test_w25_meta_assert_multi.py -q
```
