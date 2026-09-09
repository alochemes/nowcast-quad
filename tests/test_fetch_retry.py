"""Transient-error retry in the HTTP layer.

api.stlouisfed.org intermittently returns 500/502 under load. Two dates of the
2026-08-03 vintage replay were lost to single 5xx responses, and the live run
that morning fell back to stale cache for two series for the same reason.
"""

from unittest import mock

import pytest
import requests

from nowcast import fetch


class _Resp:
    def __init__(self, code):
        self.status_code = code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}", response=self)


def _responder(codes):
    """Returns a requests.get stand-in yielding `codes` in order, and the log."""
    seen = []

    def get(*_a, **_k):
        code = codes[min(len(seen), len(codes) - 1)]
        seen.append(code)
        return _Resp(code)

    return get, seen


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_transient_errors_are_retried_then_succeed(code):
    get, seen = _responder([code, code, 200])
    with mock.patch("requests.get", get), mock.patch("time.sleep"):
        assert fetch._http_get("http://x").status_code == 200
    assert len(seen) == 3


def test_gives_up_after_the_retry_budget():
    get, seen = _responder([502])
    with mock.patch("requests.get", get), mock.patch("time.sleep"):
        with pytest.raises(requests.exceptions.HTTPError):
            fetch._http_get("http://x")
    assert len(seen) == fetch.RETRIES


def test_client_errors_are_not_retried():
    """get_series_vintage reads a 400 as 'no vintage exists that early', so it
    must arrive immediately and unaltered."""
    get, seen = _responder([400])
    with mock.patch("requests.get", get), mock.patch("time.sleep"):
        with pytest.raises(requests.exceptions.HTTPError) as e:
            fetch._http_get("http://x")
    assert len(seen) == 1
    assert e.value.response.status_code == 400


def test_connection_errors_are_retried():
    seen = []

    def get(*_a, **_k):
        seen.append(1)
        if len(seen) < 3:
            raise requests.exceptions.ConnectionError("reset")
        return _Resp(200)

    with mock.patch("requests.get", get), mock.patch("time.sleep"):
        assert fetch._http_get("http://x").status_code == 200
    assert len(seen) == 3


def test_ssl_failure_still_rebuilds_the_ca_bundle():
    """The Norton-MITM workaround must survive inside the retry loop."""
    seen = []

    def get(*_a, **k):
        seen.append(k.get("verify"))
        if len(seen) == 1:
            raise requests.exceptions.SSLError("bad cert")
        return _Resp(200)

    with mock.patch("requests.get", get), mock.patch("time.sleep"), \
            mock.patch.object(fetch, "_build_ca_bundle",
                              return_value="combined.pem") as built:
        assert fetch._http_get("http://x").status_code == 200
    built.assert_called_once()
    assert seen[1] == "combined.pem"
