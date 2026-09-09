"""Quad assignment from quarterly year-over-year growth and inflation series.

Convention (Hedgeye GIP model):
- Growth   = real GDP YoY % by quarter.
- Inflation = headline CPI YoY %, quarterly average of monthly YoY readings.
- A series "accelerates" when this quarter's YoY rate exceeds the prior
  quarter's (delta > 0, measured in basis points).
- Quad 1: growth accel, inflation decel   (Goldilocks)
  Quad 2: growth accel, inflation accel   (Reflation)
  Quad 3: growth decel, inflation accel   (Stagflation)
  Quad 4: growth decel, inflation decel   (Deflation)
"""

from __future__ import annotations

import pandas as pd

QUAD_NAMES = {1: "Goldilocks", 2: "Reflation", 3: "Stagflation", 4: "Deflation"}
QUAD_POLICY = {1: "Neutral", 2: "Hawkish", 3: "Constrained", 4: "Dovish"}


def assign_quad(d_gdp_bps: float, d_cpi_bps: float) -> int:
    growth_accel = d_gdp_bps > 0
    inflation_accel = d_cpi_bps > 0
    if growth_accel and not inflation_accel:
        return 1
    if growth_accel and inflation_accel:
        return 2
    if not growth_accel and inflation_accel:
        return 3
    return 4


def quad_table(gdp_yoy: pd.Series, cpi_yoy: pd.Series,
               estimate_from: pd.Period | None = None) -> pd.DataFrame:
    """Build the quad table from two quarterly-PeriodIndex YoY series (%).

    estimate_from: first quarter that is a model estimate rather than actuals
    (that quarter and everything after is flagged is_estimate).
    """
    df = pd.DataFrame({"gdp_yoy": gdp_yoy, "cpi_yoy": cpi_yoy}).dropna()
    df.index.name = "quarter"
    df["d_gdp_bps"] = (df["gdp_yoy"].diff() * 100).round(1)
    df["d_cpi_bps"] = (df["cpi_yoy"].diff() * 100).round(1)
    df = df.dropna(subset=["d_gdp_bps", "d_cpi_bps"])
    df["quad"] = [assign_quad(g, c) for g, c in zip(df["d_gdp_bps"], df["d_cpi_bps"])]
    df["quad_name"] = df["quad"].map(QUAD_NAMES)
    if estimate_from is None:
        df["is_estimate"] = False
    else:
        df["is_estimate"] = df.index >= estimate_from
    return df


def quarter_label(p: pd.Period, estimate: bool = False) -> str:
    """Hedgeye-style label: 2Q26 / 2Q26E."""
    return f"{p.quarter}Q{p.year % 100:02d}" + ("E" if estimate else "")
