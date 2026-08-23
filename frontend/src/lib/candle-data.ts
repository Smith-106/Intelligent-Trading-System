/**
 * Candle data normalization for lightweight-charts (UI-REV016).
 *
 * The chart library requires `time` to be strictly ascending and unique —
 * violations throw mid-render. Never trust the wire format: sort, dedupe,
 * and convert ms→s here.
 */

import type { CandlestickData, HistogramData, UTCTimestamp } from "lightweight-charts";

export interface RawCandle {
  timestamp: number; // epoch milliseconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Sort ascending + dedupe by second-resolution time. Empty/single safe. */
function normalizeCandles(raw: RawCandle[]): RawCandle[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<number>();
  return raw
    .map((c) => ({ ...c, _t: Math.floor(c.timestamp / 1000) }))
    .filter((c) => {
      if (seen.has(c._t)) return false;
      seen.add(c._t);
      return true;
    })
    .sort((a, b) => a._t - b._t)
    .map(({ _t, ...rest }) => ({ ...rest, timestamp: _t as unknown as number }));
}

export function toCandlestickData(raw: RawCandle[]): CandlestickData[] {
  return normalizeCandles(raw).map((c) => ({
    time: Math.floor(c.timestamp / 1000) as UTCTimestamp,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}

/** Volume histogram colored by bar direction (project convention: green up). */
export function toVolumeData(raw: RawCandle[], upColor: string, downColor: string): HistogramData[] {
  return normalizeCandles(raw).map((c) => ({
    time: Math.floor(c.timestamp / 1000) as UTCTimestamp,
    value: c.volume,
    color: c.close >= c.open ? upColor : downColor,
  }));
}
