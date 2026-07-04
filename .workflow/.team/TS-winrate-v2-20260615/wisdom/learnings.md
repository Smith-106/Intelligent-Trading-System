# Cross-Iteration Learnings

## Round 1 Results (TS-winrate-20260613)
- 3 major gaps identified and fixed: no profit targets, AND-entry too strict, Sharpe-only validation
- All 15 code changes implemented in P1-P4
- Estimated win rate improvement: 40-50% → 55-65% (needs backtest verification)

## Iteration 2 Findings (ANT-2-1)
- **CRITICAL**: No regime detection exists at all — grep for 'regime' returns only momentum_rotation.py:17 docstring comment
- **HIGH**: MTFAligner class exists (mtf_aligner.py:1-205) but never imported by any strategy template; only elliott_wave references it
- **HIGH**: Signal strengths hardcoded per strategy (0.5-0.8) regardless of condition count or market context
- **HIGH**: TradingSession engine.py:91 equal 1/N allocation regardless of strategy performance
- Confirmed iter1: engine.py:54 RiskEngine without strategy_risk_budgets, engine.py:208 PositionSizer.size() without strategy_win_rates
- 5 bottleneck clusters: (CL-1) no regime, (CL-2) MTF unused, (CL-3) dead per-strategy features, (CL-4) condition count not mapped to strength, (CL-5) long-only BacktestEngine
- Estimated combined win rate impact: +20-35% if all 5 clusters fixed
- Priority order: CL-1 (regime) > CL-5 (long-only) > CL-3 (dead features) > CL-2 (MTF) > CL-4 (strength mapping)

## Iteration 2 Findings (ANT-2-2)
- **NEW**: RSI-adaptive profit targets use global mean (rsi[entries].mean()) not per-entry RSI, making feature dead code — with 100+ entries avg converges to ~50
- **NEW**: BacktestEngine exit timing mismatch -- signals fire at bar N close but execute at bar N+1 open, reducing realized win rate by 2-4%
- **NEW**: signal_quality_metrics hit_rate uses 1-bar next-bar return as win proxy, not full trade lifecycle -- validation overestimates win rate by 5-10%
- **NEW**: Exit conditions require vol_ok, delaying exits during low-volume reversals (should be looser than entry)
- **NEW**: YAML trailing_stop_atr_multiplier vs code trailing_stop_atr_mult key mismatch -- YAML sets 1.5 but code defaults to 3.0
- **Calibration**: trend_following trailing_stop_atr_mult=3.0 too wide (YAML wants 1.5); mean_reversion max_holding_bars=10 too short for 4h; volume_threshold=0.8 trivially satisfied
- profit_target_exit() now in _runtime.py and wired into all 6 templates
- min_conditions defaults: trend=4, mean_rev=2, vol_breakout=5
- Trailing stops added to trend_following (ATR*3.0) and volatility_breakout (ATR*2.5)
- Mean reversion exit changed from bb_middle to opposite band × 0.98
- RSI-adaptive profit targets in trend_following
- Strength-weighted consolidation with strategy_hit_rates
- Per-strategy risk budgets in RiskEngine
- Per-strategy Kelly sizing in PositionSizer

## Iteration 2 Findings (ANT-2-3)
- **CRITICAL**: YAML stop_loss_pct NEVER wired into generate_signals — trend_following & mean_reversion have zero stop-loss; losing trades run to max_holding_bars timeout at -15-25%
- **HIGH**: Trailing stop tracks highest CLOSE not HIGH — premature exits on valid pullbacks
- **HIGH**: volatility_breakout always emits Direction.LONG — _latest_signal() returns boolean, losing directionality
- **HIGH**: ADX computed but never consumed — no regime detection mechanism
- **MEDIUM**: consolidate_signals() never called — conflicting strategies open opposing positions (self-hedging)
- **MEDIUM**: trend_following exit uses Direction.SHORT instead of FLAT — opens new short instead of closing long
- **MEDIUM**: All strategies use hardcoded signal strength — no quality or regime discrimination
- Systemic YAML wiring issue: every YAML config defines stop_loss_pct, take_profit_pct, trailing_stop_atr_multiplier but code param names differ

## Iteration 2 Findings (ANT-2-4)
- Confirmed all major findings from ANT-2-1 through ANT-2-3
- Added: vol_breakout min_conditions=5 nearly impossible (ALL 5 conditions required)
- Added: mean_reversion effective min_conditions = 1 of 2 (vol_ok ~always True)
- YAML take_profit_pct vs code profit_take_pct key mismatch confirmed across all 3 strategies

## Iteration 2 Findings (ANT-1-3)
- **CRITICAL**: profit_target_exit() only works for LONG direction; SHORT positions never hit profit target (target = entry*(1+pct), check close >= target)
- **HIGH**: mean_reversion on_bar() path has no profit_target or max_holding check -- only generate_signals() has it
- **HIGH**: YAML config keys (take_profit_pct, trailing_stop_pct) don't match code param names (profit_take_pct) -- YAML values may be dead letters
- mean_reversion volume_threshold code default=0.8 (nearly always true) vs YAML=1.2 (meaningful filter)

## Iteration 3 Findings (ANT-3-1)
- **CRITICAL**: 4/6 strategies have ZERO trailing stop — elliott_wave, funding_rate, momentum_rotation, ml_ensemble completely lack it
- **CRITICAL**: on_bar() path lacks ALL exit mechanisms (profit_target, trailing stop, max_holding) in 4 strategies — live/paper positions run indefinitely
- **CRITICAL**: vol_breakout entries include both long AND short (line 372) but trailing stop only tracks highest — wrong for shorts
- **HIGH**: YAML key bridge affects ALL 6 strategies, not just 3 — funding_rate and momentum_rotation also have take_profit_pct vs profit_take_pct mismatch (0.06 vs 0.02, 0.08 vs 0.04)
- **HIGH**: Trailing stop should track HIGH/LOW not CLOSE — close is always <= high, causing premature exits on valid pullbacks
- Confirmed: profit_target_exit() LONG-only (_runtime.py:167) — no direction param
- Confirmed: max_holding_bars correctly overrides trailing stop (implemented inside profit_target_exit)
- Confirmed: profit_target and trailing_stop interaction is correct (both OR into exits, state machine resets properly)
- New priority order for exit fixes: on_bar exits > direction profit_target > direction trailing > YAML bridge > add trailing to 4 strategies > min_conditions > RSI per-entry
