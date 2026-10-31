"""Data quality checks for bar series.

Run these before trusting a backtest. A single missing bar can silently shift
every indicator; duplicate bars can double count volume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import polars as pl

from quant.data.binance import INTERVAL_MS


@dataclass
class Gap:
    after: datetime
    before: datetime
    missing_bars: int


@dataclass
class QualityReport:
    rows: int = 0
    start: datetime | None = None
    end: datetime | None = None
    duplicates: int = 0
    gaps: list[Gap] = field(default_factory=list)
    ohlc_violations: int = 0
    zero_volume_bars: int = 0
    non_positive_prices: int = 0

    @property
    def missing_bars(self) -> int:
        return sum(g.missing_bars for g in self.gaps)

    @property
    def ok(self) -> bool:
        return self.duplicates == 0 and self.ohlc_violations == 0 and not self.gaps


def check_bars(df: pl.DataFrame, interval: str = "1m") -> QualityReport:
    report = QualityReport(rows=df.height)
    if df.is_empty():
        return report

    step = INTERVAL_MS[interval]
    report.start = df["open_time"].min()
    report.end = df["open_time"].max()

    report.duplicates = df.height - df["open_time"].n_unique()

    ordered = df.sort("open_time")
    gaps_df = (
        ordered.select(
            pl.col("open_time").shift(1).alias("prev"),
            pl.col("open_time").alias("cur"),
        )
        .with_columns(
            ((pl.col("cur") - pl.col("prev")).dt.total_milliseconds()).alias("delta_ms")
        )
        .filter(pl.col("delta_ms") > step)
    )
    report.gaps = [
        Gap(
            after=row["prev"],
            before=row["cur"],
            missing_bars=int(row["delta_ms"] // step) - 1,
        )
        for row in gaps_df.iter_rows(named=True)
    ]

    bad_ohlc = (
        (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.col("high") < pl.col("low"))
    )
    report.ohlc_violations = ordered.filter(bad_ohlc).height
    report.zero_volume_bars = ordered.filter(pl.col("volume") == 0).height
    report.non_positive_prices = ordered.filter(
        (pl.col("close") <= 0) | (pl.col("open") <= 0)
    ).height

    return report


def describe(report: QualityReport, max_gaps: int = 5) -> list[str]:
    lines = [
        f"rows={report.rows}  range={report.start} -> {report.end}",
        f"duplicates={report.duplicates}  ohlc_violations={report.ohlc_violations}  "
        f"zero_volume={report.zero_volume_bars}  bad_prices={report.non_positive_prices}",
        f"gaps={len(report.gaps)}  missing_bars={report.missing_bars}",
    ]
    for gap in report.gaps[:max_gaps]:
        lines.append(
            f"  gap: {gap.after} -> {gap.before}  missing {gap.missing_bars} bars"
        )
    if len(report.gaps) > max_gaps:
        lines.append(f"  ... {len(report.gaps) - max_gaps} more")
    return lines
