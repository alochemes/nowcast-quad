"""Base-effect analysis: does the trailing 2-year SMA of a YoY series predict
the DIRECTION of the next YoY change, for GDP and CPI?

Two comp definitions per series:
  sma8    : trailing 8-quarter SMA of YoY through t-1 (the user's framing;
            fully known at t)
  hedgeye : (yoy_{t-4} + yoy_{t-8}) / 2 — the base-period comp our
            out-quarter model uses (known 4 quarters ahead of t)
Signal = change in the comp vs prior quarter. Base-effect logic predicts
sign(Δyoy_t) = -sign(Δcomp_t): steepening comps -> deceleration.

Tests: hit rates vs baselines, conditional hit rates by signal size, OLS
Δyoy = α + β·Δcomp (calibrates K), horizon 1-4 forecasts, stability, and a
tie-breaker experiment on the 33 real-time ensemble backtest quarters.

Writes output/backtest/base_effects_report.html.
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
C_MAIN, C_ACC = "#1d4ed8", "#b45309"


def _img(fig, name) -> str:
    p = OUT / name
    fig.savefig(p, bbox_inches="tight", facecolor="white", dpi=140)
    plt.close(fig)
    return f"<img src='data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}'>"


def yoy_series() -> dict[str, pd.Series]:
    gdp = fetch.get_series("GDPC1", start="1950-01-01", log=lambda m: None)
    gdp.index = pd.PeriodIndex(gdp.index, freq="Q")
    gdp_yoy = ((gdp / gdp.shift(4) - 1) * 100).dropna()

    cpi = fetch.get_series("CPIAUCSL", start="1950-01-01", log=lambda m: None)
    cpi.index = pd.PeriodIndex(cpi.index, freq="M")
    cpi = cpi.reindex(pd.period_range(cpi.index[0], cpi.index[-1], freq="M"))
    yoy_m = (cpi / cpi.shift(12) - 1) * 100
    cpi_yoy = yoy_m.groupby(yoy_m.index.asfreq("Q")).mean().dropna()
    return {"GDP": gdp_yoy, "CPI": cpi_yoy}


def comps(yoy: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"yoy": yoy})
    df["sma8"] = yoy.rolling(8).mean().shift(1)          # through t-1
    df["hedgeye"] = (yoy.shift(4) + yoy.shift(8)) / 2    # base-period comp
    df["d_yoy"] = df["yoy"].diff()
    df["d_sma8"] = df["sma8"].diff()
    df["d_hedgeye"] = df["hedgeye"].diff()
    return df.dropna()


def _mask(df, start, ex2020=True):
    m = df.index >= pd.Period(start, "Q")
    if ex2020:
        m &= ~df.index.astype(str).str.startswith("2020")
        m &= ~df.index.astype(str).str.startswith("2021")  # base-effect echo of 2020
    return df[m]


def hit_stats(df: pd.DataFrame, sig_col: str) -> dict:
    d = df[df[sig_col] != 0]
    pred = -np.sign(d[sig_col])              # inverse relationship
    hit = (pred == np.sign(d["d_yoy"])).mean()
    momentum = (np.sign(d["d_yoy"].shift(1)) == np.sign(d["d_yoy"])).dropna().mean()
    # conditional on signal size terciles
    q = d[sig_col].abs().quantile([1 / 3, 2 / 3]).values
    small = d[d[sig_col].abs() <= q[0]]
    large = d[d[sig_col].abs() >= q[1]]
    b = np.polyfit(d[sig_col], d["d_yoy"], 1)
    r = np.corrcoef(d[sig_col], d["d_yoy"])[0, 1]
    return {"n": len(d), "hit%": 100 * hit, "momentum%": 100 * momentum,
            "hit% |signal| small": 100 * (-np.sign(small[sig_col]) == np.sign(small["d_yoy"])).mean(),
            "hit% |signal| large": 100 * (-np.sign(large[sig_col]) == np.sign(large["d_yoy"])).mean(),
            "beta (opt K)": -b[0], "corr": r}


def horizon_table(yoy: pd.Series, start: str) -> pd.DataFrame:
    """Direction hit rate of the pure comp model at horizons 1-4 (as used for
    out-quarters), vs a no-change baseline."""
    rows = []
    for h in (1, 2, 3, 4):
        comp_h = (yoy.shift(4 - h) + yoy.shift(8 - h)) / 2  # comp for t+h seen from t
        d_comp = comp_h.diff()
        d_yoy_h = yoy.diff().shift(-h + 1)                  # Δyoy at t+h... aligned below
        df = pd.DataFrame({"sig": d_comp, "dy": yoy.shift(-h) - yoy.shift(-h + 1)}).dropna()
        df = _mask(df, start)
        df = df[df["sig"] != 0]
        rows.append({"horizon (qtrs ahead)": h, "n": len(df),
                     "comp-model hit%": 100 * (-np.sign(df["sig"]) == np.sign(df["dy"])).mean()})
    return pd.DataFrame(rows)


def scatter_chart(dfs: dict, sig: str, name: str) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), dpi=140)
    for ax, (label, d) in zip(axes, dfs.items()):
        ax.scatter(d[sig], d["d_yoy"], s=14, alpha=0.55, color=C_MAIN)
        b = np.polyfit(d[sig], d["d_yoy"], 1)
        xs = np.linspace(d[sig].min(), d[sig].max(), 10)
        ax.plot(xs, np.polyval(b, xs), color=C_ACC, lw=1.8,
                label=f"slope {b[0]:.2f} (K={-b[0]:.2f})")
        ax.axhline(0, color="#9ca3af", lw=0.8)
        ax.axvline(0, color="#9ca3af", lw=0.8)
        ax.set_xlabel(f"Δ comp ({sig}, pp)")
        ax.set_ylabel("Δ YoY (pp)")
        ax.set_title(label, fontsize=11)
        ax.legend(fontsize=9, frameon=False)
        ax.grid(color="#e5e7eb", lw=0.5)
        ax.set_axisbelow(True)
        for s in ax.spines.values():
            s.set_color("#d1d5db")
    return _img(fig, name)


def rolling_chart(dfs: dict, sig: str, name: str) -> str:
    fig, ax = plt.subplots(figsize=(11, 3.8), dpi=140)
    for (label, d), color in zip(dfs.items(), (C_MAIN, C_ACC)):
        hit = (-np.sign(d[sig]) == np.sign(d["d_yoy"])).astype(float)
        roll = hit.rolling(40).mean() * 100
        ax.plot(roll.index.to_timestamp(), roll, lw=1.6, color=color, label=label)
    ax.axhline(50, color="#9ca3af", lw=1, ls="--")
    ax.set_ylabel("rolling 10y hit rate (%)")
    ax.set_title(f"Stability of the {sig} direction signal", fontsize=11)
    ax.legend(fontsize=9, frameon=False)
    ax.grid(color="#e5e7eb", lw=0.5)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_color("#d1d5db")
    return _img(fig, name)


def tiebreak_experiment() -> str:
    """On the 33 real-time backtest quarters: does deferring to the comp signal
    when the ensemble's implied |Δyoy| is small add directional hits?"""
    f = pd.read_csv(OUT / "gdp_backtest_hf.csv")
    f["q"] = pd.PeriodIndex(f["quarter"], freq="Q")
    f = f.set_index("q").sort_index().dropna(subset=["gdpnow_saar"])
    w = 0.15
    rows_out = []
    details = []
    for q, row in f.iterrows():
        try:
            v = fetch.get_series_vintage("GDPC1", row["asof"], start="2005-01-01",
                                         log=lambda m: None)
            adv_date = (pd.Timestamp(row["asof"]) + pd.Timedelta("1D")).strftime("%Y-%m-%d")
            adv = fetch.get_series_vintage("GDPC1", adv_date, start="2005-01-01",
                                           log=lambda m: None)
            v.index = pd.PeriodIndex(v.index, freq="Q")
            adv.index = pd.PeriodIndex(adv.index, freq="Q")
            vyoy = (v / v.shift(4) - 1) * 100
            prev_yoy = vyoy.loc[q - 1]
            blend = w * row["ours_saar"] + (1 - w) * row["gdpnow_saar"]
            yoy_hat = ((v.loc[q - 1] * (1 + blend / 100) ** 0.25) / v.loc[q - 4] - 1) * 100
            d_hat = yoy_hat - prev_yoy
            d_act = (adv.loc[q] / adv.loc[q - 4] - 1) * 100 - prev_yoy
            comp = (vyoy.loc[q - 4] + vyoy.loc[q - 8]) / 2
            comp_prev = (vyoy.loc[q - 5] + vyoy.loc[q - 9]) / 2
            comp_sig = -np.sign(comp - comp_prev)
            details.append({"q": q, "d_hat": d_hat, "d_act_sign": np.sign(d_act),
                            "comp_sig": comp_sig})
        except Exception:  # noqa: BLE001
            continue
    d = pd.DataFrame(details).set_index("q")
    base_hit = (np.sign(d["d_hat"]) == d["d_act_sign"]).mean()
    for thr in (0, 5, 10, 15, 20, 30):
        pred = np.where(d["d_hat"].abs() * 100 <= thr, d["comp_sig"], np.sign(d["d_hat"]))
        rows_out.append({"tie-break threshold (bps)": thr,
                         "quarters deferred to comp": int((d["d_hat"].abs() * 100 <= thr).sum()),
                         "direction hit%": 100 * (pred == d["d_act_sign"]).mean()})
    t = pd.DataFrame(rows_out)
    comp_alone = 100 * (d["comp_sig"] == d["d_act_sign"]).mean()
    return (f"<p>Real-time tie-breaker test on the {len(d)} ensemble backtest quarters "
            f"(all-quarters sample, incl. 2020): ensemble alone "
            f"<b>{100 * base_hit:.0f}%</b>; the pure comp signal alone scores "
            f"<b>{comp_alone:.0f}%</b> on the same quarters. Deferring to the comp "
            f"when the ensemble's implied |Δyoy| is below a threshold:</p>"
            + t.to_html(index=False, border=0, float_format=lambda v: f"{v:.0f}"))


