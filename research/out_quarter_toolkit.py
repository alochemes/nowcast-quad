"""Out-quarter direction toolkit: which free leading signals predict the sign
of Δ(YoY) for GDP and CPI at horizons 1-4 quarters, vs the comp baseline?

GDP signals (known at end of quarter t, predicting sign(yoy_{t+h}-yoy_{t+h-1})):
  comp     : -sign(Δcomp_{t+h}) — base effects, computable ahead (baseline)
  curve    : sign(10y-3m spread, deviation from trailing 10y mean)
  nfci     : -sign(Δ NFCI qtr avg) — financial conditions tightening
  hyoas    : -sign(Δ HY OAS qtr avg) — credit spreads widening
  permits  : sign(Δ permits YoY) — housing leads
CPI signals:
  comp     : -sign(Δcomp_{t+h})
  breakeven: sign(Δ 5y breakeven qtr avg)  [2003+]
  oil      : sign(Δ WTI YoY)
  core_mom : sign(Δ core CPI YoY) — core leads headline
Combined = z-scored sum of comp + the best-performing extra signal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nowcast import fetch  # noqa: E402
from research.base_effects_analysis import yoy_series  # noqa: E402


def qavg(sid, start="1970-01-01"):
    s = fetch.get_series(sid, start=start, log=lambda m: None)
    return s.groupby(pd.PeriodIndex(s.index, freq="Q")).mean()


def qyoy(sid, start="1970-01-01"):
    s = fetch.get_series(sid, start=start, log=lambda m: None)
    s = s.groupby(pd.PeriodIndex(s.index, freq="M")).mean()  # daily/weekly -> monthly
    s = s.reindex(pd.period_range(s.index[0], s.index[-1], freq="M"))
    yy = (s / s.shift(12) - 1) * 100
    return yy.groupby(yy.index.asfreq("Q")).mean()


def ex_covid(ix):
    s = ix.astype(str)
    return ~(s.str.startswith("2020") | s.str.startswith("2021"))


def hit_table(yoy: pd.Series, signals: dict[str, pd.Series], start="1985Q1") -> pd.DataFrame:
    d_yoy = yoy.diff()
    rows = []
    for h in (1, 2, 3, 4):
        row = {"h": h}
        target = d_yoy.shift(-h)  # Δyoy at t+h, aligned to signal date t
        for name, sig in signals.items():
            df = pd.DataFrame({"s": sig, "y": target}).dropna()
            df = df[(df.index >= pd.Period(start, "Q")) & ex_covid(df.index)]
            df = df[df["s"] != 0]
            row[name] = round(100 * (np.sign(df["s"]) == np.sign(df["y"])).mean(), 0)
            row["n"] = len(df)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    data = yoy_series()
    gdp_yoy, cpi_yoy = data["GDP"], data["CPI"]

    curve = qavg("T10Y3M", "1982-01-01")
    nfci = qavg("NFCI", "1973-01-01")
    hyoas = qavg("BAMLH0A0HYM2", "1997-01-01")
    permits = qyoy("PERMIT")
    breakeven = qavg("T5YIE", "2003-01-01")
    oil_yoy = qyoy("DCOILWTICO", "1986-01-01")
    core_yoy = qyoy("CPILFESL")

    # comp signal for horizon h is built inside hit_table via shift(-h) on the
    # target; the comp itself must also be the one for quarter t+h as seen at t:
    def comp_sig(yoy, h):
        comp = (yoy.shift(4 - h) + yoy.shift(8 - h)) / 2
        return -comp.diff()

    print("=== GDP: direction hit% by horizon (1985+, ex-2020/21) ===")
    for h in (1, 2, 3, 4):
        signals = {
            "comp": comp_sig(gdp_yoy, h),
            "curve": curve - curve.rolling(40).mean(),
            "nfci": -nfci.diff(),
            "hyoas": -hyoas.diff(),
            "permits": permits.diff(),
        }
        z = sum((s / s.std()).reindex(gdp_yoy.index) for s in
                [signals["comp"], signals["curve"]])
        signals["comp+curve"] = z
        t = hit_table(gdp_yoy, signals)
        print(t[t["h"] == h].to_string(index=False))

    print("\n=== CPI: direction hit% by horizon (1985+, ex-2020/21; breakeven 2003+) ===")
    for h in (1, 2, 3, 4):
        signals = {
            "comp": comp_sig(cpi_yoy, h),
            "breakeven": breakeven.diff(),
            "oil": oil_yoy.diff(),
            "core_mom": core_yoy.diff(),
        }
        z = sum((s / s.std()).reindex(cpi_yoy.index) for s in
                [signals["comp"], signals["breakeven"]])
        signals["comp+breakeven"] = z
        t = hit_table(cpi_yoy, signals)
        print(t[t["h"] == h].to_string(index=False))


if __name__ == "__main__":
    main()
