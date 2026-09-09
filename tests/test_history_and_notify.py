"""Run history round-trip, and the notifier's like-for-like quarter comparison.

The notifier tests pin the 2026-08-03 regression: the nowcast quarter rolled
from 2Q26 to 3Q26, the old code compared 2Q26's quad against 3Q26's, and a
routine roll went out as a QUAD CHANGE alert.
"""

import pandas as pd
import pytest

from nowcast import history, notify_remote as nr, quads


def _table(quads_by_q: dict, estimate_from: str) -> pd.DataFrame:
    idx = pd.PeriodIndex(list(quads_by_q), freq="Q")
    df = pd.DataFrame(index=idx)
    df.index.name = "quarter"
    df["gdp_yoy"] = [2.0 + 0.1 * i for i in range(len(idx))]
    df["cpi_yoy"] = [3.0 + 0.1 * i for i in range(len(idx))]
    df["d_gdp_bps"] = 10.0
    df["d_cpi_bps"] = -10.0
    df["quad"] = list(quads_by_q.values())
    df["quad_name"] = df["quad"].map(quads.QUAD_NAMES)
    df["is_estimate"] = idx >= pd.Period(estimate_from, freq="Q")
    return df


# --------------------------------------------------------------- history


def test_history_roundtrip(tmp_path):
    t = _table({"2026Q1": 2, "2026Q2": 3, "2026Q3": 1}, "2026Q3")
    history.append_run(t, "2026-08-03", tmp_path, source="live")
    h = history.load(tmp_path)
    assert len(h) == 3
    assert set(h["quarter"].astype(str)) == {"2026Q1", "2026Q2", "2026Q3"}
    assert h[h["quarter"] == pd.Period("2026Q3", "Q")]["quad"].iloc[0] == 1


def test_history_append_is_idempotent(tmp_path):
    t = _table({"2026Q2": 3, "2026Q3": 1}, "2026Q3")
    for _ in range(3):
        history.append_run(t, "2026-08-03", tmp_path, source="live")
    assert len(history.load(tmp_path)) == 2


def test_history_live_beats_replay_on_same_date(tmp_path):
    history.append_run(_table({"2026Q3": 4}, "2026Q3"), "2026-08-03", tmp_path,
                       source="replay")
    history.append_run(_table({"2026Q3": 1}, "2026Q3"), "2026-08-03", tmp_path,
                       source="live")
    h = history.load(tmp_path)
    assert len(h) == 1 and h["quad"].iloc[0] == 1


def test_quarter_track_stops_after_the_call_closes(tmp_path):
    q = pd.Period("2026Q2", freq="Q")
    for i, (d, est) in enumerate([("2026-06-01", True), ("2026-07-06", True),
                                  ("2026-08-03", False), ("2027-01-04", False)]):
        history.append_run(_table({"2026Q2": 3}, "2026Q3" if est else "2026Q4"),
                           d, tmp_path, source="live")
    h = history.load(tmp_path)
    track = history.quarter_track(h, q)
    # the January row is long past the close and would only flatten the panel
    assert track["asof"].max() < pd.Timestamp("2026-10-01")
    assert history.settled_quad(h, q) == 3


# --------------------------------------------------------------- notifier

PREV_ROLL = {
    "timestamp": "2026-07-30 00:04", "quarter": "2Q26E", "current_q": "2026Q2",
    "quad": 3, "quad_name": "Stagflation", "ensemble_q": "2026Q2",
    "path": {
        "2026Q2": {"quad": 3, "quad_name": "Stagflation", "gdp_yoy": 2.26,
                   "cpi_yoy": 3.80, "is_estimate": True},
        "2026Q3": {"quad": 1, "quad_name": "Goldilocks", "gdp_yoy": 2.20,
                   "cpi_yoy": 3.25, "is_estimate": True}},
}
NOW = {
    "quarter": "3Q26E", "current_q": "2026Q3", "quad": 1,
    "quad_name": "Goldilocks", "gdp_yoy": 2.17, "cpi_yoy": 3.20,
    "ensemble_q": "2026Q3",
    "path": {
        "2026Q2": {"quad": 3, "quad_name": "Stagflation", "gdp_yoy": 2.10,
                   "cpi_yoy": 3.80, "is_estimate": False},
        "2026Q3": {"quad": 1, "quad_name": "Goldilocks", "gdp_yoy": 2.17,
                   "cpi_yoy": 3.20, "is_estimate": True}},
}


