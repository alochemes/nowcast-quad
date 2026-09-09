"""Data fetching: FRED API (primary) with DBnomics fallback and local caching.

Network resilience notes (this machine):
- Norton AV intercepts TLS; certifi alone fails. We build a combined CA bundle
  (certifi + the cert file named by NODE_EXTRA_CA_CERTS) on first SSL failure.
- fred.stlouisfed.org (the website, incl. fredgraph.csv) is unreachable from
  this machine; api.stlouisfed.org works and requires an API key.
- Every successful fetch is cached to data_cache/<id>.csv so an autonomous run
  degrades to stale-but-usable data when the network is down.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data_cache"
PRIVATE_CONFIG = PROJECT_ROOT / "private" / "config.yaml"
CACHE_MAX_AGE_HOURS = 6  # reuse cache newer than this instead of refetching

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
DBNOMICS_URL = "https://api.db.nomics.world/v22/series/{provider}/{dataset}/{series}"

# FRED id -> (provider, dataset, series) on DBnomics, for keyless fallback.
DBNOMICS_MAP = {
    "CPIAUCSL": ("BLS", "cu", "CUSR0000SA0"),
    "CPILFESL": ("BLS", "cu", "CUSR0000SA0L1E"),
    "CPIUFDSL": ("BLS", "cu", "CUSR0000SAF1"),
    "CUSR0000SETB01": ("BLS", "cu", "CUSR0000SETB01"),
    "PAYEMS": ("BLS", "ce", "CES0000000001"),
    "UNRATE": ("BLS", "ln", "LNS14000000"),
    "AWHMAN": ("BLS", "ce", "CES3000000007"),
}


def _load_fred_key() -> str | None:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    if PRIVATE_CONFIG.exists():
        import yaml

        with open(PRIVATE_CONFIG) as f:
            cfg = yaml.safe_load(f)
        return (cfg.get("api_key") or {}).get("FRED")
    return None


def _ca_bundle() -> str | bool:
    """Return verify= argument for requests, building a combined bundle if needed."""
    combined = CACHE_DIR / "cacert_combined.pem"
    if combined.exists():
        return str(combined)
    return True


def _build_ca_bundle() -> str | bool:
    """Append the corporate/AV MITM cert (NODE_EXTRA_CA_CERTS) to certifi's bundle."""
    extra = os.environ.get("NODE_EXTRA_CA_CERTS")
    if not extra or not Path(extra).exists():
        return True
    import certifi

    CACHE_DIR.mkdir(exist_ok=True)
    combined = CACHE_DIR / "cacert_combined.pem"
    shutil.copyfile(certifi.where(), combined)
    with open(extra, "rb") as f:
        pem = f.read()
    with open(combined, "ab") as f:
        f.write(b"\n" + pem)
    return str(combined)


RETRY_STATUS = (429, 500, 502, 503, 504)
RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds, multiplied by the attempt number


def _http_get(url: str, params: dict | None = None, timeout: int = 60,
              retries: int = RETRIES) -> requests.Response:
    """GET with a retry on transient server errors.

    api.stlouisfed.org intermittently answers 500/502 under load — two dates of
    a vintage replay were lost to single 5xx responses on 2026-08-03, and the
    live run the same morning fell back to stale cache for two series for the
    same reason. 4xx is never retried: get_series_vintage relies on a 400 to
    mean "no vintage exists that early".
    """
    verify = _ca_bundle()
    last = None
    for attempt in range(1, retries + 1):
        try:
            try:
                r = requests.get(url, params=params, timeout=timeout, verify=verify,
                                 headers={"User-Agent": "nowcast-quad/0.1"})
            except requests.exceptions.SSLError:
                verify = _build_ca_bundle()
                r = requests.get(url, params=params, timeout=timeout, verify=verify,
                                 headers={"User-Agent": "nowcast-quad/0.1"})
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            last = e
            status = e.response.status_code if e.response is not None else None
            if status not in RETRY_STATUS or attempt == retries:
                raise
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last = e
            if attempt == retries:
                raise
        time.sleep(RETRY_BACKOFF * attempt)
    raise last  # unreachable; keeps the type checker honest


def _cache_path(series_id: str, start: str) -> Path:
    # keyed by start date: a series cached from 2024 must not satisfy a
    # request for history from 2015
    return CACHE_DIR / f"{series_id}__{start}.csv"


def _read_cache(series_id: str, start: str, max_age_hours: float | None = None) -> pd.Series | None:
    path = _cache_path(series_id, start)
    if not path.exists():
        return None
    if max_age_hours is not None:
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h > max_age_hours:
            return None
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    s = df["value"]
    s.name = series_id
    return s


def _write_cache(series_id: str, start: str, s: pd.Series) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    s.rename("value").rename_axis("date").to_csv(_cache_path(series_id, start))


