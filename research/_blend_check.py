import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nowcast import fetch  # noqa: E402

import sys as _sys
bt = pd.read_csv(_sys.argv[1] if len(_sys.argv) > 1 else "output/backtest/gdp_backtest.csv")
bt["q"] = pd.PeriodIndex(bt["quarter"], freq="Q")
bt = bt.set_index("q")
mask = ~bt.index.astype(str).str.startswith("2020")
d = bt[mask].dropna(subset=["gdpnow_saar"])
adv = d["advance_saar"]


def rmse(x):
    return float(np.sqrt(((x - adv) ** 2).mean()))


for w in [0.0, 0.15, 0.3, 0.5, 1.0]:
    blend = (1 - w) * d["gdpnow_saar"] + w * d["ours_saar"]
    print(f"blend w_ours={w:.2f}: RMSE {rmse(blend):.2f}pp")

gl = fetch.get_series("GDPC1", start="2015-01-01", log=lambda m: None)
gl = gl.set_axis(pd.PeriodIndex(gl.index, freq="Q"))


def dir_acc(saar):
    ok = []
    for q, s in saar.items():
        try:
            prev = gl.loc[q - 1] / gl.loc[q - 5] - 1
            d_hat = (gl.loc[q - 1] * (1 + s / 100) ** 0.25) / gl.loc[q - 4] - 1 - prev
            d_act = (gl.loc[q - 1] * (1 + adv.loc[q] / 100) ** 0.25) / gl.loc[q - 4] - 1 - prev
            ok.append(np.sign(d_hat) == np.sign(d_act))
        except KeyError:
            pass
    return 100 * np.mean(ok)


blend = 0.85 * d["gdpnow_saar"] + 0.15 * d["ours_saar"]
print(f"direction: ours {dir_acc(d['ours_saar']):.0f}%  "
      f"gdpnow {dir_acc(d['gdpnow_saar']):.0f}%  blend {dir_acc(blend):.0f}%")
