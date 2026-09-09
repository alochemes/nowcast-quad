"""GDP nowcast: mixed-frequency dynamic factor model (statsmodels DynamicFactorMQ).

Monthly indicators (transformed to stationarity) + quarterly real GDP growth
(100*dlog). The Kalman filter handles ragged edges natively, so the panel is
passed with NaNs intact. The nowcast for any quarter without a released GDP
print is read off res.forecast(); implied levels then give YoY growth.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

from . import config, fetch


def _transform(s: pd.Series, how: str) -> pd.Series:
    if how == "chg":
        return s.diff()
    if how == "pch":
        return 100 * np.log(s).diff()
    if how == "lin":
        return s
    raise ValueError(how)


def panel_series(panel: str | list | None = None) -> list:
    if panel is None:
        panel = config.ACTIVE_PANEL
    return config.PANELS[panel] if isinstance(panel, str) else list(panel)


def build_panel(log=print, raw: dict | None = None, gdp_level_raw=None,
                panel: str | list | None = None):
    """Return (monthly_panel, gdp_growth_q, gdp_level_q) ready for the DFM.

    raw / gdp_level_raw: inject pre-fetched (e.g. vintage) data; fetched live
    when omitted. panel: PANELS name or explicit series list.
    """
    sids = panel_series(panel)
    if raw is None:
        raw = fetch.get_many(sids, start=config.SAMPLE_START, log=log)
    monthly = {}
    for sid in sids:
        how, _block, freq = config.SERIES_META[sid]
        s = raw[sid].copy()
        if freq == "W":
            # weekly -> monthly means; partial months kept (that is the point
            # of weekly data: the current month has a value immediately)
            s = s.groupby(pd.PeriodIndex(s.index, freq="M")).mean()
        else:
            s.index = pd.PeriodIndex(s.index, freq="M")
        # gapless calendar index: missing months (e.g. shutdown gaps) must be
        # NaN so diff/pct_change stay month-over-month
        s = s.reindex(pd.period_range(s.index[0], s.index[-1], freq="M"))
        t = _transform(s, how)
        # FRED-MD/Fulton outlier rule: observations further than k*IQR from
        # the median become missing — the Kalman filter handles NaN natively,
        # and removal (unlike clipping) keeps the EM estimator stable
        med = t.median()
        iqr = t.quantile(0.75) - t.quantile(0.25)
        if np.isfinite(iqr) and iqr > 0:
            t = t.where((t - med).abs() <= config.OUTLIER_IQR_K * iqr)
        # degenerate columns (near-empty or constant vintage series) break the
        # EM estimator — drop them rather than fail the whole fit
        if t.count() < 36 or not np.isfinite(t.std()) or t.std() == 0:
            log(f"dropping degenerate panel series {sid} "
                f"({t.count()} valid obs)")
            continue
        monthly[sid] = t
    panel = pd.DataFrame(monthly)
    panel.attrs["data_status"] = {sid: str(s.last_valid_index())
                                  for sid, s in monthly.items()}

    if gdp_level_raw is None:
        gdp_level_raw = fetch.get_series(config.GDP_QUARTERLY_SERIES,
                                         start=config.SAMPLE_START, log=log)
    gdp_level = gdp_level_raw.copy()
    gdp_level.index = pd.PeriodIndex(gdp_level.index, freq="Q")
    gdp_growth = 100 * np.log(gdp_level).diff()
    gdp_growth.name = "GDP"
    return panel.dropna(how="all"), gdp_growth.dropna(), gdp_level


def fit_dfm(panel: pd.DataFrame, gdp_growth: pd.Series, log=print):
    """Fit the mixed-frequency DFM with a numerical-stability retry ladder:
    Global VAR(2) first, then Global AR(1) (the EM state recursion overflows
    on some data vintages under the VAR(2) spec)."""
    factors = {}
    for sid in panel.columns:
        block = config.SERIES_META[sid][1]
        factors[sid] = ["Global"] + ([block] if block else [])
    factors["GDP"] = ["Global", "Real"]
    # every surviving block needs an explicit order (statsmodels'
    # default-order path calls the removed pd.Series.append on pandas>=2).
    # sorted(), not the raw set: the key order of factor_orders sets the
    # factor ordering inside statsmodels, and set order for strings is
    # hash-randomized per process. Unsorted, the same panel gave a different
    # EM path (and sometimes a diverging one) in every new process —
    # llf -14808/-14886/overflow-crash across four runs of identical data on
    # 2026-07-29, and two same-day scheduled runs on 2026-07-27 that
    # disagreed on the nowcast. Sorted is bitwise reproducible and ~3x faster.
    blocks = sorted({b for f in factors.values() for b in f})
    log(f"fitting DFM: {panel.shape[1]} monthly series, "
        f"{panel.index[0]}..{panel.index[-1]}")
    last_err = None
    for global_order, idio_ar1 in ((2, True), (1, True), (1, False)):
        try:
            model = DynamicFactorMQ(
                panel,
                endog_quarterly=gdp_growth,
                factors=factors,
                factor_orders={b: (global_order if b == "Global" else 1)
                               for b in blocks},
                idiosyncratic_ar1=idio_ar1,
                standardize=True,
            )
            res = model.fit(disp=30, maxiter=500)
            if not np.isfinite(res.llf) or res.llf < -1e6:
                raise RuntimeError(f"degenerate fit (llf={res.llf:.3g})")
            spec = f"Global({global_order}){'+idioAR1' if idio_ar1 else ''}"
            res._nowcast_spec = spec
            if (global_order, idio_ar1) != (2, True):
                log(f"DFM fell back to {spec}")
            return res
        except Exception as e:  # noqa: BLE001 - try the next rung
            last_err = e
            log(f"DFM Global({global_order}){'+idioAR1' if idio_ar1 else ''} failed: {e}")
    raise RuntimeError(f"all DFM specs failed: {last_err}")


def derive_nowcast(panel, gdp_growth, gdp_level, target_q: pd.Period | None = None,
                   log=print) -> dict:
    """Fit the DFM and derive q/q + YoY nowcasts for quarters through target_q.

    Returns dict with:
      yoy: quarterly PeriodIndex Series of real GDP YoY % (actuals + nowcasts)
      qq_saar: dict of {Period: nowcast q/q SAAR %} for nowcast quarters
      first_estimate: first Period that is a nowcast rather than actuals
    """
    res = fit_dfm(panel, gdp_growth, log=log)

    last_actual_q = gdp_level.index[-1]
    last_month = panel.index[-1]
    current_q = pd.Period(last_month, freq="Q")
    if target_q is None:
        # nowcast through the quarter containing the latest monthly data, plus one
        target_q = current_q + 1
    months_ahead = (target_q.end_time.to_period("M") - last_month).n
    fc = res.forecast(steps=max(months_ahead, 1))["GDP"].dropna()
    # quarterly variables are reported at monthly rows; quarter estimate = last month
    fc_q = fc.groupby(fc.index.asfreq("Q")).last()
    # in-sample smoothed estimate covers quarters already inside the panel range
    # (e.g. a finished-but-unreleased quarter); forecast covers the rest
    pred = res.get_prediction(start=panel.index[-15], end=last_month).predicted_mean["GDP"].dropna()
    pred = pred.groupby(pred.index.asfreq("Q")).last()

    levels = gdp_level.copy()
    qq_saar = {}
    first_estimate = last_actual_q + 1
    q = first_estimate
    while q <= target_q:
        if q in fc_q.index:
            dlog = fc_q.loc[q]
        elif q in pred.index:
            dlog = pred.loc[q]
        else:
            raise RuntimeError(f"no DFM estimate for {q}")
        prev = levels.loc[q - 1]
        levels.loc[q] = prev * float(np.exp(dlog / 100))
        qq_saar[q] = float((np.exp(dlog / 100) ** 4 - 1) * 100)
        q += 1

    yoy = (levels / levels.shift(4) - 1) * 100
    yoy.name = "gdp_yoy"
    return {"yoy": yoy.dropna(), "qq_saar": qq_saar, "first_estimate": first_estimate,
            "levels": levels,
            "data_status": panel.attrs.get("data_status", {}),
            "last_actual_quarter": str(last_actual_q),
            "spec": getattr(res, "_nowcast_spec", "")}


def nowcast_gdp_yoy(log=print) -> dict:
    """Live nowcast: fetch latest data, fit, derive (see derive_nowcast)."""
    panel, gdp_growth, gdp_level = build_panel(log=log)
    return derive_nowcast(panel, gdp_growth, gdp_level, log=log)
