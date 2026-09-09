"""High-frequency indicator analysis report.

Combines: (1) the standalone indicator screen (directionality + magnitude),
(2) vintage backtests of the three panel variants vs GDPNow / NY Fed,
(3) source-mapping notes for the user's MASTER workbook series.
Writes output/backtest/hf_indicator_report.html.
"""

from __future__ import annotations

import base64
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nowcast import config, fetch  # noqa: E402

OUT = ROOT / "output" / "backtest"
BENCH = ROOT / "data_cache" / "benchmarks"

PANEL_FILES = {
    "baseline (16 series)": OUT / "gdp_backtest.csv",
    "nyfed_full (27 series)": OUT / "gdp_backtest_nyfed_full.csv",
    "hf (42 series, incl. weekly)": OUT / "gdp_backtest_hf.csv",
}
COLORS = {"baseline (16 series)": "#1d4ed8", "nyfed_full (27 series)": "#0e7490",
          "hf (42 series, incl. weekly)": "#7c3aed", "GDPNow": "#b45309",
          "NY Fed": "#6b7280"}


def _img(fig) -> str:
    p = OUT / "_tmp2.png"
    fig.savefig(p, bbox_inches="tight", facecolor="white", dpi=140)
    plt.close(fig)
    b = base64.b64encode(p.read_bytes()).decode()
    p.unlink()
    return f"<img src='data:image/png;base64,{b}'>"


def _direction(df: pd.DataFrame, col: str) -> float:
    """Sign agreement of the y/y rate-of-change vs the advance print,
    using the same real-time vintage levels as the main backtest report."""
    ok = []
    for q, row in df.iterrows():
        try:
            v = fetch.get_series_vintage("GDPC1", row["asof"], start="2010-01-01",
                                         log=lambda m: None)
            adv_date = (pd.Timestamp(row["asof"]) + pd.Timedelta("1D")).strftime("%Y-%m-%d")
            adv = fetch.get_series_vintage("GDPC1", adv_date, start="2010-01-01",
                                           log=lambda m: None)
            v.index = pd.PeriodIndex(v.index, freq="Q")
            adv.index = pd.PeriodIndex(adv.index, freq="Q")
            prev = v.loc[q - 1] / v.loc[q - 5] - 1
            d_hat = (v.loc[q - 1] * (1 + row[col] / 100) ** 0.25) / v.loc[q - 4] - 1 - prev
            d_act = (adv.loc[q] / adv.loc[q - 4] - 1) - prev
            ok.append(np.sign(d_hat) == np.sign(d_act))
        except Exception:  # noqa: BLE001
            continue
    return 100 * np.mean(ok) if ok else np.nan


def panels_section() -> str:
    frames = {}
    for name, path in PANEL_FILES.items():
        if path.exists():
            f = pd.read_csv(path)
            f["q"] = pd.PeriodIndex(f["quarter"], freq="Q")
            frames[name] = f.set_index("q").sort_index()
    base = frames["baseline (16 series)"]

    ny = pd.read_csv(BENCH / "ny_fed_nowcast_by_quarter.csv")
    ny["q"] = pd.PeriodIndex(ny["target_quarter"], freq="Q")
    ny = ny[ny["forecast_after_quarter_end"] == 1].set_index("q")["nowcast_qq_saar"]

    rows = []
    for name, f in frames.items():
        ex = f[~f.index.astype(str).str.startswith("2020")]
        err = ex["ours_saar"] - ex["advance_saar"]
        rows.append({
            "model": f"Ours — {name}",
            "n": len(err.dropna()),
            "RMSE ex-2020": np.sqrt((err ** 2).mean()),
            "MAE ex-2020": err.abs().mean(),
            "bias": err.mean(),
            "direction %": _direction(f, "ours_saar"),
            "fallback series/qtr": f["n_fallback_series"].mean(),
        })
    ex = base[~base.index.astype(str).str.startswith("2020")]
    for name, col in (("GDPNow", "gdpnow_saar"),):
        err = ex[col] - ex["advance_saar"]
        rows.append({"model": name, "n": len(err.dropna()),
                     "RMSE ex-2020": np.sqrt((err ** 2).mean()),
                     "MAE ex-2020": err.abs().mean(), "bias": err.mean(),
                     "direction %": _direction(base, col),
                     "fallback series/qtr": np.nan})
    nyj = ny.reindex(ex.index)
    err = nyj - ex["advance_saar"]
    rows.append({"model": "NY Fed Staff Nowcast", "n": len(err.dropna()),
                 "RMSE ex-2020": np.sqrt((err ** 2).mean()),
                 "MAE ex-2020": err.abs().mean(), "bias": err.mean(),
                 "direction %": np.nan, "fallback series/qtr": np.nan})
    stats = pd.DataFrame(rows)
    stats_html = stats.to_html(index=False, border=0, na_rep="—",
                               float_format=lambda v: f"{v:.2f}")

    # per-quarter |error| comparison chart, ex-2020
    fig, ax = plt.subplots(figsize=(12, 4.4), dpi=140)
    x = np.arange(len(ex))
    for name, f in frames.items():
        e = (f["ours_saar"] - f["advance_saar"]).reindex(ex.index)
        ax.plot(x, e.abs(), marker="o", ms=3.5, lw=1.3, label=f"Ours {name.split(' ')[0]}",
                color=COLORS[name])
    ax.plot(x, (ex["gdpnow_saar"] - ex["advance_saar"]).abs(), marker="s", ms=3.5,
            lw=1.6, label="GDPNow", color=COLORS["GDPNow"])
    ax.set_xticks(x)
    ax.set_xticklabels([str(i) for i in ex.index], rotation=45, fontsize=8)
    ax.grid(color="#e5e7eb", lw=0.5)
    ax.set_axisbelow(True)
    ax.set_ylabel("|error| vs advance (pp)")
    ax.set_title("Absolute nowcast error by panel (2020 omitted)", fontsize=11)
    ax.legend(fontsize=9, ncol=4, frameon=False)
    for s in ax.spines.values():
        s.set_color("#d1d5db")
    chart = _img(fig)

    # per-quarter table of all panels
    tbl = pd.DataFrame({"advance": base["advance_saar"],
                        "GDPNow": base["gdpnow_saar"], "NY Fed": ny})
    for name, f in frames.items():
        tbl[name.split(" ")[0]] = f["ours_saar"]
    tbl_html = tbl.reset_index().rename(columns={"q": "quarter"}).to_html(
        index=False, border=0, na_rep="—", float_format=lambda v: f"{v:.2f}")

    return f"""
<h2>Panel backtests (real-time vintages, day before advance release)</h2>
{stats_html}
{chart}
<h3>Per-quarter nowcasts</h3>
<div class="scroll">{tbl_html}</div>
"""


