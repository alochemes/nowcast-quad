"""Build the backtest comparison report: stats, charts, HTML.

Reads output/backtest/gdp_backtest.csv + cpi_backtest.csv and the benchmark
histories in data_cache/benchmarks/ (NY Fed, STLENI). Produces
output/backtest/backtest_report.html with embedded charts and an error
attribution against GDP-component contributions.
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
from nowcast import fetch  # noqa: E402

OUT = ROOT / "output" / "backtest"
BENCH = ROOT / "data_cache" / "benchmarks"

C_OURS = "#1d4ed8"     # blue
C_GDPNOW = "#b45309"   # orange-brown
C_NYFED = "#7c3aed"    # violet
C_ACTUAL = "#111827"   # near-black
C_CLEV = "#0e7490"     # teal


def _stats(err: pd.Series) -> dict:
    err = err.dropna()
    return {"n": len(err), "RMSE": float(np.sqrt((err ** 2).mean())),
            "MAE": float(err.abs().mean()), "bias": float(err.mean())}


def _fmt_stats(name, s):
    return (f"<tr><td>{name}</td><td>{s['n']}</td><td>{s['RMSE']:.2f}</td>"
            f"<td>{s['MAE']:.2f}</td><td>{s['bias']:+.2f}</td></tr>")


def _img(fig) -> str:
    p = OUT / "_tmp.png"
    fig.savefig(p, bbox_inches="tight", facecolor="white", dpi=140)
    plt.close(fig)
    b = base64.b64encode(p.read_bytes()).decode()
    p.unlink()
    return f"<img src='data:image/png;base64,{b}'>"


def gdp_section() -> tuple[str, pd.DataFrame]:
    df = pd.read_csv(OUT / "gdp_backtest.csv")
    df["q"] = pd.PeriodIndex(df["quarter"], freq="Q")
    df = df.sort_values("q").set_index("q")

    ny = pd.read_csv(BENCH / "ny_fed_nowcast_by_quarter.csv")
    ny["q"] = pd.PeriodIndex(ny["target_quarter"], freq="Q")
    ny = ny[ny["forecast_after_quarter_end"] == 1].set_index("q")
    df["nyfed_saar"] = ny["nowcast_qq_saar"]

    stleni = pd.read_csv(BENCH / "stleni.csv", parse_dates=["date"])
    stleni["q"] = pd.PeriodIndex(stleni["date"], freq="Q")
    df["stleni_saar"] = stleni.set_index("q")["value"]

    ex20 = df[~df.index.astype(str).str.startswith("2020")]
    e = {
        "Ours (DFM, vintage real-time)": df["ours_saar"] - df["advance_saar"],
        "Atlanta Fed GDPNow (final)": df["gdpnow_saar"] - df["advance_saar"],
        "NY Fed Staff Nowcast (final)": df["nyfed_saar"] - df["advance_saar"],
        "St. Louis Fed ENI": df["stleni_saar"] - df["advance_saar"],
    }
    stats_all = "".join(_fmt_stats(k, _stats(v)) for k, v in e.items())
    e20 = {k: v[~v.index.astype(str).str.startswith("2020")] for k, v in e.items()}
    stats_ex = "".join(_fmt_stats(k, _stats(v)) for k, v in e20.items())

    # chart 1: nowcasts vs advance actual through time (ex-2020 scale)
    fig, ax = plt.subplots(figsize=(12, 4.6), dpi=140)
    x = np.arange(len(ex20))
    ax.plot(x, ex20["advance_saar"], color=C_ACTUAL, lw=2.2, marker="o", ms=4,
            label="Advance actual")
    ax.plot(x, ex20["ours_saar"], color=C_OURS, lw=1.6, marker="o", ms=4,
            label="Ours (DFM)")
    ax.plot(x, ex20["gdpnow_saar"], color=C_GDPNOW, lw=1.6, marker="s", ms=4,
            label="GDPNow")
    ax.plot(x, ex20["nyfed_saar"], color=C_NYFED, lw=1.4, marker="^", ms=4,
            label="NY Fed")
    ax.set_xticks(x)
    ax.set_xticklabels([str(q) for q in ex20.index], rotation=45, fontsize=8)
    ax.axhline(0, color="#9ca3af", lw=0.8)
    ax.grid(color="#e5e7eb", lw=0.5)
    ax.set_axisbelow(True)
    ax.set_ylabel("Real GDP q/q SAAR %")
    ax.set_title("Final pre-release nowcasts vs advance print (2020 omitted for scale)",
                 fontsize=11)
    ax.legend(fontsize=9, ncol=4, frameon=False)
    for s in ax.spines.values():
        s.set_color("#d1d5db")
    chart1 = _img(fig)

    # chart 2: |error| per quarter, ours vs GDPNow
    fig, ax = plt.subplots(figsize=(12, 3.6), dpi=140)
    w = 0.38
    ax.bar(x - w / 2, (ex20["ours_saar"] - ex20["advance_saar"]).abs(), w,
           color=C_OURS, label="Ours")
    ax.bar(x + w / 2, (ex20["gdpnow_saar"] - ex20["advance_saar"]).abs(), w,
           color=C_GDPNOW, label="GDPNow")
    ax.set_xticks(x)
    ax.set_xticklabels([str(q) for q in ex20.index], rotation=45, fontsize=8)
    ax.grid(axis="y", color="#e5e7eb", lw=0.5)
    ax.set_axisbelow(True)
    ax.set_ylabel("|error| pp")
    ax.set_title("Absolute nowcast error vs advance print", fontsize=11)
    ax.legend(fontsize=9, frameon=False)
    for s in ax.spines.values():
        s.set_color("#d1d5db")
    chart2 = _img(fig)

    # error attribution: our error vs net-exports + inventories contributions
    try:
        nx = fetch.get_series("A019RY2Q224SBEA", start="2017-01-01", log=lambda m: None)
        inv = fetch.get_series("A014RY2Q224SBEA", start="2017-01-01", log=lambda m: None)
        nx.index = pd.PeriodIndex(nx.index, freq="Q")
        inv.index = pd.PeriodIndex(inv.index, freq="Q")
        vol = (nx + inv).reindex(df.index)
        our_err = df["ours_saar"] - df["advance_saar"]
        mask = (~df.index.astype(str).str.startswith("2020")) & vol.notna() & our_err.notna()
        corr = float(np.corrcoef(vol[mask], our_err[mask])[0, 1])
        fig, ax = plt.subplots(figsize=(5.6, 4.4), dpi=140)
        ax.scatter(vol[mask], our_err[mask], color=C_OURS, s=28)
        for q_, xx, yy in zip(df.index[mask], vol[mask], our_err[mask]):
            ax.annotate(str(q_), (xx, yy), fontsize=6.5, xytext=(3, 3),
                        textcoords="offset points", color="#6b7280")
        b = np.polyfit(vol[mask], our_err[mask], 1)
        xs = np.linspace(vol[mask].min(), vol[mask].max(), 10)
        ax.plot(xs, np.polyval(b, xs), color="#9ca3af", lw=1, ls="--")
        ax.axhline(0, color="#e5e7eb")
        ax.axvline(0, color="#e5e7eb")
        ax.set_xlabel("Net exports + inventories contribution to SAAR (pp)")
        ax.set_ylabel("Our error vs advance (pp)")
        ax.set_title(f"Error vs trade/inventory swings (corr {corr:.2f}, slope {b[0]:.2f})",
                     fontsize=10)
        for s in ax.spines.values():
            s.set_color("#d1d5db")
        chart3 = _img(fig)
        attribution = (f"<p>Correlation of our error with the net-exports+inventories "
                       f"contribution: <b>{corr:.2f}</b> (slope {b[0]:.2f}). These two "
                       f"components are what GDPNow tracks with dedicated source data "
                       f"(FT900 trade report, inventories reports) and what a monthly "
                       f"factor panel largely cannot see.</p>")
    except Exception as ex:  # noqa: BLE001
        chart3, attribution = "", f"<p>attribution unavailable: {ex}</p>"

    # quad-relevant metric: does the model get the SIGN of the y/y growth
    # rate-of-change right (accelerating vs decelerating vs prior quarter)?
    agree = {"ours": [], "gdpnow": []}
    for q, row in df.iterrows():
        try:
            asof = row["asof"]
            v = fetch.get_series_vintage("GDPC1", asof, start="2010-01-01",
                                         log=lambda m: None)
            adv_date = (pd.Timestamp(asof) + pd.Timedelta("1D")).strftime("%Y-%m-%d")
            adv = fetch.get_series_vintage("GDPC1", adv_date, start="2010-01-01",
                                           log=lambda m: None)
            v.index = pd.PeriodIndex(v.index, freq="Q")
            adv.index = pd.PeriodIndex(adv.index, freq="Q")
            prev_yoy = v.loc[q - 1] / v.loc[q - 5] - 1
            d_adv = (adv.loc[q] / adv.loc[q - 4] - 1) - prev_yoy
            for name, saar in (("ours", row["ours_saar"]), ("gdpnow", row["gdpnow_saar"])):
                lvl_hat = v.loc[q - 1] * (1 + saar / 100) ** 0.25
                d_hat = (lvl_hat / v.loc[q - 4] - 1) - prev_yoy
                agree[name].append(np.sign(d_hat) == np.sign(d_adv))
        except Exception:  # noqa: BLE001 - skip quarters lacking cached vintages
            continue
    direction = ""
    if agree["ours"]:
        direction = (f"<p><b>Quad-relevant direction accuracy</b> (sign of the y/y "
                     f"growth rate-of-change vs the advance print): ours "
                     f"<b>{100 * np.mean(agree['ours']):.0f}%</b>, GDPNow "
                     f"<b>{100 * np.mean(agree['gdpnow']):.0f}%</b> "
                     f"over {len(agree['ours'])} quarters. The quad map depends on "
                     f"this sign, not on SAAR precision.</p>")

    rows = df.reset_index()[["quarter", "asof", "ours_saar", "gdpnow_saar",
                             "nyfed_saar", "stleni_saar", "advance_saar",
                             "revised_saar"]]
    tbl = rows.to_html(index=False, float_format=lambda v: f"{v:.2f}",
                       border=0, na_rep="—")

    html = f"""
