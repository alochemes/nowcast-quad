"""End-to-end smoke test: real pipeline run (network or cache), sane outputs."""

import pandas as pd
import pytest

from nowcast import pipeline


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("output")
    return pipeline.run(output_dir=out, log=lambda m: None), out


def test_outputs_exist(result):
    _res, out = result
    for name in ("quad_map.png", "report.html", "nowcast.csv"):
        f = out / name
        assert f.exists() and f.stat().st_size > 0


def test_table_sane(result):
    res, _out = result
    t = res["table"]
    assert len(t) >= 8
    assert t["gdp_yoy"].between(-6, 9).all(), t["gdp_yoy"]
    assert t["cpi_yoy"].between(-3, 11).all(), t["cpi_yoy"]
    assert set(t["quad"]).issubset({1, 2, 3, 4})
    assert t["is_estimate"].any() and (~t["is_estimate"]).any()
    # estimates form a contiguous tail
    flags = t["is_estimate"].tolist()
    assert flags == sorted(flags)


def test_current_quarter_covered(result):
    res, _out = result
    t = res["table"]
    assert t.index[-1] >= pd.Period(pd.Timestamp.now(), freq="Q")


def test_quads_match_deltas(result):
    res, _out = result
    t = res["table"]
    for _, r in t.iterrows():
        expect = {(True, False): 1, (True, True): 2,
                  (False, True): 3, (False, False): 4}[
            (r["d_gdp_bps"] > 0, r["d_cpi_bps"] > 0)]
        assert r["quad"] == expect
