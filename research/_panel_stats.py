import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from research.hf_report import _direction  # noqa: E402

files = {
    "baseline": ROOT / "output/backtest/gdp_backtest.csv",
    "nyfed_full": ROOT / "output/backtest/gdp_backtest_nyfed_full.csv",
    "hf": ROOT / "output/backtest/gdp_backtest_hf.csv",
}
rows = []
base = None
for name, path in files.items():
    f = pd.read_csv(path)
    f["q"] = pd.PeriodIndex(f["quarter"], freq="Q")
    f = f.set_index("q").sort_index()
    if base is None:
        base = f
    ex = f[~f.index.astype(str).str.startswith("2020")]
    e = ex["ours_saar"] - ex["advance_saar"]
    rows.append((name, np.sqrt((e ** 2).mean()), e.abs().mean(), e.mean(),
                 _direction(f, "ours_saar")))

ex = base[~base.index.astype(str).str.startswith("2020")]
e = ex["gdpnow_saar"] - ex["advance_saar"]
rows.append(("GDPNow", np.sqrt((e ** 2).mean()), e.abs().mean(), e.mean(),
             _direction(base, "gdpnow_saar")))

print(f"{'panel':14s} {'RMSE':>6s} {'MAE':>6s} {'bias':>6s} {'dir%':>5s}   (ex-2020, n=29)")
for name, rmse, mae, bias, d in rows:
    print(f"{name:14s} {rmse:6.2f} {mae:6.2f} {bias:+6.2f} {d:5.0f}")

# 2025 zoom
print("\n2025-2026 errors per panel:")
sub = {}
for name, path in files.items():
    f = pd.read_csv(path)
    f["q"] = pd.PeriodIndex(f["quarter"], freq="Q")
    f = f.set_index("q").sort_index()
    sub[name] = (f["ours_saar"] - f["advance_saar"]).loc["2025Q1":]
t = pd.DataFrame(sub)
f0 = base
t["gdpnow"] = (f0["gdpnow_saar"] - f0["advance_saar"]).loc["2025Q1":]
print(t.round(2).to_string())