<h2>GDP: real-time vintage backtest ({df.index[0]}–{df.index[-1]})</h2>
<p>Protocol: for each quarter, all panel series are rebuilt from ALFRED vintages as of
the day before the advance GDP release, the DFM is refit from scratch, and the nowcast is
compared with the advance print — the same information stance as the published "final"
GDPNow / NY Fed values shown.</p>
<h3>Error vs advance print (pp of SAAR)</h3>
<table class="stats"><thead><tr><th>Model</th><th>n</th><th>RMSE</th><th>MAE</th><th>bias</th></tr></thead>
<tbody>{stats_all}</tbody></table>
<h3>Excluding 2020 (COVID quarters)</h3>
<table class="stats"><thead><tr><th>Model</th><th>n</th><th>RMSE</th><th>MAE</th><th>bias</th></tr></thead>
<tbody>{stats_ex}</tbody></table>
{direction}
{chart1}
{chart2}
<h3>Where our error comes from</h3>
{attribution}
{chart3}
<h3>Per-quarter detail</h3>
<div class="scroll">{tbl}</div>
"""
    return html, df


def cpi_section() -> str:
    df = pd.read_csv(OUT / "cpi_backtest.csv")
    df["m"] = pd.PeriodIndex(df["month"], freq="M")
    e_ours = df["ours_yoy"] - df["actual_yoy_sa"]
    stats_rows = _fmt_stats("Ours (y/y, SA basis)", _stats(e_ours))
    cl = df.dropna(subset=["cleveland_yoy", "cleveland_actual_yoy_nsa"]) \
        if "cleveland_yoy" in df else pd.DataFrame()
    if not cl.empty:
        e_cl = cl["cleveland_yoy"] - cl["cleveland_actual_yoy_nsa"]
        stats_rows += _fmt_stats("Cleveland Fed (y/y, NSA basis)", _stats(e_cl))

    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=140)
    x = df["m"].dt.to_timestamp()
    ax.plot(x, df["actual_yoy_sa"], color=C_ACTUAL, lw=2, label="Actual y/y (SA)")
    ax.plot(x, df["ours_yoy"], color=C_OURS, lw=1.3, label="Ours (final stance)")
    if not cl.empty:
        ax.plot(cl["m"].dt.to_timestamp(), cl["cleveland_yoy"], color=C_CLEV,
                lw=1.1, label="Cleveland Fed (final)")
    ax.grid(color="#e5e7eb", lw=0.5)
    ax.set_axisbelow(True)
    ax.set_ylabel("Headline CPI YoY %")
    ax.set_title("CPI y/y: final pre-release nowcasts vs actual", fontsize=11)
    ax.legend(fontsize=9, frameon=False)
    for s in ax.spines.values():
        s.set_color("#d1d5db")
    chart = _img(fig)

    return f"""
