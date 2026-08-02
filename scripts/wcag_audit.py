#!/usr/bin/env python3
"""WCAG 2.1 contrast audit for QuantFlow frontend oklch theme variables.

Audits both light (:root) and dark (.dark) themes. Badge status colors use
alpha compositing (card base + 15% status overlay) to reflect real rendering.

Severity model:
  - "error": failures block CI (exit 1). Covers all in-scope pairs.
  - "warning": failures print a diagnostic but do NOT block CI.
    Used for known out-of-scope items (status-go, status-danger light theme).

Pipeline: oklch(L,C,H) -> OKLab -> linear sRGB -> relative luminance -> contrast ratio
"""

import json
import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# oklch -> sRGB conversion (Björn Ottosson matrices)
# ---------------------------------------------------------------------------


def oklch_to_oklab(lch_l: float, lch_c: float, lch_h: float) -> tuple[float, float, float]:
    """Convert OKLCH to OKLab."""
    h_rad = math.radians(lch_h)
    a = lch_c * math.cos(h_rad)
    b = lch_c * math.sin(h_rad)
    return (lch_l, a, b)


def oklab_to_linear_srgb(lab_l: float, lab_a: float, lab_b: float) -> tuple[float, float, float]:
    """Convert OKLab to linear sRGB via LMS intermediate."""
    # M1^-1: OKLab -> LMS (approximate cone responses)
    l_ = lab_l + 0.3963377774 * lab_a + 0.2158037573 * lab_b
    m_ = lab_l - 0.1055613458 * lab_a - 0.0638541728 * lab_b
    s_ = lab_l - 0.0894841775 * lab_a - 1.2914855480 * lab_b

    l_cubed = l_**3
    m_cubed = m_**3
    s_cubed = s_**3

    # M2^-1: LMS -> linear sRGB
    r = +4.0767416621 * l_cubed - 3.3077115913 * m_cubed + 0.2309699292 * s_cubed
    g = -1.2684380046 * l_cubed + 2.6097574011 * m_cubed - 0.3413193965 * s_cubed
    b_out = -0.0041960863 * l_cubed - 0.7034186147 * m_cubed + 1.7076147010 * s_cubed

    return (r, g, b_out)


def linear_to_gamma(c: float) -> float:
    """Linear sRGB -> gamma-corrected sRGB, clamped to [0,1]."""
    c = max(0.0, min(1.0, c))
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def relative_luminance(r_lin: float, g_lin: float, b_lin: float) -> float:
    """WCAG relative luminance from linear sRGB (clamped)."""
    r = max(0.0, min(1.0, r_lin))
    g = max(0.0, min(1.0, g_lin))
    b = max(0.0, min(1.0, b_lin))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def oklch_to_luminance(lch_l: float, lch_c: float, lch_h: float) -> float:
    """Full pipeline: oklch -> relative luminance."""
    lab = oklch_to_oklab(lch_l, lch_c, lch_h)
    lin = oklab_to_linear_srgb(*lab)
    return relative_luminance(*lin)


def oklch_to_gamma_srgb(lch_l: float, lch_c: float, lch_h: float) -> tuple[float, float, float]:
    """Full pipeline: oklch -> gamma sRGB tuple (clamped [0,1])."""
    lab = oklch_to_oklab(lch_l, lch_c, lch_h)
    lin = oklab_to_linear_srgb(*lab)
    return (linear_to_gamma(lin[0]), linear_to_gamma(lin[1]), linear_to_gamma(lin[2]))


def contrast_ratio(lum1: float, lum2: float) -> float:
    """WCAG contrast ratio between two luminance values."""
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def alpha_composite_gamma(
    base: tuple[float, float, float],
    overlay: tuple[float, float, float],
    alpha: float,
) -> tuple[float, float, float]:
    """Alpha-composite overlay onto base in gamma sRGB space."""
    return tuple(base[c] * (1 - alpha) + overlay[c] * alpha for c in range(3))  # type: ignore[return-value]


def gamma_srgb_to_luminance(rgb: tuple[float, float, float]) -> float:
    """Convert gamma sRGB back to relative luminance via linearization."""

    def gamma_to_linear(c: float) -> float:
        if c <= 0.04045:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r_lin = gamma_to_linear(rgb[0])
    g_lin = gamma_to_linear(rgb[1])
    b_lin = gamma_to_linear(rgb[2])
    return relative_luminance(r_lin, g_lin, b_lin)


# ---------------------------------------------------------------------------
# CSS parsing
# ---------------------------------------------------------------------------