def _fetch_fred(series_id: str, start: str) -> pd.Series:
    key = _load_fred_key()
    if not key:
        raise RuntimeError("no FRED API key (env FRED_API_KEY or private/config.yaml)")
    r = _http_get(FRED_API_URL, params={
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start,
    })
    obs = r.json()["observations"]
    idx, vals = [], []
    for o in obs:
        if o["value"] in (".", ""):
            continue
        idx.append(pd.Timestamp(o["date"]))
        vals.append(float(o["value"]))
    s = pd.Series(vals, index=pd.DatetimeIndex(idx, name="date"), name=series_id)
    if s.empty:
        raise RuntimeError(f"FRED returned no observations for {series_id}")
    return s


def _fetch_dbnomics(series_id: str, start: str) -> pd.Series:
    if series_id not in DBNOMICS_MAP:
        raise RuntimeError(f"no DBnomics mapping for {series_id}")
    provider, dataset, series = DBNOMICS_MAP[series_id]
    r = _http_get(DBNOMICS_URL.format(provider=provider, dataset=dataset, series=series),
                  params={"observations": "1"})
    docs = r.json()["series"]["docs"][0]
    periods, values = docs["period_start_day"], docs["value"]
    idx, vals = [], []
    for p, v in zip(periods, values):
        if v is None or v == "NA":
            continue
        ts = pd.Timestamp(p)
        if ts < pd.Timestamp(start):
            continue
        idx.append(ts)
        vals.append(float(v))
    s = pd.Series(vals, index=pd.DatetimeIndex(idx, name="date"), name=series_id)
    if s.empty:
        raise RuntimeError(f"DBnomics returned no observations for {series_id}")
    return s


def get_series(series_id: str, start: str = "1990-01-01", log=print) -> pd.Series:
    """Fetch one series: fresh cache -> FRED -> DBnomics -> stale cache."""
    cached = _read_cache(series_id, start, max_age_hours=CACHE_MAX_AGE_HOURS)
    if cached is not None:
        return cached
    errors = []
    for name, fn in (("FRED", _fetch_fred), ("DBnomics", _fetch_dbnomics)):
        try:
            s = fn(series_id, start)
            _write_cache(series_id, start, s)
            return s
        except Exception as e:  # noqa: BLE001 - fall through the source chain
            errors.append(f"{name}: {e}")
    stale = _read_cache(series_id, start, max_age_hours=None)
    if stale is not None:
        log(f"WARNING {series_id}: all sources failed ({'; '.join(errors)}); using stale cache")
        return stale
    raise RuntimeError(f"{series_id}: all sources failed and no cache: {'; '.join(errors)}")


def get_many(series_ids: list[str], start: str = "1990-01-01", log=print) -> dict[str, pd.Series]:
    out = {}
    for sid in series_ids:
        out[sid] = get_series(sid, start=start, log=log)
    return out


# ---------------------------------------------------------------------------
# ALFRED vintages (real-time historical data, for backtesting)

VINTAGE_DIR = CACHE_DIR / "vintages"


def get_series_vintage(series_id: str, asof: str, start: str = "1990-01-01",
                       log=print) -> pd.Series | None:
    """Series exactly as it appeared on `asof` (YYYY-MM-DD), via ALFRED
    realtime windows. Returns None when no vintage exists that early.
    Vintages are immutable, so the cache never expires."""
    path = VINTAGE_DIR / f"{series_id}_{asof}.csv"
    if path.exists():
        if path.stat().st_size < 5:  # cached "no vintage" marker
            return None
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
        s = df["value"]
        s.name = series_id
        return s
    key = _load_fred_key()
    if not key:
        raise RuntimeError("vintage fetch requires a FRED API key")
    r = None
    try:
        r = _http_get(FRED_API_URL, params={
            "series_id": series_id, "api_key": key, "file_type": "json",
            "observation_start": start,
            "realtime_start": asof, "realtime_end": asof,
        })
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 400:
            VINTAGE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text("")  # remember the miss
            log(f"vintage {series_id}@{asof}: none available")
            return None
        raise
    obs = r.json()["observations"]
    idx, vals = [], []
    for o in obs:
        if o["value"] in (".", ""):
            continue
        idx.append(pd.Timestamp(o["date"]))
        vals.append(float(o["value"]))
    s = pd.Series(vals, index=pd.DatetimeIndex(idx, name="date"), name=series_id)
    VINTAGE_DIR.mkdir(parents=True, exist_ok=True)
    s.rename("value").rename_axis("date").to_csv(path)
    return s if not s.empty else None


def get_vintage_dates(series_id: str, log=print) -> list[pd.Timestamp]:
    """All ALFRED vintage dates for a series (cached daily)."""
    path = VINTAGE_DIR / f"{series_id}_vintagedates.csv"
    if path.exists() and (time.time() - path.stat().st_mtime) / 3600 < 24:
        return list(pd.read_csv(path, parse_dates=["date"])["date"])
    key = _load_fred_key()
    r = _http_get("https://api.stlouisfed.org/fred/series/vintagedates",
                  params={"series_id": series_id, "api_key": key,
                          "file_type": "json", "limit": 10000})
    dates = [pd.Timestamp(d) for d in r.json()["vintage_dates"]]
    VINTAGE_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": dates}).to_csv(path, index=False)
    return dates
