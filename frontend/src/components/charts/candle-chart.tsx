/**
 * CandleChart — pure renderer over lightweight-charts v4 (UI-REV016).
 *
 * Lifecycle contract (React 19 StrictMode double-mount safe):
 * effect 1 (mount-only) creates the chart; cleanup MUST call chart.remove()
 * to release the canvas and internal ResizeObserver. Effect 2 swaps data
 * via setData — never rebuilds the chart on TF change.
 *
 * Canvas ignores CSS variables, so theme colors are resolved from
 * getComputedStyle at render time and re-applied when the theme flips.
 */

import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { prepareCandles, toCandlestickData, toVolumeData, type RawCandle } from "@/lib/candle-data";

interface ChartTheme {
  background: string;
  textColor: string;
  gridLine: string;
  border: string;
  upColor: string;
  downColor: string;
}

function resolveTheme(): ChartTheme {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string): string =>
    css.getPropertyValue(name).trim() || fallback;
  return {
    background: v("--card", "#111318"),
    textColor: v("--muted-foreground", "#8b8f98"),
    gridLine: v("--border", "#262a31"),
    border: v("--border", "#262a31"),
    // project-wide green-up/red-down convention
    upColor: v("--status-go", "#22c55e"),
    downColor: v("--status-danger", "#ef4444"),
  };
}

interface CandleChartProps {
  candles: RawCandle[];
  showVolume?: boolean;
  className?: string;
}

export function CandleChart({ candles, showVolume = true, className }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // REV-017-RV2: keep the latest inputs so the theme observer can rebuild the
  // volume colors baked into per-bar HistogramData (series options can't).
  const dataRef = useRef<{ candles: RawCandle[]; showVolume: boolean }>({
    candles: [],
    showVolume: true,
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const t = resolveTheme();
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: t.background },
        textColor: t.textColor,
        fontFamily: "inherit",
      },
      crosshair: { mode: CrosshairMode.Normal },
      grid: {
        vertLines: { color: t.gridLine },
        horzLines: { color: t.gridLine },
      },
      rightPriceScale: { borderColor: t.border },
      timeScale: { borderColor: t.border, timeVisible: true, secondsVisible: false },
    });
    const candle = chart.addCandlestickSeries({
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      upColor: t.upColor,
      downColor: t.downColor,
      borderUpColor: t.upColor,
      borderDownColor: t.downColor,
      wickUpColor: t.upColor,
      wickDownColor: t.downColor,
    });
    const volume = chart.addHistogramSeries({
      priceScaleId: "",
      priceFormat: { type: "volume" },
      priceLineVisible: false,
    });
    chart.priceScale("").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    chartRef.current = chart;
    candleSeriesRef.current = candle;
    volumeSeriesRef.current = volume;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  // Theme flip: re-resolve concrete colors and apply to the live chart.
  useEffect(() => {
    const unsub = (() => {
      let last = document.documentElement.classList.contains("dark");
      const observer = new MutationObserver(() => {
        const dark = document.documentElement.classList.contains("dark");
        if (dark === last) return;
        last = dark;
        const chart = chartRef.current;
        const candle = candleSeriesRef.current;
        if (!chart || !candle) return;
        const t = resolveTheme();
        chart.applyOptions({
          layout: { background: { type: ColorType.Solid, color: t.background }, textColor: t.textColor },
          grid: { vertLines: { color: t.gridLine }, horzLines: { color: t.gridLine } },
          rightPriceScale: { borderColor: t.border },
          timeScale: { borderColor: t.border },
        });
        candle.applyOptions({
          upColor: t.upColor,
          downColor: t.downColor,
          borderUpColor: t.upColor,
          borderDownColor: t.downColor,
          wickUpColor: t.upColor,
          wickDownColor: t.downColor,
        });
        const { candles: cur, showVolume: vol } = dataRef.current;
        if (vol && volumeSeriesRef.current && cur.length > 0) {
          volumeSeriesRef.current.setData(
            toVolumeData(prepareCandles(cur), `${t.upColor}66`, `${t.downColor}66`),
          );
        }
      });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
      return () => observer.disconnect();
    })();
    return unsub;
  }, []);

  useEffect(() => {
    const candle = candleSeriesRef.current;
    const volume = volumeSeriesRef.current;
    dataRef.current = { candles, showVolume };
    if (!candle || !volume) return;
    const t = resolveTheme();
    const normalized = prepareCandles(candles);
    const candleData: CandlestickData[] = toCandlestickData(normalized);
    const volumeData: HistogramData[] = showVolume
      ? toVolumeData(normalized, `${t.upColor}66`, `${t.downColor}66`)
      : [];
    candle.setData(candleData);
    volume.setData(volumeData);
    if (candleData.length > 0) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [candles, showVolume]);

  return <div ref={containerRef} className={className ?? "h-full w-full"} />;
}