def main():
    data = yoy_series()
    sections = []
    summary_rows = []
    for start, label in (("1985Q1", "1985–2026 ex-2020/21"), ("1960Q1", "1960–2026 ex-2020/21")):
        for name, yoy in data.items():
            df = _mask(comps(yoy), start)
            for sig in ("d_sma8", "d_hedgeye"):
                s = hit_stats(df, sig)
                summary_rows.append({"series": name, "sample": label,
                                     "signal": sig.replace("d_", "Δ"), **s})
    summary = pd.DataFrame(summary_rows)
    summary_html = summary.to_html(index=False, border=0,
                                   float_format=lambda v: f"{v:.2f}")

    modern = {name: _mask(comps(yoy), "1985Q1") for name, yoy in data.items()}
    charts = (scatter_chart(modern, "d_hedgeye", "be_scatter_hedgeye.png")
              + scatter_chart(modern, "d_sma8", "be_scatter_sma8.png")
              + rolling_chart(modern, "d_hedgeye", "be_rolling.png"))

    hz = {name: horizon_table(yoy, "1985Q1") for name, yoy in data.items()}
    hz_html = "".join(f"<h3>{n} — comp model by horizon</h3>"
                      + t.to_html(index=False, border=0, float_format=lambda v: f"{v:.0f}")
                      for n, t in hz.items())

    tb = tiebreak_experiment()

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Base-effect directionality analysis</title>
<style>
 body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1150px; color: #111827; }}
 h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 26px; }} h3 {{ font-size: 14px; margin: 14px 0 4px; }}
 img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; margin: 8px 0; }}
 table {{ border-collapse: collapse; font-size: 12.5px; margin: 6px 0; }}
 th, td {{ padding: 4px 9px; border-bottom: 1px solid #e5e7eb; text-align: right; }}
 th:first-child, td:first-child {{ text-align: left; }}
 th {{ background: #f9fafb; color: #6b7280; }}
 p {{ font-size: 13.5px; color: #374151; }}
</style></head><body>
<h1>Base effects: does the 2-year comp SMA predict YoY direction?</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M}. Signal = quarterly change in the comp
(Δsma8 = trailing 8-qtr SMA of YoY through t−1; Δhedgeye = (yoy_{{t−4}}+yoy_{{t−8}})/2, our
out-quarter comp). Prediction: sign(Δyoy) = −sign(Δcomp). "opt K" = −OLS slope of
Δyoy on Δcomp, the empirically calibrated pass-through (we currently use K=0.5).
2020–2021 excluded (COVID collapse + its mechanical base-effect echo).</p>
<h2>Hit rates and calibration</h2>
{summary_html}
<h2>Relationship shape</h2>
{charts}
<h2>Out-quarter horizons (what our comp model is used for)</h2>
{hz_html}
<h2>Tie-breaker experiment on the real-time ensemble quarters</h2>
{tb}
</body></html>"""
    (OUT / "base_effects_report.html").write_text(html, encoding="utf-8")
    print("wrote", OUT / "base_effects_report.html")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.2f}"))


if __name__ == "__main__":
    main()
