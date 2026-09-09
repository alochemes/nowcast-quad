"""Ensemble weight sensitivity analysis.

1) 1-D sweep: w·ours(hf) + (1-w)·GDPNow — RMSE, MAE, direction vs weight.
2) 3-model simplex: ours + GDPNow + NY Fed (and ours + GDPNow + STLENI):
   heatmaps + 3D surface of RMSE and direction accuracy over the weight simplex.
3) CPI leg: blending our CPI nowcast with the Cleveland Fed's.

Direction accuracy uses the same real-time convention as the backtests: sign
of the implied y/y rate-of-change vs the advance print, on vintage GDP levels.
All GDP stats ex-2020. Writes output/backtest/ensemble_sensitivity.html.
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
C_MAIN, C_MARK = "#1d4ed8", "#b91c1c"


def _img(fig, name) -> str:
    p = OUT / name
    fig.savefig(p, bbox_inches="tight", facecolor="white", dpi=140)
    plt.close(fig)
    return f"<img src='data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}'>"


def load_gdp() -> pd.DataFrame:
    f = pd.read_csv(OUT / "gdp_backtest_hf.csv")
    f["q"] = pd.PeriodIndex(f["quarter"], freq="Q")
    f = f.set_index("q").sort_index()
    ny = pd.read_csv(BENCH / "ny_fed_nowcast_by_quarter.csv")
    ny["q"] = pd.PeriodIndex(ny["target_quarter"], freq="Q")
    ny = ny[ny["forecast_after_quarter_end"] == 1].set_index("q")
    f["nyfed_saar"] = ny["nowcast_qq_saar"]
    stl = pd.read_csv(BENCH / "stleni.csv", parse_dates=["date"])
    stl["q"] = pd.PeriodIndex(stl["date"], freq="Q")
    f["stleni_saar"] = stl.set_index("q")["value"]
    f = f[~f.index.astype(str).str.startswith("2020")]
    return f


def direction_primitives(f: pd.DataFrame) -> pd.DataFrame:
    """Per quarter: constants so direction(saar) is a cheap vector op."""
    rows = []
    for q, row in f.iterrows():
        try:
            v = fetch.get_series_vintage("GDPC1", row["asof"], start="2010-01-01",
                                         log=lambda m: None)
            adv_date = (pd.Timestamp(row["asof"]) + pd.Timedelta("1D")).strftime("%Y-%m-%d")
            adv = fetch.get_series_vintage("GDPC1", adv_date, start="2010-01-01",
                                           log=lambda m: None)
            v.index = pd.PeriodIndex(v.index, freq="Q")
            adv.index = pd.PeriodIndex(adv.index, freq="Q")
            prev = v.loc[q - 1] / v.loc[q - 5] - 1
            d_act = (adv.loc[q] / adv.loc[q - 4] - 1) - prev
            rows.append({"q": q, "lvl_prev": v.loc[q - 1], "lvl_base": v.loc[q - 4],
                         "prev_yoy": prev, "d_act_sign": np.sign(d_act)})
        except Exception:  # noqa: BLE001
            continue
    return pd.DataFrame(rows).set_index("q")


def direction_acc(saar: pd.Series, prim: pd.DataFrame) -> float:
    j = prim.join(saar.rename("s")).dropna()
    d_hat = (j["lvl_prev"] * (1 + j["s"] / 100) ** 0.25) / j["lvl_base"] - 1 - j["prev_yoy"]
    return float(100 * (np.sign(d_hat) == j["d_act_sign"]).mean())


def stats(saar: pd.Series, adv: pd.Series, prim: pd.DataFrame) -> tuple[float, float, float]:
    e = (saar - adv).dropna()
    return (float(np.sqrt((e ** 2).mean())), float(e.abs().mean()),
            direction_acc(saar, prim))


def sweep_1d(f, prim) -> tuple[str, pd.DataFrame]:
    d = f.dropna(subset=["gdpnow_saar"])
    ws = np.round(np.arange(0, 1.0001, 0.05), 2)
    rows = []
    for w in ws:
        blend = w * d["ours_saar"] + (1 - w) * d["gdpnow_saar"]
        r, m, dd = stats(blend, d["advance_saar"], prim)
        rows.append({"w_ours": w, "RMSE": r, "MAE": m, "direction": dd})
    t = pd.DataFrame(rows)
    best = t.loc[t["RMSE"].idxmin()]
    flat = t[t["RMSE"] <= t["RMSE"].min() * 1.05]

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9), dpi=140)
    ax = axes[0]
    ax.plot(t["w_ours"], t["RMSE"], color=C_MAIN, lw=2, marker="o", ms=3.5)
    ax.axvline(0.15, color=C_MARK, lw=1, ls="--")
    ax.annotate("proposed 0.15", (0.15, t["RMSE"].max() * 0.95), color=C_MARK, fontsize=9)
    ax.axvspan(flat["w_ours"].min(), flat["w_ours"].max(), color="#dbeafe", zorder=0)
    ax.set_xlabel("weight on ours (rest on GDPNow)")
    ax.set_ylabel("RMSE vs advance (pp)")
    ax.set_title("Level accuracy", fontsize=11)
    ax = axes[1]
    ax.plot(t["w_ours"], t["direction"], color=C_MAIN, lw=2, marker="o", ms=3.5)
    ax.axvline(0.15, color=C_MARK, lw=1, ls="--")
    ax.set_xlabel("weight on ours (rest on GDPNow)")
    ax.set_ylabel("direction accuracy (%)")
    ax.set_title("Quad-relevant direction accuracy", fontsize=11)
    for ax in axes:
        ax.grid(color="#e5e7eb", lw=0.5)
        ax.set_axisbelow(True)
        for s in ax.spines.values():
            s.set_color("#d1d5db")
    img = _img(fig, "sweep1d.png")
    note = (f"<p>Optimum at w_ours = <b>{best['w_ours']:.2f}</b> "
            f"(RMSE {best['RMSE']:.2f}pp). Shaded band = weights within 5% of the "
            f"minimum RMSE: <b>{flat['w_ours'].min():.2f}–{flat['w_ours'].max():.2f}</b> — "
            f"the choice is robust inside that range. n={len(d)} quarters ex-2020.</p>")
    return note + img + "<div class='scroll'>" + t.to_html(
        index=False, border=0, float_format=lambda v: f"{v:.2f}") + "</div>", t


def simplex(f, prim, third_col: str, third_name: str) -> tuple[str, dict]:
    d = f.dropna(subset=["gdpnow_saar", third_col])
    step = 0.05
    grid = np.round(np.arange(0, 1.0001, step), 2)
    R = np.full((len(grid), len(grid)), np.nan)
    D = np.full((len(grid), len(grid)), np.nan)
    for i, w_o in enumerate(grid):
        for j, w_t in enumerate(grid):
            if w_o + w_t > 1.0001:
                continue
            w_g = 1 - w_o - w_t
            blend = (w_o * d["ours_saar"] + w_g * d["gdpnow_saar"]
                     + w_t * d[third_col])
            r, _m, dd = stats(blend, d["advance_saar"], prim)
            R[j, i], D[j, i] = r, dd
    ij = np.unravel_index(np.nanargmin(R), R.shape)
    best = {"w_ours": grid[ij[1]], f"w_{third_name}": grid[ij[0]],
            "w_gdpnow": round(1 - grid[ij[1]] - grid[ij[0]], 2),
            "RMSE": float(R[ij]), "direction": float(D[ij]), "n": len(d)}

    # heatmaps
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6), dpi=140)
    for ax, Z, title, cmap in ((axes[0], R, "RMSE (pp) — lower is better", "Blues_r"),
                               (axes[1], D, "Direction accuracy (%) — higher is better", "Blues")):
        pc = ax.pcolormesh(grid, grid, Z, cmap=cmap, shading="nearest")
        fig.colorbar(pc, ax=ax, shrink=0.85)
        ax.plot(best["w_ours"], best[f"w_{third_name}"], "o", color=C_MARK, ms=8,
                mfc="none", mew=2)
        ax.set_xlabel("weight: ours (hf)")
        ax.set_ylabel(f"weight: {third_name}")
        ax.set_title(title + f"   (rest = GDPNow)", fontsize=10)
        for s in ax.spines.values():
            s.set_color("#d1d5db")
    img1 = _img(fig, f"simplex_{third_name}.png")

    # 3D surface of RMSE
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
    fig = plt.figure(figsize=(7.5, 5.6), dpi=140)
    ax = fig.add_subplot(111, projection="3d")
    X, Y = np.meshgrid(grid, grid)
    Zm = np.ma.masked_invalid(R)
    surf = ax.plot_surface(X, Y, Zm, cmap="Blues_r", edgecolor="none", alpha=0.95)
    fig.colorbar(surf, shrink=0.6)
    ax.scatter([best["w_ours"]], [best[f"w_{third_name}"]], [best["RMSE"]],
               color=C_MARK, s=40)
    ax.set_xlabel("w ours (hf)")
    ax.set_ylabel(f"w {third_name}")
    ax.set_zlabel("RMSE (pp)")
    ax.set_title(f"RMSE surface: ours + GDPNow + {third_name}", fontsize=10)
    ax.view_init(elev=28, azim=-135)
    img2 = _img(fig, f"surface_{third_name}.png")

    note = (f"<p>Best 3-model blend (n={best['n']} quarters ex-2020 where all three "
            f"published): ours <b>{best['w_ours']:.2f}</b> / {third_name} "
            f"<b>{best[f'w_{third_name}']:.2f}</b> / GDPNow <b>{best['w_gdpnow']:.2f}</b> "
            f"→ RMSE <b>{best['RMSE']:.2f}pp</b>, direction <b>{best['direction']:.0f}%</b>.</p>")
    return note + img1 + img2, best


def cpi_blend() -> str:
    df = pd.read_csv(OUT / "cpi_backtest.csv").dropna(
        subset=["cleveland_yoy", "cleveland_actual_yoy_nsa"])
    rows = []
    for w in np.round(np.arange(0, 1.0001, 0.1), 2):
        blend = w * df["ours_yoy"] + (1 - w) * df["cleveland_yoy"]
        e = blend - df["actual_yoy_sa"]
        # direction: sign of monthly change in y/y
        db = blend.diff()
        da = df["actual_yoy_sa"].diff()
        rows.append({"w_ours": w, "RMSE": float(np.sqrt((e ** 2).mean())),
                     "direction": float(100 * (np.sign(db) == np.sign(da)).dropna().mean())})
    t = pd.DataFrame(rows)
    best = t.loc[t["RMSE"].idxmin()]
    return (f"<p>CPI leg (n={len(df)} months, scored on SA actuals; Cleveland forecasts "
            f"are NSA-based, which costs them a small level penalty here): best blend "
            f"w_ours = <b>{best['w_ours']:.1f}</b>, RMSE {best['RMSE']:.3f}pp vs "
            f"{t.loc[t.w_ours == 1.0, 'RMSE'].iloc[0]:.3f} (ours alone) and "
            f"{t.loc[t.w_ours == 0.0, 'RMSE'].iloc[0]:.3f} (Cleveland alone).</p>"
            + "<div class='scroll'>" + t.to_html(index=False, border=0,
                                                 float_format=lambda v: f"{v:.3f}") + "</div>")


def main():
    f = load_gdp()
    prim = direction_primitives(f)
    s1, t1 = sweep_1d(f, prim)
    s2, best_ny = simplex(f, prim, "nyfed_saar", "NYFed")
    s3, best_stl = simplex(f, prim, "stleni_saar", "STLENI")
    s4 = cpi_blend()
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Ensemble sensitivity analysis</title>
<style>
 body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1150px; color: #111827; }}
 h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; }}
 img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; margin: 8px 0; }}
 table {{ border-collapse: collapse; font-size: 12.5px; }}
 th, td {{ padding: 4px 9px; border-bottom: 1px solid #e5e7eb; text-align: right; }}
 th {{ background: #f9fafb; color: #6b7280; }}
 .scroll {{ overflow-x: auto; max-height: 300px; overflow-y: auto; display: inline-block; }}
 p {{ font-size: 13.5px; color: #374151; }}
</style></head><body>
<h1>Ensemble weight sensitivity</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M} · all GDP stats ex-2020, vs advance print,
direction = sign of implied y/y rate-of-change on real-time vintage levels.</p>
<h2>1) Two-model sweep: ours (hf) vs GDPNow</h2>
{s1}
<h2>2) Three-model: + NY Fed Staff Nowcast</h2>
{s2}
<h2>3) Three-model alternative: + St. Louis Fed ENI</h2>
{s3}
<h2>4) CPI leg: ours vs Cleveland Fed</h2>
{s4}
</body></html>"""
    (OUT / "ensemble_sensitivity.html").write_text(html, encoding="utf-8")
    print("wrote", OUT / "ensemble_sensitivity.html")
    print("\n1D sweep (key rows):")
    print(t1[t1["w_ours"].isin([0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.5, 1.0])].to_string(index=False))
    print("\nbest 3-model NYFed:", best_ny)
    print("best 3-model STLENI:", best_stl)


if __name__ == "__main__":
    main()
