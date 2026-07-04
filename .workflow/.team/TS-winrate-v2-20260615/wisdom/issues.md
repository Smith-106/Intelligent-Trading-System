# Issues Log

## ISS-1: profit_target_exit long-only bug [severity=critical]
- _runtime.py:167 only handles close >= entry_price * (1+pct), never close <= entry_price * (1-pct) for shorts
- Affects: mean_reversion, volatility_breakout (both generate short entries)
- Found by: ANT-1-4

## ISS-5: mean_reversion on_bar() missing profit_target_exit + max_holding_bars [severity=high]
- mean_reversion.py:107-109 exit logic only checks bb band proximity + RSI
- generate_signals() at line 146 has profit_target_exit but on_bar() does not
- Live/paper trading holds positions indefinitely if price never returns to opposite band
- Found by: ANT-1-3

## ISS-6: YAML config key mismatch makes YAML values dead letters [severity=high]
- YAML uses take_profit_pct but code reads profit_take_pct -- key name mismatch
- mean_reversion YAML: take_profit_pct=0.05, code default profit_take_pct=0.03
- trailing_stop_pct in YAML not read by any strategy code
- trend_following YAML: take_profit_pct=0.15, code default=0.10
- Found by: ANT-1-3

## ISS-7: mean_reversion volume_threshold code default=0.8 is trivially satisfied [severity=medium]
- volume_threshold=0.8 means vol_ok when volume > 80% of MA -- nearly always true
- YAML sets it to 1.2 (meaningful filter) but code default dominates
- This inflates entry count with weak signals that reduce win rate
- Found by: ANT-1-3
- trend_following.py:287 and volatility_breakout.py:391 track only highest, never lowest
- Short positions have zero trailing stop protection
- Found by: ANT-1-4

## ISS-3: BacktestEngine long-only masks short bugs [severity=critical]
- backtest.py:63 documents long-only; short entries simulated as longs
- Validation pipeline (CPCV/DSR/WFO) runs through this engine, hiding all short-side failures
- Found by: ANT-1-4

## ISS-4: Stop-loss in YAML never wired into generate_signals [severity=high]
- stop_loss_pct and stop_loss_atr_multiplier in YAML configs are dead parameters
- Only momentum_rotation.py:37 uses stop_loss_pct
- Losing trades run to max_holding_bars timeout without stop-loss, causing oversized losses
- Found by: ANT-1-4
- **Updated**: ANT-2-3 confirms this is #1 win rate killer — losing trades at -15-25% while winners exit early at profit_target

## ISS-8: No regime detection — all strategies fire blindly [severity=critical]
- Grep for 'regime' returns only momentum_rotation.py:17 docstring comment
- trend_following fires in ranging markets (low win rate), mean_reversion fires in trending markets (low win rate)
- MTFAligner exists (mtf_aligner.py) but never imported by strategy templates
- ADX computed but never consumed as regime indicator
- Estimated 8-15% win rate penalty from regime-inappropriate trades
- Found by: ANT-2-1, ANT-2-3

## ISS-9: Trailing stop tracks highest CLOSE not HIGH [severity=high]
- Using close instead of high as trailing anchor makes stops too tight, causing premature exits
- Affects trend_following.py:287 and volatility_breakout.py:391
- Found by: ANT-2-3

## ISS-10: volatility_breakout always emits Direction.LONG [severity=high]
- _latest_signal() returns boolean, losing directionality
- Short breakout signals completely lost
- Found by: ANT-2-3

## ISS-11: trend_following exit uses Direction.SHORT instead of FLAT [severity=medium]
- Exit signals create new short positions instead of closing long positions
- Found by: ANT-2-3

## ISS-12: consolidate_signals() never called [severity=medium]
- engine.py:150-156 flush_signals() goes directly to _process_signal(), skipping consolidation
- Conflicting strategies can open opposing positions (self-hedging)
- Found by: ANT-2-3, ANT-2-4

## ISS-13: Signal strength hardcoded, never varies with condition count [severity=high]
- trend_following strength=0.8 (always), mean_reversion=0.7 (always), volatility_breakout=0.8 (always)
- Condition count computed but only used for binary threshold, not mapped to strength
- Found by: ANT-2-1, ANT-2-3, ANT-2-4

## ISS-14: BacktestEngine exit timing mismatch [severity=high]
- Signals fire at bar N close but execute at bar N+1 open in backtest
- Every trailing stop and profit target exit delayed by 1 bar
- Reduces realized win rate by 2-4%
- Found by: ANT-2-2

## ISS-15: signal_quality_metrics hit_rate uses 1-bar proxy [severity=high]
- hit_rate = precision of (forward_returns > 0), not full trade lifecycle win rate
- 5-10% gap between validated and realized win rate
- CPCV/WFO validation pipeline uses this inflated metric as GO/NO-GO gate
- Found by: ANT-2-2

## ISS-16: vol_ok required in exit conditions [severity=medium]
- trend_following.py:168-170 exit requires vol_ok same as entry
- Reversals often occur on LOW volume (distribution phase)
- Delays exits during critical reversal periods
- Found by: ANT-2-2

## ISS-17: 4/6 strategies have ZERO trailing stop [severity=critical]
- elliott_wave.py, funding_rate.py, momentum_rotation.py, ml_ensemble.py have no trailing stop at all
- mean_reversion.py also lacks trailing stop
- Only trend_following and volatility_breakout have trailing stop
- Losing trades in these strategies run unbounded to max_holding timeout
- Found by: ANT-3-1

## ISS-18: Trailing stop direction-unaware — tracks highest for all entries including shorts [severity=critical]
- volatility_breakout.py:372 entries = (long_count >= min) | (short_count >= min) — includes short entries
- volatility_breakout.py:385-396 trailing stop only tracks highest — completely wrong for short entries
- trend_following.py:281-292 same pattern
- Short positions have zero effective trailing stop protection
- Found by: ANT-3-1

## ISS-19: on_bar() path lacks ALL exit mechanisms in 4 strategies [severity=critical]
- trend_following.py:106-122 on_bar only uses _latest_signal() — no profit_target, no trailing stop, no max_holding
- mean_reversion.py:64-80 on_bar only checks bb proximity + RSI
- volatility_breakout.py:114-130 on_bar only checks atr_shrink + middle_return
- funding_rate.py:71-86 on_bar only checks neutral_zone + oi_reversal
- Live/paper positions can run indefinitely without systematic exit
- Found by: ANT-3-1

## ISS-20: YAML key bridge missing — ALL 6 strategies affected [severity=high]
- All 6 strategies: YAML take_profit_pct not read by code (code reads profit_take_pct)
- trend_following: YAML trailing_stop_atr_multiplier vs code trailing_stop_atr_mult
- volatility_breakout: same trailing_stop_atr_multiplier mismatch
- Result: YAML values are dead letters, code uses lower defaults
- Funding_rate: YAML take_profit_pct=0.06 vs code profit_take_pct=0.02 (3x gap)
- Momentum_rotation: YAML take_profit_pct=0.08 vs code profit_take_pct=0.04 (2x gap)
- Found by: ANT-3-1 (extends ISS-6 to all 6 strategies)

## ISS-21: Trailing stop tracks CLOSE not HIGH — premature exits [severity=high]
- trend_following.py:281 highest = close.copy() — should use high column
- volatility_breakout.py:385 same pattern
- Using close instead of high makes stops too tight — intrabar high extends further than close
- Found by: ANT-2-3, confirmed by: ANT-3-1