def screen_section() -> str:
    df = pd.read_csv(OUT / "indicator_screen.csv")
    df["abs_corr_dyoy"] = df["corr_dyoy"].abs()
    df["effective_dir"] = np.where(df["corr_dyoy"] < 0, 100 - df["dir_hit"], df["dir_hit"])
    df = df.sort_values("effective_dir", ascending=False)
    cols = ["indicator", "id", "source", "n", "dir_hit", "effective_dir",
            "corr_dyoy", "corr_saar"]
    html = df[cols].to_html(index=False, border=0, na_rep="—",
                            float_format=lambda v: f"{v:.2f}")
    return f"""
<h2>Standalone indicator screen (2005–2026, 2020 excluded)</h2>
<p><b>dir_hit</b>: % of quarters the indicator's quarterly change matched the sign of the
change in GDP YoY (the quad-relevant call). <b>effective_dir</b>: same, after flipping
counter-cyclical indicators (claims, unemployment, hourly earnings — negative corr_dyoy);
the factor model exploits these automatically through negative loadings.
<b>corr_saar</b>: correlation of the indicator's quarterly signal with GDP q/q SAAR
(magnitude relevance). Workbook (BBG) rows are scored on 2005–2021 data only.</p>
<div class="scroll">{html}</div>
"""


def mapping_section() -> str:
    return """
<h2>Source mapping for the MASTER workbook series</h2>
<p>Every monthly indicator in the workbook's HEYE list maps to a live FRED series except
the licensed ones: <b>ISM Manufacturing / Services / Composite, NFIB Optimism, and
Conference Board Confidence</b> (Bloomberg-sourced, history in the workbook ends Feb-2022,
so they can be screened but not run live for free — regional Fed surveys
(Empire / Philly / Dallas) and UMich sentiment serve as free proxies in the hf panel).
Weekly additions available free with real-time vintages: initial claims (ICSA), continued
claims (CCSA), and the NY Fed Weekly Economic Index (WEI — itself a composite of Redbook
retail, staffing, steel, fuel, rail, electricity and tax-withholding weeklies, i.e. most
of the licensed weekly universe in one free series scaled to GDP YoY). No usable free
bi-monthly/semimonthly releases exist (Ward's mid-month auto sales and Redbook are
licensed); the weekly block covers that cadence.</p>
"""


def main():
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>High-frequency indicator analysis</title>
<style>
 body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1150px;
        color: #111827; }}
 h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; }}
 h3 {{ font-size: 14px; margin: 16px 0 6px; color: #374151; }}
 img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; margin: 8px 0; }}
 table {{ border-collapse: collapse; font-size: 12.5px; }}
 th, td {{ padding: 4px 9px; border-bottom: 1px solid #e5e7eb; text-align: right; }}
 th:first-child, td:first-child {{ text-align: left; }}
 td:nth-child(2), td:nth-child(3) {{ text-align: left; }}
 th {{ background: #f9fafb; color: #6b7280; }}
 .scroll {{ overflow-x: auto; }}
 p {{ font-size: 13.5px; color: #374151; }}
</style></head><body>
<h1>High-frequency indicator &amp; panel analysis</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M} · nowcast_quad · directionality = sign of the
change in real GDP YoY vs prior quarter (the quad call); magnitude = q/q SAAR error.</p>
{panels_section()}
{screen_section()}
{mapping_section()}
<h2>Recommendation</h2>
<p><b>Adopted: the hf panel</b> (42 series incl. weekly claims/WEI and the HEYE-list
monthly indicators) — best of the three variants on both magnitude (RMSE 2.35pp ex-2020
vs 2.50 baseline, 3.00 nyfed_full) and direction (76% vs 70%). It softened every 2025
miss but does not close the gap to GDPNow (1.00pp / 85%): panel breadth cannot supply
what component bookkeeping provides — the remaining error is still concentrated in
trade/inventory quarters. Two follow-ups, in order: (1) ensemble the current-quarter
growth input as 0.85·GDPNow + 0.15·ours(hf) — backtests at <b>0.92pp RMSE (better than
GDPNow alone) with ~90% direction accuracy</b>; (2) the domestic-final-sales + trade /
inventory bridge restructure in REFINEMENT_PLAN.md, which attacks the residual error
source directly.</p>
</body></html>"""
    out = OUT / "hf_indicator_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
