"""Terminal and SVG rendering helpers (no plotting dependency)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[float], width: int = 80) -> str:
    if not values:
        return ""
    step = max(1, len(values) // width)
    sampled = list(values)[::step][:width]
    lo, hi = min(sampled), max(sampled)
    if hi <= lo:
        return _BLOCKS[0] * len(sampled)
    span = hi - lo
    top = len(_BLOCKS) - 1
    return "".join(_BLOCKS[min(top, int((v - lo) / span * top))] for v in sampled)


def line_svg(
    values: Sequence[float],
    timestamps: Sequence[datetime],
    width: int = 960,
    height: int = 360,
) -> str:
    """Minimal candlestick-free line chart, enough to eyeball data quality."""
    if not values or len(values) < 2:
        raise ValueError("need at least two points")

    left, right, top, bottom = 56, 16, 16, 40
    plot_w = width - left - right
    plot_h = height - top - bottom

    lo, hi = min(values), max(values)
    span = hi - lo or 1.0

    def x(i: int) -> float:
        return left + plot_w * i / (len(values) - 1)

    def y(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / span)

    points = " ".join(f"{x(i):.2f},{y(v):.2f}" for i, v in enumerate(values))

    grid = []
    for frac in (0, 0.25, 0.5, 0.75, 1):
        gy = top + plot_h * frac
        price = hi - span * frac
        grid.append(
            f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" '
            f'stroke="#2a2e39" stroke-width="1"/>'
            f'<text x="{left - 8}" y="{gy + 4:.1f}" fill="#8a8f9c" font-size="11" '
            f'text-anchor="end">{price:,.2f}</text>'
        )

    labels = (
        f'<text x="{left}" y="{height - 12}" fill="#8a8f9c" font-size="11">'
        f"{timestamps[0]:%Y-%m-%d %H:%M}</text>"
        f'<text x="{width - right}" y="{height - 12}" fill="#8a8f9c" font-size="11" '
        f'text-anchor="end">{timestamps[-1]:%Y-%m-%d %H:%M}</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#131722"/>'
        f"{''.join(grid)}"
        f'<polyline fill="none" stroke="#2962ff" stroke-width="1.5" points="{points}"/>'
        f"{labels}"
        f"</svg>"
    )
