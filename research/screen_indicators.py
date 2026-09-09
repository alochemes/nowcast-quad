"""Standalone indicator screen: directionality and magnitude vs real GDP.

For every candidate indicator (live FRED series + the licensed Bloomberg
series in the user's MASTER workbook: ISM x3, NFIB, Conference Board), compute
quarterly aggregates and score, concurrent quarter:
  dir_hit   : % of quarters where sign(Δ indicator) == sign(Δ GDP YoY)
              (Δ = change vs prior quarter; the quad-relevant metric)
  corr_dyoy : corr(Δ indicator, Δ GDP YoY)
  corr_saar : corr(indicator quarterly value, GDP q/q SAAR)
YoY-transformed indicators use their quarterly-average YoY; surveys use levels.
2020 excluded (COVID quarters distort everything).

Writes output/backtest/indicator_screen.csv.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nowcast import fetch  # noqa: E402

OUT = ROOT / "output" / "backtest"
HEYE_CSV = ROOT / "data_cache" / "benchmarks" / "heye_master_monthly.csv"

# FRED candidates: sid -> (how quarterly signal is built, label)
# 'yoy'  : quarterly mean of monthly YoY % change
# 'level': quarterly mean of levels (surveys, rates, WEI)
FRED_CANDIDATES = {
    "PCEC96": ("yoy", "Real PCE (M)"),
    "RSAFS": ("yoy", "Retail sales (M)"),
    "RSCCAS": ("yoy", "Retail control group (M)"),
    "TOTALSA": ("yoy", "Auto sales (M)"),
    "PSAVERT": ("level", "Savings rate (M)"),
    "PAYEMS": ("yoy", "Payrolls (M)"),
    "CES0500000003": ("yoy", "Avg hourly earnings (M)"),
    "AWHAETP": ("level", "Avg weekly hours (M)"),
    "ICSA": ("yoy", "Initial claims (W)"),
    "CCSA": ("yoy", "Continued claims (W)"),
    "WEI": ("level", "NY Fed WEI (W)"),
    "UMCSENT": ("level", "UMich sentiment (M)"),
    "INDPRO": ("yoy", "Industrial production (M)"),
    "DGORDER": ("yoy", "Durable goods orders (M)"),
    "NEWORDER": ("yoy", "Core capex orders (M)"),
    "AMTMNO": ("yoy", "Factory orders (M)"),
    "PNRESCONS": ("yoy", "Nonres construction (M)"),
    "PRRESCONS": ("yoy", "Res construction (M)"),
    "TTLCONS": ("yoy", "Construction spending (M)"),
    "HOUST": ("yoy", "Housing starts (M)"),
    "PERMIT": ("yoy", "Building permits (M)"),
    "HSN1F": ("yoy", "New home sales (M)"),
    "BOPTEXP": ("yoy", "Exports (M)"),
    "BOPTIMP": ("yoy", "Imports (M)"),
    "BOPGSTB": ("level", "Goods trade balance (M)"),
    "WHLSLRIMSA": ("yoy", "Wholesale inventories (M)"),
    "BUSINV": ("yoy", "Business inventories (M)"),
    "RETAILIMSA": ("yoy", "Retail inventories (M)"),
    "JTSJOL": ("yoy", "Job openings (M)"),
    "UNRATE": ("level", "Unemployment rate (M)"),
    "TCU": ("level", "Capacity utilization (M)"),
    "DSPIC96": ("yoy", "Real disposable income (M)"),
    "GACDISA066MSFRBNY": ("level", "Empire State survey (M)"),
    "GACDFSA066MSFRBPHI": ("level", "Philly Fed survey (M)"),
    "BACTSAMFRBDAL": ("level", "Dallas Fed survey (M)"),
    "CPIAUCSL": ("yoy", "CPI (M)"),
    "PPIFIS": ("yoy", "PPI final demand (M)"),
    "IR": ("yoy", "Import prices (M)"),
    "IQ": ("yoy", "Export prices (M)"),
}

# workbook (Bloomberg-licensed) candidates: column -> (mode, label); data to 2022-02
HEYE_CANDIDATES = {
    "NAPMPMI Index": ("level", "ISM Manufacturing PMI [BBG, to 2022]"),
    "NAPMNMI Index": ("level", "ISM Services PMI [BBG, to 2022]"),
    "NAPMALL Index": ("level", "ISM Composite [BBG, to 2022]"),
    "SBOITOTL Index": ("level", "NFIB Small Business Optimism [BBG, to 2022]"),
    "CONCCONF Index": ("level", "Conference Board Confidence [BBG, to 2022]"),
}

START, END = "2005Q1", "2026Q1"


def quarterly_signal(s: pd.Series, mode: str) -> pd.Series:
    s = s.dropna()
    m = s.groupby(pd.PeriodIndex(s.index, freq="M")).mean()
    m = m.reindex(pd.period_range(m.index[0], m.index[-1], freq="M"))
    if mode == "yoy":
        m = (m / m.shift(12) - 1) * 100
    q = m.groupby(m.index.asfreq("Q")).mean()
    return q.dropna()


def score(sig: pd.Series, gdp_yoy: pd.Series, gdp_saar: pd.Series) -> dict:
    df = pd.DataFrame({"x": sig, "gy": gdp_yoy, "gs": gdp_saar}).dropna()
    df = df.loc[(df.index >= pd.Period(START, "Q")) & (df.index <= pd.Period(END, "Q"))]
    df = df[~df.index.astype(str).str.startswith("2020")]
    dx, dg = df["x"].diff().dropna(), df["gy"].diff().dropna()
    common = dx.index.intersection(dg.index)
    dx, dg = dx.loc[common], dg.loc[common]
    if len(common) < 12:
        return {"n": len(common), "dir_hit": np.nan, "corr_dyoy": np.nan,
                "corr_saar": np.nan}
    return {
        "n": len(common),
        "dir_hit": float(100 * (np.sign(dx) == np.sign(dg)).mean()),
        "corr_dyoy": float(np.corrcoef(dx, dg)[0, 1]),
        "corr_saar": float(np.corrcoef(df["x"].loc[common], df["gs"].loc[common])[0, 1]),
    }


def main():
    gdp = fetch.get_series("GDPC1", start="2000-01-01", log=lambda m: None)
    gdp.index = pd.PeriodIndex(gdp.index, freq="Q")
    gdp_yoy = (gdp / gdp.shift(4) - 1) * 100
    gdp_saar = ((gdp / gdp.shift(1)) ** 4 - 1) * 100

    rows = []
    for sid, (mode, label) in FRED_CANDIDATES.items():
        try:
            s = fetch.get_series(sid, start="2003-01-01", log=lambda m: None)
            sig = quarterly_signal(s, mode)
            rows.append({"indicator": label, "id": sid, "source": "FRED (live)",
                         "mode": mode, **score(sig, gdp_yoy, gdp_saar)})
        except Exception as e:  # noqa: BLE001
            rows.append({"indicator": label, "id": sid, "source": "FRED (live)",
                         "mode": mode, "n": 0, "dir_hit": np.nan,
                         "corr_dyoy": np.nan, "corr_saar": np.nan})
            print(f"{sid} failed: {e}")

    heye = pd.read_csv(HEYE_CSV, parse_dates=["Date"]).replace("NAN", np.nan)
    heye = heye.set_index("Date")
    for col, (mode, label) in HEYE_CANDIDATES.items():
        s = pd.to_numeric(heye[col], errors="coerce").dropna()
        sig = quarterly_signal(s, mode)
        rows.append({"indicator": label, "id": col, "source": "workbook (BBG)",
                     "mode": mode, **score(sig, gdp_yoy, gdp_saar)})

    df = pd.DataFrame(rows).sort_values("dir_hit", ascending=False)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "indicator_screen.csv", index=False)
    print(df.to_string(index=False,
                       float_format=lambda v: f"{v:.2f}"))
    print(f"\nwrote {OUT / 'indicator_screen.csv'}")


if __name__ == "__main__":
    main()
