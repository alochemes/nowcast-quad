"""Real-time vintage backtest of the GDP DFM nowcast vs Atlanta Fed GDPNow.

Protocol: for each target quarter q, stand on the day before q's advance GDP
release (the same stance as GDPNow's final estimate), rebuild the entire panel
from ALFRED vintages as of that day, fit the DFM, and nowcast q/q SAAR for q.
Score against the advance release (the fair target — it is what both models
try to predict) and record GDPNow's final estimate and today's revised actual.

Usage:
  python research/backtest_gdp_vintage.py [--start 2018Q1] [--end 2026Q1] [--quarters 2024Q1,2024Q4]
Results append to output/backtest/gdp_backtest.csv (idempotent per quarter).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nowcast import config, fetch, gdp, vintage  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "backtest"
CSV_PATH = OUT_DIR / "gdp_backtest.csv"

# moved to nowcast/vintage.py so the quad replay shares one definition;
# re-exported here because this script's callers still reference them
FALLBACK_LAG = vintage.FALLBACK_LAG
vintage_raw_panel = vintage.raw_panel


def _quiet(_msg):
    pass


def find_advance_release(q: pd.Period, log=print) -> tuple[pd.Timestamp, pd.Series] | None:
    """First GDPC1 vintage after quarter end that actually CONTAINS q (a later
    vintage may still be a delayed release of an older quarter, e.g. the
    2025 government shutdown)."""
    vintages = fetch.get_vintage_dates("GDPC1")
    q_end = q.end_time.normalize()
    after = sorted(v for v in vintages if q_end < v <= q_end + pd.Timedelta(days=240))
    for v in after:
        adv = fetch.get_series_vintage("GDPC1", v.strftime("%Y-%m-%d"),
                                       start="2010-01-01", log=log)
        if adv is None:
            continue
        adv = adv.copy()
        adv.index = pd.PeriodIndex(adv.index, freq="Q")
        if q in adv.index:
            return v, adv
    return None


def backtest_quarter(q: pd.Period, panel: str = "baseline", log=print) -> dict:
    found = find_advance_release(q, log=log)
    if found is None:
        raise RuntimeError(f"no advance release found for {q}")
    advance_date, adv = found
    asof = (advance_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    log(f"--- {q} (asof {asof}, advance {advance_date.date()})")

    gdp_v = fetch.get_series_vintage("GDPC1", asof, start=config.SAMPLE_START, log=log)
    if gdp_v is None:
        raise RuntimeError("no GDPC1 vintage")
    last_q_in_vintage = pd.Period(gdp_v.index[-1], freq="Q")
    if last_q_in_vintage >= q:
        raise RuntimeError(f"vintage already contains {q} — timing off")

    sids = gdp.panel_series(panel)
    raw, fallbacks = vintage_raw_panel(asof, sids, log=log)
    pnl, growth, level = gdp.build_panel(log=log, raw=raw, gdp_level_raw=gdp_v,
                                         panel=panel)
    r = gdp.derive_nowcast(pnl, growth, level, target_q=q, log=_quiet)
    ours = r["qq_saar"][q]

    advance_saar = float(((adv.loc[q] / adv.loc[q - 1]) ** 4 - 1) * 100)

    # latest revised actual
    cur = fetch.get_series("GDPC1", start="2010-01-01", log=_quiet)
    cur.index = pd.PeriodIndex(cur.index, freq="Q")
    revised_saar = (float(((cur.loc[q] / cur.loc[q - 1]) ** 4 - 1) * 100)
                    if q in cur.index else np.nan)

    return {"quarter": str(q), "asof": asof, "ours_saar": round(ours, 2),
            "advance_saar": round(advance_saar, 2),
            "revised_saar": round(revised_saar, 2) if not np.isnan(revised_saar) else np.nan,
            "n_fallback_series": fallbacks,
            "n_panel_months": int(pnl.shape[0]),
            "n_series": int(pnl.shape[1]),
            "spec": r.get("spec", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018Q1")
    ap.add_argument("--end", default="2026Q1")
    ap.add_argument("--panel", default="baseline", choices=list(config.PANELS))
    ap.add_argument("--quarters", default=None,
                    help="comma-separated explicit list, overrides start/end")
    args = ap.parse_args()

    if args.quarters:
        quarters = [pd.Period(s.strip(), freq="Q") for s in args.quarters.split(",")]
    else:
        quarters = list(pd.period_range(args.start, args.end, freq="Q"))

    csv_path = (CSV_PATH if args.panel == "baseline"
                else OUT_DIR / f"gdp_backtest_{args.panel}.csv")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if csv_path.exists():
        done = set(pd.read_csv(csv_path)["quarter"])

    gdpnow = fetch.get_series(config.BENCHMARK_GDPNOW, start="2011-01-01")
    gdpnow.index = pd.PeriodIndex(gdpnow.index, freq="Q")

    rows = []
    for q in quarters:
        if str(q) in done:
            print(f"{q}: already done, skipping")
            continue
        try:
            row = backtest_quarter(q, panel=args.panel, log=print)
        except Exception as e:  # noqa: BLE001 - one bad quarter must not kill the run
            print(f"{q} FAILED: {e}")
            traceback.print_exc()
            continue
        row["gdpnow_saar"] = float(gdpnow.loc[q]) if q in gdpnow.index else np.nan
        rows.append(row)
        # incremental save so partial runs survive
        df = pd.DataFrame(rows)
        if csv_path.exists():
            old = pd.read_csv(csv_path)
            df = pd.concat([old, df[~df["quarter"].isin(old["quarter"])]],
                           ignore_index=True)
        df.sort_values("quarter").to_csv(csv_path, index=False)
        print(f"{q}: ours {row['ours_saar']:+.2f} | GDPNow "
              f"{row['gdpnow_saar']:+.2f} | advance {row['advance_saar']:+.2f}")

    print(f"\nwrote {csv_path}")


if __name__ == "__main__":
    main()
