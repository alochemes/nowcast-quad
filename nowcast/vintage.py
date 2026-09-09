"""Rebuilding the model's inputs as they stood on a past date.

Shared by research/backtest_gdp_vintage.py (scores the GDP leg against the
advance release) and research/replay_vintage_quads.py (replays the whole quad
call week by week to backfill the chart-book history).

ALFRED serves most series' vintages directly. Where a series has no vintage
that early, the current series is truncated by its typical publication lag
instead — an approximation that affects the level of a few inputs but not the
ragged edge the Kalman filter cares about.
"""

from __future__ import annotations

import pandas as pd

from . import config, fetch

# publication lag in months, used only when no ALFRED vintage exists for a
# series at the as-of date. Weekly series (freq W in SERIES_META) are instead
# truncated by observation date.
FALLBACK_LAG = {
    "PAYEMS": 1, "UNRATE": 1, "JTSJOL": 2, "INDPRO": 1, "TCU": 1,
    "DGORDER": 1, "RSAFS": 1, "HOUST": 1, "PERMIT": 1, "DSPIC96": 1,
    "PCEC96": 1, "BOPTEXP": 2, "BOPTIMP": 2, "TTLCONS": 2,
    "GACDISA066MSFRBNY": 0, "GACDFSA066MSFRBPHI": 0,
    "WHLSLRIMSA": 2, "BUSINV": 2, "RETAILIMSA": 2, "HSN1F": 1,
    "CPIAUCSL": 1, "CPILFESL": 1, "PCEPI": 1, "PCEPILFE": 1, "PPIFIS": 1,
    "IR": 1, "IQ": 1,
    "TOTALSA": 1, "PSAVERT": 1, "CES0500000003": 1, "AWHAETP": 1,
    "UMCSENT": 0, "NEWORDER": 1, "AMTMNO": 2, "PNRESCONS": 2,
    "PRRESCONS": 2, "RSCCAS": 1, "BOPGSTB": 2, "BACTSAMFRBDAL": 0,
    "ICSA": 0, "CCSA": 0, "WEI": 0,
}


def raw_panel(asof: str, sids: list, log=print) -> tuple[dict, int]:
    """{series_id: series as of `asof`} plus a count of lag-fallback series."""
    raw, fallbacks = {}, 0
    for sid in sids:
        s = fetch.get_series_vintage(sid, asof, start=config.SAMPLE_START, log=log)
        if s is None:
            fallbacks += 1
            cur = fetch.get_series(sid, start=config.SAMPLE_START, log=log)
            if config.SERIES_META[sid][2] == "W":
                cutoff = pd.Timestamp(asof) - pd.Timedelta("7D")
            else:
                cutoff = (pd.Period(asof, freq="M") - FALLBACK_LAG[sid]).end_time
            s = cur[cur.index <= cutoff]
            log(f"  fallback truncation for {sid}")
        raw[sid] = s
    return raw, fallbacks


def get_series_vintage_gdp(asof: str, log=print) -> pd.Series | None:
    """Real GDP (GDPC1) as published on `asof` — i.e. without any revision or
    release that landed later."""
    return fetch.get_series_vintage(config.GDP_QUARTERLY_SERIES, asof,
                                    start=config.SAMPLE_START, log=log)


def gdpnow_asof(asof: str, log=print) -> tuple[pd.Period, float] | None:
    """Atlanta Fed GDPNow as it stood on `asof`: (target quarter, SAAR %).

    GDPNow is revised several times a quarter and each revision is its own
    ALFRED vintage, so this is the actual number that was on the screen that
    day — not a backfilled one.
    """
    try:
        s = fetch.get_series_vintage(config.BENCHMARK_GDPNOW, asof,
                                     start="2016-01-01", log=log)
    except Exception as e:  # noqa: BLE001 - the ensemble degrades to pure DFM
        log(f"GDPNow vintage unavailable at {asof}: {e}")
        return None
    if s is None or s.empty:
        return None
    return pd.Period(s.index[-1], freq="Q"), float(s.iloc[-1])
