"""End-to-end pipeline: fetch -> nowcast GDP & CPI -> quads -> PNG/HTML/CSV."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import baseeffects, config, fetch, gdp, history, inflation, quads, report

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


def _fetch_gdpnow(log=print) -> tuple[pd.Period, float] | None:
    """Latest GDPNow estimate and the quarter it targets."""
    try:
        s = fetch.get_series(config.BENCHMARK_GDPNOW, start="2024-01-01", log=log)
        return pd.Period(s.index[-1], freq="Q"), float(s.iloc[-1])
    except Exception as e:  # noqa: BLE001 - the ensemble degrades to pure DFM
        log(f"GDPNow unavailable: {e}")
        return None


def _apply_ensemble(g: dict, gdpnow: tuple[pd.Period, float] | None,
                    log=print) -> tuple[str, dict | None]:
    """Blend the current-quarter q/q SAAR with GDPNow (approved 2026-07-14),
    then rebuild implied levels and YoY. Later nowcast quarters keep the DFM's
    own q/q path, rebased on the blended level.

    Returns (human note, structured components or None if no blend)."""
    if not (config.ENSEMBLE_ENABLED and gdpnow and g["qq_saar"]):
        return "pure DFM (ensemble off or GDPNow unavailable)", None
    q0 = min(g["qq_saar"])
    gn_q, gn_val = gdpnow
    if gn_q != q0:
        log(f"GDPNow targets {gn_q}, our first nowcast is {q0} — no blend")
        return f"pure DFM (GDPNow targets {gn_q}, not {q0})", None
    w = config.ENSEMBLE_W_OURS
    dfm_saar = g["qq_saar"][q0]
    blend = w * dfm_saar + (1 - w) * gn_val
    levels = g["levels"]
    levels.loc[q0] = levels.loc[q0 - 1] * (1 + blend / 100) ** 0.25
    for q in sorted(k for k in g["qq_saar"] if k > q0):
        levels.loc[q] = levels.loc[q - 1] * (1 + g["qq_saar"][q] / 100) ** 0.25
    g["qq_saar"][q0] = blend
    yoy = (levels / levels.shift(4) - 1) * 100
    yoy.name = "gdp_yoy"
    g["yoy"], g["levels"] = yoy.dropna(), levels
    note = (f"{q0}: {w:.2f}·DFM({dfm_saar:+.2f}) + {1 - w:.2f}·GDPNow({gn_val:+.2f}) "
            f"= {blend:+.2f}% SAAR")
    log(f"ensemble: {note}")
    info = {"quarter": str(q0), "w_ours": w, "dfm_saar": round(dfm_saar, 2),
            "gdpnow_saar": round(gn_val, 2), "blend_saar": round(blend, 2)}
    return note, info


def run(output_dir: Path | None = None, log=print) -> dict:
    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)

    log("=== GDP nowcast (DynamicFactorMQ) ===")
    g = gdp.nowcast_gdp_yoy(log=log)
    gdpnow = _fetch_gdpnow(log=log)
    dfm_saar_note = {str(k): f"{v:.2f}%" for k, v in g["qq_saar"].items()}
    ensemble_note, ensemble_info = _apply_ensemble(g, gdpnow, log=log)
    log("=== CPI nowcast (Cleveland Fed style) ===")
    c = inflation.nowcast_cpi_yoy(log=log)

    gdp_yoy, cpi_yoy = g["yoy"], c["yoy_q"]

    # bring both to a common last quarter before base-effect extension
    common_last = min(gdp_yoy.index[-1], cpi_yoy.index[-1])
    gdp_yoy, cpi_yoy = gdp_yoy.loc[:common_last], cpi_yoy.loc[:common_last]

    # The headline quarter is the one the CALENDAR says we are in, not the
    # first quarter BEA has yet to publish. Those differ for the ~30 days
    # between a quarter ending and its advance GDP release, and during that
    # window the old behaviour headlined a quarter that was already over —
    # while the market had long since moved on to the live one.
    first_estimate = min(g["first_estimate"], c["first_estimate"])
    calendar_q = pd.Period(datetime.now(), freq="Q")
    current_q = max(calendar_q, first_estimate)

    # extend far enough that the calendar quarter still gets its full set of
    # out-quarters (in early July the DFM reaches 4Q26 on its own, but the
    # comp model must still carry the path out to current_q + N_OUT_QUARTERS)
    def _n_out(series: pd.Series) -> int:
        # Period - Period yields a DateOffset, not an int
        need = (current_q + config.N_OUT_QUARTERS) - series.index[-1]
        return max(config.N_OUT_QUARTERS, need.n if hasattr(need, "n") else int(need))

    log(f"=== base-effect extension: out to {current_q + config.N_OUT_QUARTERS} ===")
    gdp_ext = baseeffects.project_out_quarters(gdp_yoy, n=_n_out(gdp_yoy),
                                               k=config.BASE_EFFECT_K)
    cpi_ext = baseeffects.project_out_quarters(cpi_yoy, n=_n_out(cpi_yoy),
                                               k=config.BASE_EFFECT_K_CPI)

    table = quads.quad_table(gdp_ext, cpi_ext, estimate_from=first_estimate)
    window_start = current_q - config.N_TRAILING_QUARTERS
    table = table.loc[(table.index >= window_start)
                      & (table.index <= current_q + config.N_OUT_QUARTERS)]

    if current_q not in table.index:  # defensive: never point at a missing row
        log(f"WARNING calendar quarter {current_q} not in the table; "
            f"falling back to {first_estimate}")
        current_q = first_estimate

    current = table.loc[table.index == current_q]
    if not current.empty:
        row = current.iloc[0]
        log(f"CURRENT NOWCAST {quads.quarter_label(current_q, bool(row['is_estimate']))}: "
            f"Quad {int(row['quad'])} ({row['quad_name']}) — "
            f"GDP {row['gdp_yoy']:.2f}% ({row['d_gdp_bps']:+.0f}bps), "
            f"CPI {row['cpi_yoy']:.2f}% ({row['d_cpi_bps']:+.0f}bps)")
        if current_q != first_estimate:
            prior = table.loc[first_estimate:current_q - 1]
            prior = prior[prior["is_estimate"]]
            for p, r in prior.iterrows():
                log(f"  (also still an estimate: {quads.quarter_label(p, True)} "
                    f"Quad {int(r['quad'])} — GDP not yet released)")

    # quarterly display data: levels, YoY, QoQ SAAR for both series, with
    # out-quarter levels implied from the base-effect YoY path
    gdp_lvl = g["levels"].copy()
    cpi_idx = c["index_q"].copy()
    for t in table.index:
        if t not in gdp_lvl.index and t - 4 in gdp_lvl.index:
            gdp_lvl.loc[t] = gdp_lvl.loc[t - 4] * (1 + gdp_ext.loc[t] / 100)
        if t not in cpi_idx.index and t - 4 in cpi_idx.index:
            cpi_idx.loc[t] = cpi_idx.loc[t - 4] * (1 + cpi_ext.loc[t] / 100)
    gdp_lvl, cpi_idx = gdp_lvl.sort_index(), cpi_idx.sort_index()
    display = pd.DataFrame(index=table.index)
    display["gdp_level"] = gdp_lvl
    display["cpi_index"] = cpi_idx
    display["gdp_yoy"] = table["gdp_yoy"]
    display["cpi_yoy"] = table["cpi_yoy"]
    display["gdp_qq_saar"] = ((gdp_lvl / gdp_lvl.shift(1)) ** 4 - 1) * 100
    display["cpi_qq_saar"] = ((cpi_idx / cpi_idx.shift(1)) ** 4 - 1) * 100
    display["is_estimate"] = table["is_estimate"]

    final_saar = {str(k): f"{v:.2f}%" for k, v in g["qq_saar"].items()}
    blended_q = (ensemble_info or {}).get("quarter")
    current_basis = ("blended with GDPNow" if blended_q == str(current_q)
                     else f"pure DFM (GDPNow still targets {blended_q})"
                     if blended_q else "pure DFM (no GDPNow blend this run)")
    meta = {
        "generated": f"{datetime.now():%Y-%m-%d %H:%M}",
        "current quarter (calendar)": f"{current_q} — {current_basis}",
        "first quarter without released GDP": str(first_estimate),
        "GDP: last released quarter": g["last_actual_quarter"],
        "GDP panel / spec": f"{config.ACTIVE_PANEL} / {g.get('spec', '')}",
        "GDP ensemble (approved 2026-07-14)": ensemble_note,
        "GDP q/q SAAR — pure DFM": json.dumps(dfm_saar_note),
        "GDP q/q SAAR — final (post-ensemble)": json.dumps(final_saar),
        "GDPNow reference": ("n/a" if gdpnow is None
                             else f"{gdpnow[1]:.2f}% SAAR for {gdpnow[0]}"),
        "CPI: last released month": c["last_cpi_month"],
        "out-quarter method": f"comparative base effects (2Y comps), K={config.BASE_EFFECT_K}",
    }
    sections = [
        ("CPI monthly nowcast detail", c["monthly_nowcast"]),
        ("CPI model parameters", c["params"]),
        ("Data vintage — GDP panel (last transformed observation)", g["data_status"]),
        ("Data vintage — CPI inputs", c["data_status"]),
    ]

    png = report.render_quad_png(
        table, output_dir / "quad_map.png",
        title="United States — Growth & Inflation Quad Map",
        subtitle=f"Real GDP YoY vs Headline CPI YoY, rate of change · "
                 f"generated {datetime.now():%Y-%m-%d}",
        current=current_q)
    hist = history.append_run(table, datetime.now(), output_dir, source="live",
                              log=log)
    hist_df = history.load(output_dir) if hist else None
    html = report.render_html(table, png, meta, output_dir / "report.html",
                              display=display, sections=sections,
                              current=current_q, history=hist_df)
    def safe_csv(frame, path):
        # a reviewer may have the file open in Excel — don't fail the run
        try:
            frame.to_csv(path)
            return path
        except PermissionError:
            alt = path.with_name(f"{path.stem}_{datetime.now():%H%M%S}{path.suffix}")
            frame.to_csv(alt)
            log(f"WARNING {path.name} is locked (open in another app?); wrote {alt.name}")
            return alt

    csv_path = safe_csv(table, output_dir / "nowcast.csv")
    safe_csv(display, output_dir / "levels.csv")

    log(f"wrote {png}")
    log(f"wrote {html}")
    log(f"wrote {csv_path}")
    return {"table": table, "display": display, "meta": meta, "png": str(png),
            "html": str(html), "gdpnow": gdpnow, "qq_saar": g["qq_saar"],
            "current_q": current_q, "first_estimate": first_estimate,
            "history": hist_df,
            "ensemble": ensemble_info}
