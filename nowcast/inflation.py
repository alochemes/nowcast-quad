"""CPI nowcast following the Cleveland Fed model (Knotek & Zaman 2017).

Monthly m/m inflation for unreleased months is built from components:
  core, food : 12-month moving average of realized m/m (applied recursively)
  gasoline   : two-stage levels model — rolling 60m OLS of monthly NSA retail
               gasoline (EIA weekly, averaged by month, partial months kept) on
               monthly Brent; AR(1) on the gap (pass-through lag); oil extended
               one month as a random walk. NSA m/m is converted to SA with an
               empirical seasonal factor (3-year same-month mean of the gap
               between NSA pump-price inflation and SA CPI-gasoline inflation).
  headline   : rolling 24m OLS of headline m/m on (core, food, gasoline) m/m —
               the coefficients absorb non-gasoline energy and weight drift.
               Months beyond the reach of any gasoline estimate fall back to a
               12-month MA of realized headline m/m.

Quarterly inflation = quarterly average of monthly YoY readings (Hedgeye
convention), computed on realized + nowcast SA index levels.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, fetch


def _mm(s: pd.Series) -> pd.Series:
    """Non-annualized m/m % change (Cleveland convention)."""
    return 100 * s.pct_change(fill_method=None)


def _reindex_full(s: pd.Series) -> pd.Series:
    """Reindex to a gapless monthly PeriodIndex so shift/diff stay calendar-
    aligned (e.g. the Oct-2025 shutdown gap must become NaN, not vanish)."""
    return s.reindex(pd.period_range(s.index[0], s.index[-1], freq="M"))


def _monthly_avg(s: pd.Series) -> pd.Series:
    return _reindex_full(s.groupby(pd.PeriodIndex(s.index, freq="M")).mean())


def _ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return coef


def _gas_model(gas_nsa_m: pd.Series, oil_m: pd.Series, months: list[pd.Period], log=print):
    """Forecast monthly NSA pump-price levels for `months` (two-stage model)."""
    df = pd.DataFrame({"gas": gas_nsa_m, "oil": oil_m}).dropna().tail(config.GAS_REG_WINDOW)
    coef = _ols(df["gas"].values, df["oil"].values.reshape(-1, 1))
    alpha, beta = float(coef[0]), float(coef[1])
    gap = df["gas"] - (alpha + beta * df["oil"])
    g, g1 = gap.values[1:], gap.values[:-1]
    a = float((g1 @ g) / (g1 @ g1))  # AR(1) through the origin, per spec
    log(f"gas levels model: gas = {alpha:.2f} + {beta:.4f}*brent, gap AR(1) a={a:.2f}")

    levels = gas_nsa_m.copy()
    levels.attrs["params"] = f"gas = {alpha:.2f} + {beta:.4f}·brent, gap AR(1) a = {a:.2f} (60m)"
    last_oil = oil_m.dropna().iloc[-1]
    for m in months:
        if m in levels.index and not np.isnan(levels.loc[m]):
            continue  # partial-month weekly average already in hand
        oil_m_val = oil_m.loc[m] if m in oil_m.index and not np.isnan(oil_m.get(m, np.nan)) else last_oil
        prev_gap = levels.loc[m - 1] - (alpha + beta * (oil_m.get(m - 1, last_oil) if m - 1 in oil_m.index else last_oil))
        levels.loc[m] = alpha + beta * oil_m_val + a * prev_gap
    return levels


def _seasonal_factor(gas_nsa_mm: pd.Series, gascpi_sa_mm: pd.Series, m: pd.Period) -> float:
    """3-year same-calendar-month mean of (NSA pump inflation - SA CPI gasoline inflation)."""
    vals = []
    for j in (1, 2, 3):
        p = m - 12 * j
        if p in gas_nsa_mm.index and p in gascpi_sa_mm.index:
            v = gas_nsa_mm.loc[p] - gascpi_sa_mm.loc[p]
            if not np.isnan(v):
                vals.append(v)
    return float(np.mean(vals)) if vals else 0.0


def nowcast_cpi_yoy(today: pd.Timestamp | None = None, log=print,
                    asof: pd.Timestamp | None = None) -> dict:
    """Nowcast monthly CPI through the end of the current quarter.

    asof: pseudo-real-time stance for backtesting — inputs are truncated to
    what was released by that date (CPI months by release schedule, weekly
    gasoline and daily Brent by observation date). Current-vintage values are
    used (SA CPI history is lightly revised each February; NSA is unrevised).

    Returns dict with:
      yoy_q: quarterly Series, average of monthly YoY (%), actual + nowcast
      first_estimate: first quarter containing any nowcast month
      monthly_nowcast: projected m/m details for inspection
      yoy_m_nowcast: {month: projected YoY %} for the nowcast months
    """
    today = pd.Timestamp.now() if today is None else today
    if asof is not None:
        today = asof
    ids = [config.CPI_HEADLINE, config.CPI_CORE, config.CPI_FOOD, config.CPI_GASOLINE]
    raw = fetch.get_many(ids + [config.GAS_WEEKLY, config.CPI_BRENT],
                         start="1995-01-01", log=log)
    if asof is not None:
        raw = dict(raw)
        # CPI for month m is released ~mid m+1
        last_released = (pd.Period(asof, freq="M")
                         - (1 if asof.day >= 15 else 2))
        for sid in ids:
            s = raw[sid]
            raw[sid] = s[s.index <= last_released.end_time]
        for sid in (config.GAS_WEEKLY, config.CPI_BRENT):
            s = raw[sid]
            raw[sid] = s[s.index <= asof]

    def as_m(s):
        s = s.copy()
        s.index = pd.PeriodIndex(s.index, freq="M")
        return _reindex_full(s)

    headline = as_m(raw[config.CPI_HEADLINE])
    core = as_m(raw[config.CPI_CORE])
    food = as_m(raw[config.CPI_FOOD])
    gascpi = as_m(raw[config.CPI_GASOLINE])
    gas_nsa_m = _monthly_avg(raw[config.GAS_WEEKLY])
    oil_m = _monthly_avg(raw[config.CPI_BRENT])

    headline_mm = _mm(headline)
    core_mm, food_mm, gascpi_mm = _mm(core), _mm(food), _mm(gascpi)
    gas_nsa_mm = _mm(gas_nsa_m)

    # rolling 24m aggregation regression: headline on components
    agg = pd.DataFrame({"h": headline_mm, "c": core_mm, "f": food_mm,
                        "g": gascpi_mm}).dropna().tail(config.AGG_WINDOW)
    b0, bc, bf, bg = _ols(agg["h"].values, agg[["c", "f", "g"]].values)
    log(f"aggregation: h = {b0:.3f} + {bc:.2f}*core + {bf:.2f}*food + {bg:.3f}*gas (24m)")

    last_month = headline.index[-1]
    current_q = pd.Period(today, freq="Q")
    end_month = pd.Period(current_q.end_time, freq="M")
    missing = pd.period_range(last_month + 1, end_month, freq="M")

    # gasoline estimates reach one month past the last month with weekly data
    last_gas_m = gas_nsa_m.dropna().index[-1]
    gas_reach = last_gas_m + 1
    gas_levels = _gas_model(gas_nsa_m, oil_m, [m for m in missing if m <= gas_reach], log=log)
    gas_levels_mm = _mm(gas_levels)

    core_hat = float(core_mm.dropna().tail(12).mean())
    food_hat = float(food_mm.dropna().tail(12).mean())
    headline_ma = float(headline_mm.dropna().tail(12).mean())

    idx = headline.copy()
    details = []
    for m in missing:
        if m <= gas_reach:
            sf = _seasonal_factor(gas_nsa_mm, gascpi_mm, m)
            gas_hat = float(gas_levels_mm.loc[m]) - sf
            mm_hat = b0 + bc * core_hat + bf * food_hat + bg * gas_hat
            src = "components"
        else:
            gas_hat, mm_hat, src = np.nan, headline_ma, "headline-12mMA"
        idx.loc[m] = idx.loc[m - 1] * (1 + mm_hat / 100)
        details.append({"month": str(m), "headline_mm_pct": round(mm_hat, 3),
                        "gas_mm_sa_pct": None if np.isnan(gas_hat) else round(gas_hat, 2),
                        "source": src})
        log(f"CPI nowcast {m}: m/m {mm_hat:+.2f}% ({src})")

    yoy_m = (idx / idx.shift(12) - 1) * 100
    yoy_q = yoy_m.groupby(yoy_m.index.asfreq("Q")).mean().dropna()
    yoy_q.name = "cpi_yoy"
    # quarterly average index level (>=2 months required; the Oct-2025
    # shutdown gap leaves 4Q25 as a 2-month average)
    index_q = idx.groupby(idx.index.asfreq("Q")).mean()
    index_q = index_q[idx.groupby(idx.index.asfreq("Q")).count() >= 2]
    index_q.name = "cpi_index"

    first_estimate = (last_month + 1).asfreq("Q")
    yoy_m_nowcast = {str(m): float(yoy_m.loc[m]) for m in missing if m in yoy_m.index}
    return {"yoy_q": yoy_q, "index_q": index_q, "first_estimate": first_estimate,
            "monthly_nowcast": details, "last_cpi_month": str(last_month),
            "yoy_m_nowcast": yoy_m_nowcast,
            "params": {
                "gasoline levels model": gas_levels.attrs.get("params", "n/a"),
                "aggregation (24m OLS)": f"h = {b0:.3f} + {bc:.2f}·core + {bf:.2f}·food + {bg:.3f}·gas",
                "core m/m (12m MA)": f"{core_hat:.3f}%",
                "food m/m (12m MA)": f"{food_hat:.3f}%",
                "headline fallback m/m (12m MA)": f"{headline_ma:.3f}%",
            },
            "data_status": {
                "CPI (headline/core/food/gasoline)": str(last_month),
                "EIA weekly gasoline": str(raw[config.GAS_WEEKLY].index[-1].date()),
                "Brent daily": str(raw[config.CPI_BRENT].index[-1].date()),
            }}