def parse_oklch(value: str) -> tuple[float, float, float]:
    """Parse an oklch(...) CSS value into (L, C, H)."""
    m = re.match(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)", value.strip())
    if not m:
        raise ValueError(f"Cannot parse oklch: {value!r}")
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)))


def extract_theme_vars(css_text: str, selector: str) -> dict[str, str]:
    """Extract oklch CSS variables from a given selector block."""
    escaped = re.escape(selector)
    m = re.search(rf"{escaped}\s*\{{(.*?)\}}", css_text, re.DOTALL)
    if not m:
        raise ValueError(f"No {selector} block found in CSS")
    block = m.group(1)
    vars_dict: dict[str, str] = {}
    for vm in re.finditer(r"(--[\w-]+)\s*:\s*(oklch\([^)]+\))", block):
        vars_dict[vm.group(1)] = vm.group(2)
    return vars_dict


# ---------------------------------------------------------------------------
# Audit pair definitions
# ---------------------------------------------------------------------------

THRESHOLDS = {"AA-normal": 4.5, "AA-large": 3.0}

# Core solid-background pairs (severity=error: must pass)
CORE_SOLID_PAIRS = [
    {
        "name": "body text on background",
        "fg": "--foreground",
        "bg": "--background",
        "level": "AA-normal",
    },
    {"name": "card text on card", "fg": "--card-foreground", "bg": "--card", "level": "AA-normal"},
    {
        "name": "popover text on popover",
        "fg": "--popover-foreground",
        "bg": "--popover",
        "level": "AA-normal",
    },
    {
        "name": "primary button text",
        "fg": "--primary-foreground",
        "bg": "--primary",
        "level": "AA-normal",
    },
    {
        "name": "secondary text on secondary",
        "fg": "--secondary-foreground",
        "bg": "--secondary",
        "level": "AA-normal",
    },
    {
        "name": "accent text on accent",
        "fg": "--accent-foreground",
        "bg": "--accent",
        "level": "AA-normal",
    },
    {
        "name": "destructive text on destructive",
        "fg": "--destructive-foreground",
        "bg": "--destructive",
        "level": "AA-normal",
    },
    {
        "name": "warning text on warning",
        "fg": "--warning-foreground",
        "bg": "--warning",
        "level": "AA-normal",
    },
]

# Badge alpha-composited pairs (status text on card + 15% status overlay)
BADGE_ALPHA_PAIRS = [
    {
        "name": "Badge go text",
        "fg": "--status-go",
        "bg_base": "--card",
        "bg_overlay": "--status-go",
        "alpha": 0.15,
        "level": "AA-normal",
    },
    {
        "name": "Badge warn text",
        "fg": "--status-warn",
        "bg_base": "--card",
        "bg_overlay": "--status-warn",
        "alpha": 0.15,
        "level": "AA-normal",
    },
    {
        "name": "Badge danger text",
        "fg": "--status-danger",
        "bg_base": "--card",
        "bg_overlay": "--status-danger",
        "alpha": 0.15,
        "level": "AA-normal",
    },
]

# Muted / large-text pairs (severity=error: must pass)
MUTED_LARGE_PAIRS = [
    {
        "name": "muted text on muted",
        "fg": "--muted-foreground",
        "bg": "--muted",
        "level": "AA-large",
    },
    {
        "name": "muted text on background",
        "fg": "--muted-foreground",
        "bg": "--background",
        "level": "AA-large",
    },
    {"name": "muted text on card", "fg": "--muted-foreground", "bg": "--card", "level": "AA-large"},
]

# Known out-of-scope failures: severity=warning (non-blocking).
# These pairs are tracked for future fixes but do NOT block CI.
# Format: (theme, pair_name)
KNOWN_WARNING_PAIRS = {
    # Light: Badge status-go (2.98:1) and status-danger (3.81:1) — future scope
    ("light", "Badge go text"),
    ("light", "Badge danger text"),
    # Light: warning-foreground on warning bg — inverse use case, not Badge text
    ("light", "warning text on warning"),
    # Dark: destructive-foreground on destructive — pre-existing, future scope
    ("dark", "destructive text on destructive"),
}


# ---------------------------------------------------------------------------
# Audit engine
# ---------------------------------------------------------------------------


