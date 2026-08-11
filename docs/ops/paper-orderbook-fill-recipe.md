# Paper orderbook fill recipe (IMP-09)

**Date**: 2026-08-11  
**Status**: optional fidelity experiment — **default OFF**  
**Related**: W16 paper fill · `quantflow/config/paper_orderbook_fill_overlay.yaml`

## Purpose

Enable BBO (bid/ask) touch fills on **paper** mode for microstructure fidelity tests.
Does **not** change live gateway behavior and is not required for T023/T024 ops.

## Recipe (merge overlay)

```bash
set PYTHONUTF8=1
# Example: paper run with orderbook fill overlay (operator present)
python -c "from quantflow.cli.main import app"  # ensure install
# Preferred CLI form when quantflow entry is available:
# quantflow run --mode paper --strategy trend_following \
#   --config quantflow/config/paper_orderbook_fill_overlay.yaml
```

Overlay essentials (`quantflow/config/paper_orderbook_fill_overlay.yaml`):

| Key | Default in overlay | Meaning |
|-----|--------------------|---------|
| `execution.orderbook_fill.enabled` | true | Use bid/ask touch when BBO present |
| `extra_slippage` | 0.0 | Extra slip on top of touch |
| `bbo_max_age_sec` | 5.0 | Reject stale BBO (0 = off) |

## Feed BBO into the gateway

Paper gateway must receive order book updates:

```python
gateway.update_orderbook(symbol, bid, ask)
```

Without BBO updates, fills **fall back** to last price + flat slippage (safe degrade).

## When to use

| Use | Avoid |
|-----|--------|
| Microstructure / fill-model A/B on paper | Daily T023 preflight (keep baseline overlay) |
| Comparing touch vs mid/last fill impact | Claiming live parity from paper BBO alone |

## Honesty

- paper_replay vectorized research paths do **not** auto-enable this overlay.
- Parity remains **paper↔live** abstract execution; BBO fidelity is an optional paper layer.
- Do not lower promote sample floors because orderbook fills look “more real”.

## See also

- [w16-paper-fill-and-strategy-dx.md](../research/w16-paper-fill-and-strategy-dx.md)
- [w17-orderbook-microstructure.md](../research/w17-orderbook-microstructure.md)
- Baseline paper overlay: `quantflow/config/paper_baseline0_overlay.yaml`