def test_quarter_roll_is_not_a_quad_change():
    """The 2026-08-03 regression: 3Q26 held Quad 1 across the roll."""
    text, kind = nr.build_commentary(NOW, PREV_ROLL)
    assert kind == "none"
    assert "QUAD CHANGE" not in text
    assert "rolled" in text
    assert "now actual" in text  # 2Q26 closing is still reported


def test_real_quad_change_still_fires():
    prev = {**PREV_ROLL, "current_q": "2026Q3", "quarter": "3Q26E",
            "path": {"2026Q3": {"quad": 2, "quad_name": "Reflation",
                                "gdp_yoy": 2.30, "cpi_yoy": 3.35,
                                "is_estimate": True}}}
    text, kind = nr.build_commentary(NOW, prev)
    assert kind == "quad_change"
    assert "QUAD CHANGE for 3Q26E" in text


def test_legacy_state_file_without_a_path_still_compares():
    """State files written before the quad path was persisted must not make the
    first run after the upgrade look like a roll."""
    legacy = {"timestamp": "2026-08-03 11:03", "quarter": "3Q26E", "quad": 1,
              "quad_name": "Goldilocks", "gdp_yoy": 2.17, "cpi_yoy": 3.20}
    _text, kind = nr.build_commentary(NOW, legacy)
    assert kind == "none"


def test_legacy_fallback_ignored_when_the_quarter_differs():
    """The fallback must never revive the cross-quarter comparison it replaced."""
    legacy = {"timestamp": "2026-07-30 00:04", "quarter": "2Q26E", "quad": 3,
              "quad_name": "Stagflation", "gdp_yoy": 2.26, "cpi_yoy": 3.80}
    text, kind = nr.build_commentary(NOW, legacy)
    assert kind == "roll"
    assert "QUAD CHANGE" not in text


def test_quarter_new_in_view_reads_as_a_roll():
    prev = {**PREV_ROLL, "path": {"2026Q2": PREV_ROLL["path"]["2026Q2"]}}
    _text, kind = nr.build_commentary(NOW, prev)
    assert kind == "roll"


def test_levels_are_never_compared_across_a_roll():
    text, _kind = nr.build_commentary(NOW, PREV_ROLL)
    # 3Q26 vs 3Q26 (2.20 -> 2.17), never 2Q26's 2.26 against 3Q26's 2.17
    assert "3Q26E GDP YoY: 2.20% → 2.17%" in text
    assert "2.26" not in text


@pytest.mark.parametrize("kind,expect", [
    ("none", "Nowcast Quad: 3Q26E Quad 1 Goldilocks"),
    ("quad_change", "Nowcast Quad CHANGE: 3Q26E Quad 2 -> 1 Goldilocks"),
    ("roll", "Nowcast Quad: 3Q26E Quad 1 Goldilocks (new quarter)"),
])
def test_subject_is_ascii_and_well_formed(kind, expect):
    subject = nr.build_subject({**NOW, "prev_quad": 2}, kind,
                               when=pd.Timestamp("2026-08-03"))
    assert subject.isascii(), subject
    assert subject.startswith(expect), subject
    assert subject.endswith("Aug 3")


def test_quad_path_shape():
    p = nr.quad_path(_table({"2026Q2": 3, "2026Q3": 1}, "2026Q3"))
    assert p["2026Q3"]["quad"] == 1
    assert p["2026Q3"]["is_estimate"] is True
    assert p["2026Q2"]["is_estimate"] is False