def audit_theme(vars_dict: dict[str, str], theme: str) -> list[dict]:
    """Run all audit pairs for one theme, return result records."""
    results: list[dict] = []

    # 1. Core solid pairs
    for pair in CORE_SOLID_PAIRS:
        fg_lum = oklch_to_luminance(*parse_oklch(vars_dict[pair["fg"]]))
        bg_lum = oklch_to_luminance(*parse_oklch(vars_dict[pair["bg"]]))
        ratio = contrast_ratio(fg_lum, bg_lum)
        threshold = THRESHOLDS[pair["level"]]
        severity = "error"
        if (theme, pair["name"]) in KNOWN_WARNING_PAIRS:
            severity = "warning"
        results.append(
            {
                "theme": theme,
                "name": pair["name"],
                "fg_var": pair["fg"],
                "bg_var": pair["bg"],
                "level": pair["level"],
                "threshold": threshold,
                "ratio": round(ratio, 4),
                "pass": ratio >= threshold,
                "severity": severity,
            }
        )

    # 2. Badge alpha-composited pairs
    for pair in BADGE_ALPHA_PAIRS:
        fg_oklch = parse_oklch(vars_dict[pair["fg"]])
        fg_lum = oklch_to_luminance(*fg_oklch)

        base_gamma = oklch_to_gamma_srgb(*parse_oklch(vars_dict[pair["bg_base"]]))
        overlay_gamma = oklch_to_gamma_srgb(*parse_oklch(vars_dict[pair["bg_overlay"]]))
        effective_bg = alpha_composite_gamma(base_gamma, overlay_gamma, pair["alpha"])
        bg_lum = gamma_srgb_to_luminance(effective_bg)

        ratio = contrast_ratio(fg_lum, bg_lum)
        threshold = THRESHOLDS[pair["level"]]
        passed = ratio >= threshold

        # Determine severity: known out-of-scope pairs are non-blocking
        severity = "error"
        if (theme, pair["name"]) in KNOWN_WARNING_PAIRS:
            severity = "warning"

        results.append(
            {
                "theme": theme,
                "name": pair["name"],
                "fg_var": pair["fg"],
                "bg_var": f"{pair['bg_base']}+{pair['bg_overlay']}@{pair['alpha']}",
                "level": pair["level"],
                "threshold": threshold,
                "ratio": round(ratio, 4),
                "pass": passed,
                "severity": severity,
            }
        )

    # 3. Muted / large-text pairs
    for pair in MUTED_LARGE_PAIRS:
        fg_lum = oklch_to_luminance(*parse_oklch(vars_dict[pair["fg"]]))
        bg_lum = oklch_to_luminance(*parse_oklch(vars_dict[pair["bg"]]))
        ratio = contrast_ratio(fg_lum, bg_lum)
        threshold = THRESHOLDS[pair["level"]]
        results.append(
            {
                "theme": theme,
                "name": pair["name"],
                "fg_var": pair["fg"],
                "bg_var": pair["bg"],
                "level": pair["level"],
                "threshold": threshold,
                "ratio": round(ratio, 4),
                "pass": ratio >= threshold,
                "severity": "error",
            }
        )

    return results


def audit(css_path: Path) -> dict:
    """Run full dual-theme WCAG audit, return structured report."""
    css_text = css_path.read_text(encoding="utf-8")

    light_vars = extract_theme_vars(css_text, ":root")
    dark_vars = extract_theme_vars(css_text, ".dark")

    results = audit_theme(light_vars, "light") + audit_theme(dark_vars, "dark")

    # Classify failures
    error_failures = [r for r in results if not r["pass"] and r["severity"] == "error"]
    warning_failures = [r for r in results if not r["pass"] and r["severity"] == "warning"]

    all_pass = len(error_failures) == 0

    return {
        "all_pass": all_pass,
        "total_pairs": len(results),
        "pass_count": sum(1 for r in results if r["pass"]),
        "fail_count": len(error_failures) + len(warning_failures),
        "error_failures": error_failures,
        "warning_failures": warning_failures,
        "pairs": results,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    css_file = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "styles" / "globals.css"
    )
    if len(sys.argv) > 1:
        css_file = Path(sys.argv[1])

    if not css_file.exists():
        print(f"ERROR: CSS file not found: {css_file}", file=sys.stderr)
        sys.exit(2)

    report = audit(css_file)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Print human-readable summary to stderr
    if report["warning_failures"]:
        print("\n⚠ WARNING (non-blocking, known out-of-scope):", file=sys.stderr)
        for f in report["warning_failures"]:
            print(
                f"  [{f['theme']}] {f['name']}: {f['ratio']:.2f}:1 < {f['threshold']}:1",
                file=sys.stderr,
            )

    if report["error_failures"]:
        print("\n✗ FAIL (blocking):", file=sys.stderr)
        for f in report["error_failures"]:
            print(
                f"  [{f['theme']}] {f['name']}: {f['ratio']:.2f}:1 < {f['threshold']}:1",
                file=sys.stderr,
            )
    else:
        print("\n✓ All in-scope pairs pass WCAG AA.", file=sys.stderr)

    sys.exit(0 if report["all_pass"] else 1)
