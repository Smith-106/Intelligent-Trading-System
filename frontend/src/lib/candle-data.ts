/**
 * Candle data normalization for lightweight-charts (UI-REV016).
 *
 * The chart library requires `time` to be strictly ascending and unique —
 * violations throw mid-render. Never trust the wire format: sort, dedupe,
 * and convert ms→s here.
 */

import type { CandlestickData, HistogramData, UTCTimestamp } from "lightweight-charts";

/** Wire format from /api/analysis/multi-tf (epoch milliseconds). */
export interface RawCandle {
  timestamp: number; // epoch milliseconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Chart-ready candle — `time` is epoch SECONDS (lightweight-charts unit). */
interface NormalizedCandle {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/**
 * REV-017-RV1 (critical fix): convert exactly ONCE. The previous version
 * normalized ms->s here and then the converters divided by 1000 again,
 * collapsing every bar into Jan-1970 with duplicate times — setData threw.
 * Dedupe keeps the LAST occurrence so a re-sent final bar wins over a stale
 * copy (REV-017-RV5 direction flip).
 */
function normalizeCandles(raw: RawCandle[]): NormalizedCandle[] {
  if (!Array.isArray(raw)) return [];
  const byTime = new Map<number, NormalizedCandle>();
  for (const c of raw) {
    if (!Array.isArray(raw) || c == null || typeof c.timestamp !== "number") continue;
    const t = Math.floor(c.timestamp / 1000);
    if (!Number.isFinite(t)) continue;
    byTime.set(t, {
      time: t as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
      volume: c.volume,
    });
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

/** Shared single pass for both converters (REV-017-RV5). */
export function prepareCandles(raw: RawCandle[]): NormalizedCandle[] {
  return normalizeCandles(raw);
}

export function toCandlestickData(normalized: NormalizedCandle[]): CandlestickData[] {
  return normalized.map((c) => ({
    time: c.time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}

/** Volume histogram colored by bar direction (project convention: green up). */
export function toVolumeData(
  normalized: NormalizedCandle[],
  upColor: string,
  downColor: string,
): HistogramData[] {
  return normalized.map((c) => ({
    time: c.time,
    value: c.volume,
    color: c.close >= c.open ? upColor : downColor,
  }));
}
