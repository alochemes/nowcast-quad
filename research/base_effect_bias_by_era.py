"""Does the out-quarter base-effect projection have a directional bias, and is
it regime-specific?

Motivation (2026-08-03): replaying the quad call weekly over 2023-2025 showed
the out-quarter call landing BELOW random — 11-20% joint-quad accuracy at
100+ days out, against 25% for a coin toss across four quads. The cause was
not an inverted sign but a blind spot: the model predicted Quad 4 zero times
in ten while Quad 4 was the modal outcome. Both axes leaned "accelerating"
because the comp model sets

    d_yoy(t) = -K * (comp(t) - comp(t-1)),   comp(t) = (yoy(t-4) + yoy(t-8)) / 2

and through 2023-25 both series were unwinding from 2022 peaks, so the comps
fell almost every quarter and -(negative) projected acceleration every time.

The open question is whether that is mechanical-and-permanent or specific to a
long one-directional unwind. This script answers it by era.

METHOD AND ITS LIMIT: this runs on REVISED history, not ALFRED vintages. That
is deliberate and adequate here — the question is about the projection's
behaviour given a history, and the comp inputs are 1-2 years old and largely
settled by then. It is NOT a performance backtest and must not be quoted as
one; for that see research/backtest_gdp_vintage.py, which is vintage-honest.

Usage:  .venv\\Scripts\\python.exe research/base_effect_bias_by_era.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nowcast import baseeffects, config, fetch, quads  # noqa: E402

# 2020-21 is excluded from every era: the COVID collapse and rebound put
# 30-percentage-point swings into the comps, which tells us nothing about how
# the model behaves in an ordinary cycle.
ERAS = {
    "1975-1994 (high/volatile CPI)": ("1975Q1", "1994Q4"),
    "1995-2007 (pre-GFC)":           ("1995Q1", "2007Q4"),
    "2008-2013 (GFC + after)":       ("2008Q1", "2013Q4"),
    "2014-2019 (low inflation)":     ("2014Q1", "2019Q4"),
    "2022-2023H1 (peak + rollover)": ("2022Q1", "2023Q2"),
    "2023H2-2025 (the unwind)":      ("2023Q3", "2025Q4"),
}


def quarterly_yoy() -> tuple[pd.Series, pd.Series]:
    """Real GDP YoY % and headline CPI YoY % by quarter, matching the pipeline
    (CPI quarterly = average of the monthly YoY readings)."""
    g = fetch.get_series(config.GDP_QUARTERLY_SERIES, start="1950-01-01",
                         log=lambda m: None)
    g.index = pd.PeriodIndex(g.index, freq="Q")
    gdp_yoy = ((g / g.shift(4) - 1) * 100).dropna()

    c = fetch.get_series(config.CPI_HEADLINE, start="1950-01-01",
                         log=lambda m: None)
    c.index = pd.PeriodIndex(c.index, freq="M")
    m_yoy = (c / c.shift(12) - 1) * 100
    cpi_yoy = m_yoy.groupby(m_yoy.index.asfreq("Q")).mean().dropna()
    return gdp_yoy, cpi_yoy


def projections(yoy: pd.Series, k: float, horizon: int) -> pd.DataFrame:
    """For every quarter T, the Δ the comp model would have projected for T
    when the last known quarter was T-horizon, against the Δ that happened."""
    rows = []
    for i in range(12, len(yoy) - horizon):
        last_known = yoy.index[i]
        target = last_known + horizon
        ext = baseeffects.project_out_quarters(yoy.loc[:last_known],
                                               n=horizon, k=k)
        pred_d = ext.loc[target] - ext.loc[target - 1]
        act_d = yoy.loc[target] - yoy.loc[target - 1]
        rows.append({"target": target, "pred_up": pred_d > 0,
                     "act_up": act_d > 0, "pred_d": pred_d, "act_d": act_d})
    return pd.DataFrame(rows).set_index("target")


def main() -> int:
    # Windows consoles default to cp1252 and cannot print Δ / − (same guard as
    # run_nowcast.py)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    gdp_yoy, cpi_yoy = quarterly_yoy()
    print(f"GDP YoY {gdp_yoy.index[0]}..{gdp_yoy.index[-1]}   "
          f"CPI YoY {cpi_yoy.index[0]}..{cpi_yoy.index[-1]}\n")

    # The projected Δ for quarter T is invariant to how far ahead it is
    # computed: comp(T) and comp(T-1) read yoy at T-4/T-5/T-8/T-9, all of which
    # are settled long before T. Verified below to float precision. The
    # consequence is structural and not regime-specific — an out-quarter call
    # carries NO new information as the quarter approaches. It can only improve
    # when the quarter enters the DFM / CPI nowcast horizon, which is why the
    # observed lock-in curve is flat until roughly 70 days before quarter end.
    for series, k, name in ((gdp_yoy, config.BASE_EFFECT_K, "GDP"),
                            (cpi_yoy, config.BASE_EFFECT_K_CPI, "CPI")):
        a, b = projections(series, k, 1), projections(series, k, 2)
        common = a.index.intersection(b.index)
        drift = (a.loc[common, "pred_d"] - b.loc[common, "pred_d"]).abs().max()
        print(f"horizon-invariance check ({name}): max |Δ(h=1) − Δ(h=2)| = "
              f"{drift:.1e} over {len(common)} quarters")
    print()

    for horizon in (1,):
        g = projections(gdp_yoy, config.BASE_EFFECT_K, horizon)
        c = projections(cpi_yoy, config.BASE_EFFECT_K_CPI, horizon)
        joint = g.join(c, lsuffix="_g", rsuffix="_c", how="inner")
        joint["pred_quad"] = [quads.assign_quad(1 if a else -1, 1 if b else -1)
                              for a, b in zip(joint["pred_up_g"], joint["pred_up_c"])]
        joint["act_quad"] = [quads.assign_quad(1 if a else -1, 1 if b else -1)
                             for a, b in zip(joint["act_up_g"], joint["act_up_c"])]

        print(f"{'=' * 78}\nOUT-QUARTER PROJECTION, BY ERA "
              f"(2020-21 excluded everywhere)")
        print(f"{'era':<30}{'n':>4}{'GDP up':>9}{'(act)':>7}"
              f"{'CPI up':>9}{'(act)':>7}{'quad ok':>9}{'Q4 pred':>9}{'(act)':>7}")
        for name, (a, b) in ERAS.items():
            lo, hi = pd.Period(a, "Q"), pd.Period(b, "Q")
            j = joint.loc[(joint.index >= lo) & (joint.index <= hi)]
            j = j.loc[(j.index < pd.Period("2020Q1", "Q"))
                      | (j.index > pd.Period("2021Q4", "Q"))]
            if j.empty:
                continue
            ok = (j["pred_quad"] == j["act_quad"]).mean() * 100
            print(f"{name:<30}{len(j):>4}"
                  f"{j['pred_up_g'].mean() * 100:>8.0f}%{j['act_up_g'].mean() * 100:>6.0f}%"
                  f"{j['pred_up_c'].mean() * 100:>8.0f}%{j['act_up_c'].mean() * 100:>6.0f}%"
                  f"{ok:>8.0f}%"
                  f"{(j['pred_quad'] == 4).mean() * 100:>8.0f}%"
                  f"{(j['act_quad'] == 4).mean() * 100:>6.0f}%")
        print()

    print("Columns: 'GDP up' / 'CPI up' = share of quarters the model projected "
          "that axis\nACCELERATING, with the realized share beside it. A large "
          "gap is the directional bias.\n'quad ok' = both axes right (25% = "
          "chance). 'Q4 pred' vs '(act)' shows whether\nQuad 4 is reachable "
          "at all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
