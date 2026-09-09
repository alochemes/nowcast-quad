"""Run history: what the model said about each quarter, at each point in time.

Every run appends its whole quad table (not just the current quarter) to
output/history/quad_history.csv in long form, one row per (as-of date,
quarter). That is the raw material for the per-quarter chart book: reading a
single quarter's rows in as-of order shows how its call evolved as data
arrived, and when it stopped being an estimate.

Rows carry a `source` so a backfill from ALFRED vintages
(research/replay_vintage_quads.py, source="replay") and the live weekly runs
(source="live") can coexist in one file. Writes are idempotent per
(asof, source): re-running the same as-of date replaces its rows rather than
duplicating them.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

HISTORY_NAME = "quad_history.csv"
COLUMNS = ["asof", "source", "quarter", "gdp_yoy", "cpi_yoy", "d_gdp_bps",
           "d_cpi_bps", "quad", "is_estimate"]


def history_path(output_dir) -> Path:
    return Path(output_dir) / "history" / HISTORY_NAME


def to_rows(table: pd.DataFrame, asof, source: str = "live") -> pd.DataFrame:
    """quad_table() output -> long-form history rows."""
    asof = pd.Timestamp(asof).normalize()
    out = pd.DataFrame({
        "asof": asof,
        "source": source,
        "quarter": [str(p) for p in table.index],
        "gdp_yoy": table["gdp_yoy"].round(4).to_numpy(),
        "cpi_yoy": table["cpi_yoy"].round(4).to_numpy(),
        "d_gdp_bps": table["d_gdp_bps"].to_numpy(),
        "d_cpi_bps": table["d_cpi_bps"].to_numpy(),
        "quad": table["quad"].astype(int).to_numpy(),
        "is_estimate": table["is_estimate"].astype(bool).to_numpy(),
    })
    return out[COLUMNS]


def append_run(table: pd.DataFrame, asof, output_dir, source: str = "live",
               log=print) -> Path | None:
    """Append one run's table. Best-effort — never fails the run."""
    try:
        path = history_path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        new = to_rows(table, asof, source=source)
        if path.exists():
            old = pd.read_csv(path, parse_dates=["asof"])
            stamp = new["asof"].iloc[0]
            keep = old[~((old["asof"] == stamp) & (old["source"] == source))]
            if not keep.empty:  # concat with an empty frame muddies dtypes
                new = pd.concat([keep, new], ignore_index=True)
        new = new.sort_values(["asof", "source", "quarter"])
        new.to_csv(path, index=False)
        return path
    except Exception as e:  # noqa: BLE001 - history must never break a run
        log(f"history: append skipped: {e}")
        return None


def load(output_dir, source: str | None = None) -> pd.DataFrame:
    """Load the history, quarter as a quarterly PeriodIndex column.

    When both sources cover the same as-of date the live row wins (it is what
    the model actually printed that day; the replay only reconstructs it).
    """
    path = history_path(output_dir)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, parse_dates=["asof"])
    if source:
        df = df[df["source"] == source]
    if df.empty:
        return df
    df["quarter"] = pd.PeriodIndex(df["quarter"], freq="Q")
    df["is_estimate"] = df["is_estimate"].astype(bool)
    df["quad"] = df["quad"].astype(int)
    # live beats replay on a shared as-of date
    df["_pref"] = (df["source"] == "live").astype(int)
    df = (df.sort_values(["asof", "quarter", "_pref"])
            .drop_duplicates(["asof", "quarter"], keep="last")
            .drop(columns="_pref"))
    return df.sort_values(["quarter", "asof"]).reset_index(drop=True)


def live_quarters(df: pd.DataFrame) -> list:
    """Quarters the history actually watched being called — those with at least
    one estimate reading in it.

    A quarter that was already final before the history begins contributes only
    a flat line of settled values, which says nothing about how the model
    behaved; the chart book is about calls that were live at the time.
    """
    if df.empty:
        return []
    return sorted(df.loc[df["is_estimate"], "quarter"].unique())


def quarter_track(df: pd.DataFrame, quarter: pd.Period,
                  tail_days: int = 45) -> pd.DataFrame:
    """One quarter's rows over as-of time, trimmed to the period when the call
    was live: from its first appearance to `tail_days` past the as-of date it
    first printed as an actual. Beyond that it is a frozen historical value and
    adds nothing but a flat line."""
    g = df[df["quarter"] == quarter].sort_values("asof")
    if g.empty:
        return g
    actual = g[~g["is_estimate"]]
    if not actual.empty:
        cutoff = actual["asof"].iloc[0] + pd.Timedelta(tail_days, unit="D")
        g = g[g["asof"] <= cutoff]
    return g


def settled_quad(df: pd.DataFrame, quarter: pd.Period) -> int | None:
    """The quad the quarter ended up in once it stopped being an estimate
    (None while it is still a live estimate)."""
    g = df[(df["quarter"] == quarter) & (~df["is_estimate"])].sort_values("asof")
    return None if g.empty else int(g["quad"].iloc[-1])


def path_at(df: pd.DataFrame, asof) -> dict[str, int]:
    """{quarter: quad} exactly as one as-of run saw it — used by the notifier
    to compare like quarter with like quarter across runs."""
    asof = pd.Timestamp(asof).normalize()
    g = df[df["asof"] == asof]
    return {str(q): int(v) for q, v in zip(g["quarter"], g["quad"])}
