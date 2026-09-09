"""Replay the whole quad call at past dates, to backfill the chart-book history.

For each as-of date the model is rebuilt exactly as it would have stood that
morning: ALFRED vintages for the 42-series GDP panel and for real GDP, the
GDPNow estimate that was actually on the screen that day, CPI truncated to the
months released by then, then the same ensemble, base-effect extension and quad
assignment the live pipeline uses. The resulting table is appended to
output/history/quad_history.csv with source="replay", where the report's chart
book reads it alongside the live runs.

The current quarter is the CALENDAR quarter at the as-of date — the same rule
the live pipeline now follows.

Usage:
  .venv\\Scripts\\python.exe research/replay_vintage_quads.py --start 2023-08-01
  .venv\\Scripts\\python.exe research/replay_vintage_quads.py --start 2026-01-01 --freq W-MON

Resumable and idempotent: as-of dates already in the history file are skipped
(--redo to overwrite), and every date is saved as it completes, so the job can
be stopped and restarted freely. Expect roughly 30-60s per date on a cold
vintage cache — mostly ALFRED fetches the first time, the DFM fit thereafter.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nowcast import (baseeffects, config, gdp, history, inflation,  # noqa: E402
                     pipeline, quads, vintage)

OUT_DIR = Path(__file__).resolve().parent.parent / "output"


def _quiet(_msg):
    pass


def replay_one(asof: pd.Timestamp, log=print) -> pd.DataFrame:
    """The quad table exactly as the model would have produced it on `asof`."""
    stamp = asof.strftime("%Y-%m-%d")

    # --- GDP leg, entirely from vintages
    gdp_level_raw = vintage.get_series_vintage_gdp(stamp, log=_quiet)
    if gdp_level_raw is None:
        raise RuntimeError("no GDPC1 vintage")
    sids = gdp.panel_series(config.ACTIVE_PANEL)
    raw, fallbacks = vintage.raw_panel(stamp, sids, log=_quiet)
    panel, growth, level = gdp.build_panel(log=_quiet, raw=raw,
                                           gdp_level_raw=gdp_level_raw,
                                           panel=config.ACTIVE_PANEL)
    g = gdp.derive_nowcast(panel, growth, level, log=_quiet)

    # --- the GDPNow print that was on the screen that day, same blend rule
    gn = vintage.gdpnow_asof(stamp, log=_quiet)
    ensemble_note, _info = pipeline._apply_ensemble(g, gn, log=_quiet)

    # --- CPI leg, truncated to what had been released
    c = inflation.nowcast_cpi_yoy(asof=asof, log=_quiet)

    gdp_yoy, cpi_yoy = g["yoy"], c["yoy_q"]
    common_last = min(gdp_yoy.index[-1], cpi_yoy.index[-1])
    gdp_yoy, cpi_yoy = gdp_yoy.loc[:common_last], cpi_yoy.loc[:common_last]

    first_estimate = min(g["first_estimate"], c["first_estimate"])
    current_q = max(pd.Period(asof, freq="Q"), first_estimate)

    def _n_out(series):
        need = (current_q + config.N_OUT_QUARTERS) - series.index[-1]
        return max(config.N_OUT_QUARTERS, need.n if hasattr(need, "n") else int(need))

    gdp_ext = baseeffects.project_out_quarters(gdp_yoy, n=_n_out(gdp_yoy),
                                               k=config.BASE_EFFECT_K)
    cpi_ext = baseeffects.project_out_quarters(cpi_yoy, n=_n_out(cpi_yoy),
                                               k=config.BASE_EFFECT_K_CPI)

    table = quads.quad_table(gdp_ext, cpi_ext, estimate_from=first_estimate)
    table = table.loc[(table.index >= current_q - config.N_TRAILING_QUARTERS)
                      & (table.index <= current_q + config.N_OUT_QUARTERS)]
    if current_q in table.index:
        r = table.loc[current_q]
        log(f"  {current_q}: Quad {int(r['quad'])} ({r['quad_name']}) — "
            f"GDP {r['gdp_yoy']:.2f}%, CPI {r['cpi_yoy']:.2f}% "
            f"[{fallbacks} lag-fallback series] {ensemble_note}")
    return table


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None,
                    help="first as-of date (default: 3 years back)")
    ap.add_argument("--end", default=None, help="last as-of date (default: today)")
    ap.add_argument("--freq", default="W-MON",
                    help="pandas frequency for the as-of grid (default weekly Monday)")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N new dates (0 = no limit)")
    ap.add_argument("--redo", action="store_true",
                    help="recompute dates already present instead of skipping")
    ap.add_argument("--output-dir", default=None)
    args = ap.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else OUT_DIR
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.today().normalize()
    start = (pd.Timestamp(args.start) if args.start
             else (end - pd.DateOffset(years=3)).normalize())
    dates = pd.date_range(start, end, freq=args.freq)

    done = set()
    if not args.redo:
        h = history.load(out_dir)
        if not h.empty:
            done = set(pd.to_datetime(h["asof"]).dt.normalize())

    todo = [d for d in dates if d.normalize() not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(dates)} as-of dates in range, {len(dates) - len(todo)} already "
          f"on file, {len(todo)} to compute")

    log_path = out_dir / "replay.log"
    out_dir.mkdir(exist_ok=True)
    ok = failed = 0
    with open(log_path, "a", encoding="utf-8") as f:
        def log(msg):
            line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
            print(line)
            f.write(line + "\n")
            f.flush()

        log(f"=== replay start: {len(todo)} dates, freq {args.freq} ===")
        for i, d in enumerate(todo, 1):
            log(f"[{i}/{len(todo)}] {d.date()}")
            try:
                table = replay_one(d, log=log)
            except Exception as e:  # noqa: BLE001 - one bad date must not stop the sweep
                failed += 1
                log(f"  FAILED: {e}")
                log(traceback.format_exc(limit=3))
                continue
            history.append_run(table, d, out_dir, source="replay", log=log)
            ok += 1
        log(f"=== replay done: {ok} ok, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
