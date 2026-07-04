# Config Decisions

## ANT-1-4 Iteration 1: Exit Direction Awareness Required
- profit_target_exit and trailing stop must handle both long and short directions
- BacktestEngine must support short positions to surface short-side bugs
- Signal strength should be computed from condition count, not hardcoded
- Stop-loss in YAML configs must be wired into generate_signals()
- Exit conditions should NOT require volume confirmation (unlike entry)

## ANT-2-1/2/3 Iteration 2: Architecture-Level Gaps
- Regime detection is the single highest-impact addition — prevents regime-inappropriate trades
- MTFAligner should be wired as pre-filter before entry signals
- Per-strategy features in TradingSession must be wired (CL-3: engine.py never passes params)
- YAML-to-code key mapping must be fixed systematically (config bridge)
- consolidate_signals() must be inserted in the signal pipeline
- Stop-loss is #1 win rate killer — zero stop-loss means losers run to timeout at -15-25%
- Direction handling must be fixed across the entire chain (profit_target, trailing stop, vol_breakout directionality)
- Long-only BacktestEngine fix is prerequisite — otherwise all short-side improvements are unmeasurable

## ANT-3-1 Iteration 3: Exit Mechanism Gaps Are Systemic
- 4/6 strategies have zero trailing stop — this is not a calibration issue, it's an absence issue
- on_bar() path (live/paper) lacks ALL exit mechanisms in 4 strategies — this is a production risk, not just a backtest issue
- YAML-to-code key bridge must be systematic (affect all 6 strategies, not just 3)
- Trailing stop direction awareness must be added alongside profit_target direction awareness — both are LONG-only
- Trailing stop should track HIGH (not CLOSE) for longs and LOW (not CLOSE) for shorts
- Priority: fix_7 (on_bar exits) > fix_1 (direction profit_target) > fix_2 (direction trailing) > fix_4 (YAML bridge) > fix_3 (add trailing to 4 strategies) > fix_6 (min_conditions) > fix_5 (RSI per-entry)