<h2>CPI: pseudo-real-time backtest ({df['month'].iloc[0]}–{df['month'].iloc[-1]})</h2>
<p>Stance: day before each month's CPI release. Caveats: our inputs are current-vintage
(SA CPI history is lightly revised each year); Cleveland's numbers are true real-time and
NSA-based — each model is scored against its own actual definition.</p>
<table class="stats"><thead><tr><th>Model</th><th>n</th><th>RMSE</th><th>MAE</th><th>bias</th></tr></thead>
<tbody>{stats_rows}</tbody></table>
{chart}
"""


def main():
    gdp_html, _df = gdp_section()
    cpi_html = cpi_section()
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Nowcast backtest vs public models</title>
<style>
 body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1150px;
        color: #111827; }}
 h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; }}
 h3 {{ font-size: 14px; margin: 16px 0 6px; color: #374151; }}
 img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; margin: 8px 0; }}
 table {{ border-collapse: collapse; font-size: 13px; }}
 th, td {{ padding: 5px 10px; border-bottom: 1px solid #e5e7eb; text-align: right; }}
 th:first-child, td:first-child {{ text-align: left; }}
 th {{ background: #f9fafb; color: #6b7280; }}
 .scroll {{ overflow-x: auto; }}
 p {{ font-size: 13.5px; color: #374151; }}
</style></head><body>
<h1>Nowcast system backtest vs public models</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M} · nowcast_quad</p>
{gdp_html}
{cpi_html}
</body></html>"""
    out = OUT / "backtest_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
