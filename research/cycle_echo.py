"""Cycle-echo test: does the LEVEL of YoY growth 8 quarters ago inversely
predict the current change in YoY (a ~4-year cycle phase flip), beyond the
base-effect comp channel?

Signals tested for sign(Δyoy_t):
  comp     : -sign(Δcomp_t)                      (existing base-effect signal)
  echo8    : -sign(yoy_{t-8} - trailing 5y mean) (the user's inverse-of-2y-ago)
  combined : sign of the sum of both z-scored signals
Plus ACF of yoy at lags 1-16 and OLS with/without momentum controls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nowcast import fetch  # noqa: E402
from research.base_effects_analysis import yoy_series, _mask  # noqa: E402

OUT = ROOT / "output" / "backtest"


def acf(y: pd.Series, max_lag=16) -> list[float]:
    y = y - y.mean()
    return [float(np.corrcoef(y[l:], y.shift(l).dropna())[0, 1]) for l in range(1, max_lag + 1)]


def ols_t(y, X):
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, res, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    s2 = (resid @ resid) / (len(y) - X1.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X1.T @ X1)))
    return beta, beta / se


def main():
    data = yoy_series()
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), dpi=140)
    for ax, (name, yoy) in zip(axes, data.items()):
        d = _mask(pd.DataFrame({"yoy": yoy}), "1985Q1")["yoy"]
        vals = acf(d)
        colors = ["#1d4ed8" if v >= 0 else "#b91c1c" for v in vals]
        ax.bar(range(1, 17), vals, color=colors)
        ax.axhline(0, color="#9ca3af", lw=0.8)
        ci = 2 / np.sqrt(len(d))
        ax.axhspan(-ci, ci, color="#e5e7eb", alpha=0.6, zorder=0)
        ax.set_title(f"{name} YoY autocorrelation by lag (1985+)", fontsize=10)
        ax.set_xlabel("lag (quarters)")
        for s in ax.spines.values():
            s.set_color("#d1d5db")
    fig.savefig(OUT / "cycle_echo_acf.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    for name, yoy in data.items():
        print(f"===== {name} =====")
        df = pd.DataFrame({"yoy": yoy})
        df["d_yoy"] = df["yoy"].diff()
        df["comp"] = (df["yoy"].shift(4) + df["yoy"].shift(8)) / 2
        df["d_comp"] = df["comp"].diff()
        df["lag8_dev"] = df["yoy"].shift(8) - df["yoy"].rolling(20).mean().shift(1)
        df["d_yoy_lag"] = df["d_yoy"].shift(1)
        for start in ("1985Q1", "1960Q1"):
            d = _mask(df, start).dropna()
            # OLS: d_yoy on lag8 deviation, with and without controls
            b1, t1 = ols_t(d["d_yoy"].values, d[["lag8_dev"]].values)
            b2, t2 = ols_t(d["d_yoy"].values, d[["lag8_dev", "d_comp", "d_yoy_lag"]].values)
            # direction hit rates
            hit_comp = (-np.sign(d["d_comp"]) == np.sign(d["d_yoy"])).mean()
            hit_echo = (-np.sign(d["lag8_dev"]) == np.sign(d["d_yoy"])).mean()
            z = (-(d["d_comp"] / d["d_comp"].std())
                 - (d["lag8_dev"] / d["lag8_dev"].std()))
            hit_comb = (np.sign(z) == np.sign(d["d_yoy"])).mean()
            print(f" {start}+ (n={len(d)}):")
            print(f"   OLS d_yoy ~ lag8_dev alone     : beta {b1[1]:+.3f} (t={t1[1]:+.1f})")
            print(f"   OLS + comp & momentum controls : beta {b2[1]:+.3f} (t={t2[1]:+.1f}) "
                  f"| d_comp beta {b2[2]:+.3f} (t={t2[2]:+.1f})")
            print(f"   direction hit%: comp {100*hit_comp:.0f} | echo8 {100*hit_echo:.0f} "
                  f"| combined {100*hit_comb:.0f}")


if __name__ == "__main__":
    main()
