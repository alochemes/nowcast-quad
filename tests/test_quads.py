import pandas as pd
import pytest

from nowcast import baseeffects, quads


def test_quad_truth_table():
    assert quads.assign_quad(+10, -10) == 1
    assert quads.assign_quad(+10, +10) == 2
    assert quads.assign_quad(-10, +10) == 3
    assert quads.assign_quad(-10, -10) == 4


def test_zero_delta_counts_as_deceleration():
    assert quads.assign_quad(0, 0) == 4
    assert quads.assign_quad(0, 5) == 3
    assert quads.assign_quad(5, 0) == 1


def test_quad_table_deltas_and_flags():
    q = pd.period_range("2023Q1", "2024Q4", freq="Q")
    gdp = pd.Series([2.0, 2.5, 2.0, 2.2, 2.4, 2.1, 2.3, 2.0], index=q)
    cpi = pd.Series([5.0, 4.0, 3.5, 3.2, 3.4, 3.1, 3.3, 3.0], index=q)
    t = quads.quad_table(gdp, cpi, estimate_from=pd.Period("2024Q3", freq="Q"))
    assert t.loc[pd.Period("2023Q2", freq="Q"), "d_gdp_bps"] == 50.0
    assert t.loc[pd.Period("2023Q2", freq="Q"), "d_cpi_bps"] == -100.0
    assert t.loc[pd.Period("2023Q2", freq="Q"), "quad"] == 1
    assert not t.loc[pd.Period("2024Q2", freq="Q"), "is_estimate"]
    assert t.loc[pd.Period("2024Q3", freq="Q"), "is_estimate"]
    assert t.loc[pd.Period("2024Q4", freq="Q"), "is_estimate"]


def test_quarter_label():
    assert quads.quarter_label(pd.Period("2026Q2", freq="Q")) == "2Q26"
    assert quads.quarter_label(pd.Period("2026Q2", freq="Q"), True) == "2Q26E"


def test_base_effect_direction():
    # steepening comps must push the projected YoY rate down (and vice versa)
    q = pd.period_range("2020Q1", "2022Q4", freq="Q")
    # acceleration sits 4-8 quarters back so the projection's comps steepen
    rising = pd.Series([1, 1, 1, 1, 1, 1, 1, 2, 3, 4, 4, 4.0], index=q)
    out = baseeffects.project_out_quarters(rising, n=1, k=0.5)
    t = out.index[-1]
    comp_t = (out.loc[t - 4] + out.loc[t - 8]) / 2
    comp_prev = (out.loc[t - 5] + out.loc[t - 9]) / 2
    assert comp_t > comp_prev  # comps steepen...
    assert out.iloc[-1] < rising.iloc[-1]  # ...so projection decelerates


def test_base_effect_length():
    q = pd.period_range("2020Q1", "2022Q4", freq="Q")
    s = pd.Series(range(12), index=q, dtype=float)
    out = baseeffects.project_out_quarters(s, n=3)
    assert len(out) == 15
    assert out.index[-1] == pd.Period("2023Q3", freq="Q")
