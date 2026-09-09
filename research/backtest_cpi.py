"""Pseudo-real-time backtest of the CPI nowcast vs the Cleveland Fed's.

Stance per target month M: the day before M's CPI release (approximated as
the 11th of M+1) — the same "final nowcast" timing the Cleveland Fed history
represents. Inputs are truncated to that date; current-vintage CPI values are
used (SA history is only lightly revised; NSA is unrevised).

Caveat on the Cleveland comparison: their published y/y numbers are NSA-based;
ours are SA-based. Each model is scored against its own actual definition.

Writes output/backtest/cpi_backtest.csv.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nowcast import config, fetch, inflation  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "backtest"
CLEVELAND_CSV = (Path(__file__).resolve().parent.parent / "data_cache" /
                 "benchmarks" / "cleveland_cpi_yoy_final_nowcast.csv")


def _quiet(_msg):
    pass


def main(start="2019-01", end="2026-05"):
    months = pd.period_range(start, end, freq="M")
    actual = fetch.get_series(config.CPI_HEADLINE, start="1995-01-01", log=_quiet)
    actual.index = pd.PeriodIndex(actual.index, freq="M")
    actual = actual.reindex(pd.period_range(actual.index[0], actual.index[-1], freq="M"))
    act_mm = 100 * actual.pct_change(fill_method=None)
    act_yoy = (actual / actual.shift(12) - 1) * 100

    cleveland = None
    if CLEVELAND_CSV.exists():
        cl = pd.read_csv(CLEVELAND_CSV)
        cl["target_month"] = pd.PeriodIndex(cl["target_month"], freq="M")
        cleveland = cl.set_index("target_month")

    rows = []
    for m in months:
        if m not in act_yoy.index or np.isnan(act_yoy.loc[m]):
            continue  # unreleased or shutdown-gap month
        asof = (m + 1).start_time + pd.Timedelta(days=10)  # the 11th of M+1
        try:
            r = inflation.nowcast_cpi_yoy(asof=asof, log=_quiet)
        except Exception as e:  # noqa: BLE001
            print(f"{m} FAILED: {e}")
            continue
        det = next((d for d in r["monthly_nowcast"] if d["month"] == str(m)), None)
        yoy_hat = r["yoy_m_nowcast"].get(str(m), np.nan)
        if det is None or np.isnan(yoy_hat):
            print(f"{m}: no nowcast produced (last released {r['last_cpi_month']})")
            continue
        row = {"month": str(m), "ours_mm": det["headline_mm_pct"],
               "actual_mm": round(float(act_mm.loc[m]), 3),
               "ours_yoy": round(yoy_hat, 3),
               "actual_yoy_sa": round(float(act_yoy.loc[m]), 3),
               "gas_source": det["source"]}
        if cleveland is not None and m in cleveland.index:
            c = cleveland.loc[m]
            row["cleveland_yoy"] = c["final_cpi_yoy_nowcast"]
            row["cleveland_actual_yoy_nsa"] = c["actual_cpi_yoy"]
        rows.append(row)
        if len(rows) % 12 == 0:
            print(f"...{m} done ({len(rows)} months)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "cpi_backtest.csv", index=False)

    e_mm = df["ours_mm"] - df["actual_mm"]
    e_yoy = df["ours_yoy"] - df["actual_yoy_sa"]
    print(f"\nn={len(df)} months {df['month'].iloc[0]}..{df['month'].iloc[-1]}")
    print(f"ours   m/m: RMSE {np.sqrt((e_mm**2).mean()):.3f}pp, MAE {e_mm.abs().mean():.3f}pp, bias {e_mm.mean():+.3f}")
    print(f"ours   y/y: RMSE {np.sqrt((e_yoy**2).mean()):.3f}pp, MAE {e_yoy.abs().mean():.3f}pp, bias {e_yoy.mean():+.3f}")
    if "cleveland_yoy" in df:
        cl_df = df.dropna(subset=["cleveland_yoy", "cleveland_actual_yoy_nsa"])
        e_cl = cl_df["cleveland_yoy"] - cl_df["cleveland_actual_yoy_nsa"]
        e_ours_overlap = cl_df["ours_yoy"] - cl_df["actual_yoy_sa"]
        print(f"overlap n={len(cl_df)}:")
        print(f"  cleveland y/y: RMSE {np.sqrt((e_cl**2).mean()):.3f}pp, MAE {e_cl.abs().mean():.3f}pp")
        print(f"  ours      y/y: RMSE {np.sqrt((e_ours_overlap**2).mean()):.3f}pp, MAE {e_ours_overlap.abs().mean():.3f}pp")
    print(f"wrote {OUT_DIR / 'cpi_backtest.csv'}")


if __name__ == "__main__":
    main()
