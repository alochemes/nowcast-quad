"""Out-quarter projection via comparative base effects (Hedgeye-style).

For quarters beyond the nowcast horizon, the YoY rate is adjusted inversely
and proportionally to the marginal change in the comparative base, where the
comp for quarter t is the 2-year average YoY rate in the base period:
    comp_t  = (yoy_{t-4} + yoy_{t-8}) / 2
    yoy_t   = yoy_{t-1} - K * (comp_t - comp_{t-1})
K (pass-through) is a heuristic set in config.BASE_EFFECT_K.
"""

from __future__ import annotations

import pandas as pd

from . import config


def project_out_quarters(yoy: pd.Series, n: int = None, k: float = None) -> pd.Series:
    """Extend a quarterly YoY series n quarters using the comp model."""
    n = config.N_OUT_QUARTERS if n is None else n
    k = config.BASE_EFFECT_K if k is None else k
    s = yoy.copy()
    for _ in range(n):
        t = s.index[-1] + 1
        comp_t = (s.loc[t - 4] + s.loc[t - 8]) / 2
        comp_prev = (s.loc[t - 5] + s.loc[t - 9]) / 2
        s.loc[t] = s.iloc[-1] - k * (comp_t - comp_prev)
    return s
