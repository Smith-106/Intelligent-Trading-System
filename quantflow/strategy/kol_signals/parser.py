"""Parse free-text KOL / alert messages into structured trade intents.

Handles common CN/EN crypto copy-trade phrasing and TradingView-style alerts.
Not perfect NLP — designed to be fail-soft with confidence scores.
"""

from __future__ import annotations

import re
from typing import Any

from quantflow.strategy.kol_signals.models import SignalSide

# Direction keywords (order matters for first-match scoring)
_LONG_PAT = re.compile(r"(?i)\b(long|buy|bullish|开多|做多|多单|买入|看多|追多|breakout\s*long)\b")
_SHORT_PAT = re.compile(
    r"(?i)\b(short|sell|bearish|开空|做空|空单|卖出|看空|追空|breakdown\s*short)\b"
)
_FLAT_PAT = re.compile(
    r"(?i)\b(close|exit|flat|平仓|止盈离场|清仓|take\s*profit\s*all|reduce\s*only)\b"
)

# BTCUSDT / BTC/USDT / $BTC / 比特币
_SYMBOL_PATS = [
    re.compile(r"(?i)\b([A-Z]{2,10})\s*/\s*(USDT|USD|USDC|BUSD|PERP)\b"),
    re.compile(r"(?i)\b([A-Z]{2,10})(USDT|USD|USDC|PERP)\b"),
    re.compile(r"(?i)\$([A-Z]{2,10})\b"),
]
_CN_SYMBOL = {
    "比特币": "BTC/USDT",
    "以太坊": "ETH/USDT",
    "以太": "ETH/USDT",
    "狗狗": "DOGE/USDT",
    "索拉纳": "SOL/USDT",
    "sol": "SOL/USDT",
}

_ENTRY_PAT = re.compile(
    r"(?i)(?:entry|进场|入场|开仓|现价|price|@)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)"
)
_SL_PAT = re.compile(r"(?i)(?:sl|s/l|stop(?:\s*loss)?|止损)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)")
_TP_PAT = re.compile(r"(?i)(?:tp\d*|t/p|take\s*profit|止盈)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)")
_TF_PAT = re.compile(r"(?i)\b(1m|3m|5m|15m|30m|45m|1h|2h|4h|6h|12h|1d|1w|日线|小时线|4小时)\b")


def _normalize_symbol(raw: str, quote: str | None = None) -> str:
    s = raw.upper().replace("-", "").replace("_", "")
    if quote:
        q = quote.upper().replace("PERP", "USDT")
        return f"{s}/{q}"
    if s.endswith("USDT"):
        return f"{s[:-4]}/USDT"
    if s.endswith("USD"):
        return f"{s[:-3]}/USDT"
    if s.endswith("USDC"):
        return f"{s[:-4]}/USDC"
    if s.endswith("PERP"):
        return f"{s[:-4]}/USDT"
    # bare base — default USDT pair for crypto KOLs
    if len(s) <= 10:
        return f"{s}/USDT"
    return s


def extract_symbol(text: str) -> tuple[str, float]:
    """Return (symbol, confidence). Empty symbol if none found."""
    for cn, sym in _CN_SYMBOL.items():
        if cn in text.lower() or cn in text:
            return sym, 0.7
    for pat in _SYMBOL_PATS:
        m = pat.search(text)
        if not m:
            continue
        if pat.groups == 2 and m.lastindex and m.lastindex >= 2:
            return _normalize_symbol(m.group(1), m.group(2)), 0.9
        return _normalize_symbol(m.group(1)), 0.75
    return "", 0.0


def extract_side(text: str) -> tuple[SignalSide, float]:
    long_m = bool(_LONG_PAT.search(text))
    short_m = bool(_SHORT_PAT.search(text))
    flat_m = bool(_FLAT_PAT.search(text))
    if long_m and short_m:
        return SignalSide.UNKNOWN, 0.2
    if flat_m and not long_m and not short_m:
        return SignalSide.FLAT, 0.7
    if long_m:
        return SignalSide.LONG, 0.85
    if short_m:
        return SignalSide.SHORT, 0.85
    return SignalSide.UNKNOWN, 0.0


def extract_levels(text: str) -> dict[str, Any]:
    entry = None
    m = _ENTRY_PAT.search(text)
    if m:
        entry = float(m.group(1))
    sl = None
    m = _SL_PAT.search(text)
    if m:
        sl = float(m.group(1))
    tps = [float(x) for x in _TP_PAT.findall(text)]
    return {"entry": entry, "stop_loss": sl, "take_profit": tps}


def extract_timeframe(text: str) -> str:
    m = _TF_PAT.search(text)
    if not m:
        return ""
    tf = m.group(1)
    mapping = {"日线": "1d", "小时线": "1h", "4小时": "4h"}
    return mapping.get(tf, tf.lower())


def parse_trade_text(text: str) -> dict[str, Any]:
    """Parse message text into structured fields + confidence + notes."""
    notes: list[str] = []
    if not text or not str(text).strip():
        return {
            "side": SignalSide.UNKNOWN,
            "symbol": "",
            "entry": None,
            "stop_loss": None,
            "take_profit": [],
            "timeframe": "",
            "confidence": 0.0,
            "parse_notes": ["empty_text"],
        }

    raw = str(text)
    side, side_c = extract_side(raw)
    symbol, sym_c = extract_symbol(raw)
    levels = extract_levels(raw)
    tf = extract_timeframe(raw)

    conf = 0.0
    if side != SignalSide.UNKNOWN:
        conf += 0.45 * side_c
    else:
        notes.append("side_unknown")
    if symbol:
        conf += 0.40 * sym_c
    else:
        notes.append("symbol_unknown")
    if levels["entry"] is not None or levels["stop_loss"] is not None or levels["take_profit"]:
        conf += 0.15
        notes.append("levels_present")
    if tf:
        notes.append(f"tf={tf}")

    # Chart-only posts often have no parseable levels
    if conf < 0.3 and ("http" in raw.lower() or "chart" in raw.lower()):
        notes.append("likely_media_heavy")

    conf = max(0.0, min(1.0, conf))
    return {
        "side": side,
        "symbol": symbol,
        "entry": levels["entry"],
        "stop_loss": levels["stop_loss"],
        "take_profit": levels["take_profit"],
        "timeframe": tf,
        "confidence": round(conf, 4),
        "parse_notes": notes,
    }
