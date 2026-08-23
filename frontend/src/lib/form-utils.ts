/**
 * UI3-H2: NaN-safe numeric input coercion. `Number("")` is 0 (a cleared
 * capital field silently became 0) and garbage strings become NaN, which
 * JSON.stringify serializes as null for the backend. Non-finite input falls
 * back to `fallback` instead.
 */
export function toFiniteNumber(raw: string, fallback = 0): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}
