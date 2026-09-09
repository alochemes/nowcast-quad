"""Remote notifications: Google Apps Script web-app (email + sheet log) and
Slack incoming webhook. Both best-effort — never fail the run.

Configure in private/config.yaml:
    notify:
      webapp_url: https://script.google.com/macros/s/.../exec
      slack_webhook: https://hooks.slack.com/services/T.../B.../...
See SETUP_NOTIFICATIONS.md for the one-time account-side setup.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path

import requests

from . import fetch, report

STATE_NAME = "notify_state.json"
MAX_CHART_BYTES = 2_000_000  # Apps Script/email inline-image safety cap
MAX_REPORT_BYTES = 6_000_000  # attached report.html cap (base64 inflates ~4/3)

# fields persisted between runs for the "changes since last run" commentary
_STATE_FIELDS = ("quarter", "current_q", "quad", "quad_name", "gdp_yoy",
                 "cpi_yoy", "dfm_saar", "gdpnow_saar", "blend_saar")


def _config() -> dict:
    try:
        import yaml

        with open(fetch.PRIVATE_CONFIG) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("notify") or {}
    except Exception:  # noqa: BLE001
        return {}


def _post(url: str, payload: dict, log) -> None:
    verify = fetch._ca_bundle()
    try:
        r = requests.post(url, json=payload, timeout=20, verify=verify)
    except requests.exceptions.SSLError:
        r = requests.post(url, json=payload, timeout=20, verify=fetch._build_ca_bundle())
    r.raise_for_status()


def _delta_line(label: str, old, new, unit: str = "%",
                bps: bool = True) -> str | None:
    """'GDP YoY: 2.25% -> 2.31% (+6 bps)' or None if either side is missing."""
    if old is None or new is None:
        return None
    try:
        old_f, new_f = float(old), float(new)
    except (TypeError, ValueError):
        return None
    d = new_f - old_f
    if abs(d) < 0.005:
        return f"{label}: unchanged at {new_f:.2f}{unit}"
    tail = f"{d * 100:+.0f} bps" if bps else f"{d:+.2f}"
    return f"{label}: {old_f:.2f}{unit} → {new_f:.2f}{unit} ({tail})"


def quad_path(table) -> dict:
    """{'2026Q3': {quad, quad_name, gdp_yoy, cpi_yoy, is_estimate}, ...}

    Persisting the whole path — not just the current quarter — is what lets
    the next run compare a quarter against its own previous reading.
    """
    if table is None or not len(table):
        return {}
    out = {}
    for p, r in table.iterrows():
        out[str(p)] = {"quad": int(r["quad"]), "quad_name": str(r["quad_name"]),
                       "gdp_yoy": round(float(r["gdp_yoy"]), 2),
                       "cpi_yoy": round(float(r["cpi_yoy"]), 2),
                       "is_estimate": bool(r["is_estimate"])}
    return out


def build_commentary(payload: dict, prev: dict | None) -> tuple[str, str]:
    """Human-readable 'changes since last run' block, plus a change_kind of
    quad_change / roll / none / first_run.

    Every comparison is LIKE QUARTER WITH LIKE QUARTER. The previous run's
    whole quad path is kept in the state file precisely so that a calendar
    roll (3Q26 replacing 2Q26 as the current quarter) is not mistaken for the
    quad moving. Before this, a roll compared last run's 2Q26 against this
    run's 3Q26 and fired a spurious QUAD CHANGE alert (observed 2026-08-03).
    """
    if not prev:
        return ("First run with change tracking enabled — "
                "no previous run to compare against.", "first_run")

    cur_q = payload.get("current_q")            # e.g. "2026Q3"
    label = payload.get("quarter", cur_q)       # e.g. "3Q26E"
    prev_path = prev.get("path") or {}
    was = prev_path.get(cur_q) or {}
    if not was and "path" not in prev and prev.get("quarter") == label:
        # state file written before the path was persisted: fall back to the
        # old single-quarter fields, but only when the LABEL matches, so this
        # can never resurrect the cross-quarter comparison it replaced
        was = {k: prev.get(k) for k in ("quad", "quad_name", "gdp_yoy", "cpi_yoy")}
    lines = [f"Changes since last run ({prev.get('timestamp', 'unknown time')}):"]
    kind = "none"

    # 1. the current quarter, judged against what the last run said about it
    if was.get("quad") is None:
        kind = "roll"
        lines.append(f"• {label} is the current quarter and is new in view — "
                     f"Quad {payload.get('quad')} "
                     f"({payload.get('quad_name', '')}); the last run did not "
                     f"carry an estimate for it.")
    elif was["quad"] == payload.get("quad"):
        lines.append(f"• {label}: Quad {payload.get('quad')} "
                     f"({payload.get('quad_name', '')}) — unchanged from last "
                     f"run's reading for this same quarter.")
    else:
        kind = "quad_change"
        lines.append(f"• QUAD CHANGE for {label}: Quad {was['quad']} "
                     f"({was.get('quad_name', '')}) → Quad {payload.get('quad')} "
                     f"({payload.get('quad_name', '')})")

    # 2. a calendar roll is normal housekeeping, reported separately
    if prev.get("current_q") and prev["current_q"] != cur_q:
        lines.append(f"• Calendar quarter rolled: {prev.get('quarter')} → {label}")
        settled = (payload.get("path") or {}).get(prev["current_q"]) or {}
        if settled and not settled.get("is_estimate"):
            prev_est = (prev_path.get(prev["current_q"]) or {}).get("quad")
            tail = ("as estimated" if prev_est == settled.get("quad")
                    else f"last estimated Quad {prev_est}" if prev_est else "")
            lines.append(f"• {prev.get('quarter', prev['current_q'])} is now "
                         f"actual: Quad {settled.get('quad')} "
                         f"({settled.get('quad_name', '')})"
                         + (f" — {tail}" if tail else ""))

    # 3. levels for the SAME quarter (never across a roll)
    for lab, key in (("GDP YoY", "gdp_yoy"), ("CPI YoY", "cpi_yoy")):
        line = _delta_line(f"{label} {lab}", was.get(key), payload.get(key))
        if line:
            lines.append("• " + line)

    comp = []
    for lab, key in (("DFM", "dfm_saar"), ("GDPNow", "gdpnow_saar"),
                     ("blend", "blend_saar")):
        # the SAAR components describe whichever quarter the ensemble targeted;
        # only comparable when that quarter did not change
        if prev.get("ensemble_q") == payload.get("ensemble_q"):
            line = _delta_line(lab, prev.get(key), payload.get(key))
            if line:
                comp.append(line)
    if comp:
        lines.append(f"• Q/Q SAAR components for {payload.get('ensemble_q', '')}"
                     f" — " + "; ".join(comp))
    return "\n".join(lines), kind


def build_subject(payload: dict, kind: str, when=None) -> str:
    """ASCII-only subject line.

    Deliberately no emoji, arrows or em-dashes: the Apps Script source that
    used to hold those literals rendered them as mojibake in the delivered
    subject (reported 2026-08-03). Mail headers are the one place where the
    encoding is worth not gambling on, so the whole line stays 7-bit.

    Built here rather than in the Apps Script so wording changes ship with a
    normal run instead of needing a manual redeploy.
    """
    when = datetime.now() if when is None else when
    label = payload.get("quarter", "")
    quad = payload.get("quad")
    name = payload.get("quad_name", "")
    date_tag = f"{when:%b %-d}" if os.name != "nt" else f"{when:%b %#d}"
    if kind == "quad_change":
        was = payload.get("prev_quad")
        head = f"Nowcast Quad CHANGE: {label} Quad {was} -> {quad} {name}"
    elif kind == "roll":
        head = f"Nowcast Quad: {label} Quad {quad} {name} (new quarter)"
    elif kind == "first_run":
        head = f"Nowcast Quad: {label} Quad {quad} {name} (first run)"
    else:
        head = f"Nowcast Quad: {label} Quad {quad} {name}"
    subject = f"{head} - {date_tag}"
    # belt and braces: strip anything non-ASCII that slipped in via quad_name
    return subject.encode("ascii", "replace").decode("ascii")


def enrich_payload(payload: dict, res: dict, output_dir, log=print) -> dict:
    """Add run-over-run commentary, the inline chart and the full report to an
    OK payload, and persist this run's numbers for the next comparison.
    Best-effort: every step is optional, none may fail the run."""
    out = Path(output_dir)
    try:
        if res.get("ensemble"):
            for k in ("dfm_saar", "gdpnow_saar", "blend_saar"):
                payload[k] = res["ensemble"][k]
            payload["ensemble_q"] = res["ensemble"].get("quarter")
        payload["current_q"] = str(res.get("current_q", ""))
        payload["path"] = quad_path(res.get("table"))
        state_path = out / STATE_NAME
        prev = None
        try:
            with open(state_path, encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        if prev:
            was = (prev.get("path") or {}).get(payload["current_q"]) or {}
            payload["prev_quad"] = was.get("quad")
        commentary, kind = build_commentary(payload, prev)
        payload["commentary"] = commentary
        payload["change_kind"] = kind
        payload["subject"] = build_subject(payload, kind)
        state = {k: payload.get(k) for k in _STATE_FIELDS}
        state["path"] = payload["path"]
        state["ensemble_q"] = payload.get("ensemble_q")
        state["timestamp"] = f"{datetime.now():%Y-%m-%d %H:%M}"
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
    except Exception as e:  # noqa: BLE001 - commentary must never fail the run
        log(f"notify: commentary skipped: {e}")
        payload.setdefault("commentary", "")
    try:
        png = Path(res.get("png", "") or out / "quad_map.png")
        if png.exists() and png.stat().st_size <= MAX_CHART_BYTES:
            payload["chart_png_b64"] = base64.b64encode(png.read_bytes()).decode()
    except Exception:  # noqa: BLE001
        pass
    # the history ribbon: every quarter's call over time, one strip each.
    # Inline images do not count against Gmail's ~102 KB body clip, so it can
    # ride along with the map (written by report.render_html).
    try:
        ribbon = out / "quad_ribbon.png"
        if ribbon.exists() and ribbon.stat().st_size <= MAX_CHART_BYTES:
            payload["ribbon_png_b64"] = base64.b64encode(ribbon.read_bytes()).decode()
    except Exception:  # noqa: BLE001
        pass
    # the report itself: tables rendered into the email body, plus the
    # standalone report.html attached for the detail sections
    try:
        payload["report_html"] = report.email_report_html(
            res["table"], res.get("display"), res.get("meta"))
    except Exception as e:  # noqa: BLE001
        log(f"notify: report tables skipped: {e}")
    try:
        html_path = Path(res.get("html", "") or out / "report.html")
        size = html_path.stat().st_size if html_path.exists() else 0
        if 0 < size <= MAX_REPORT_BYTES:
            payload["report_file_b64"] = base64.b64encode(
                html_path.read_bytes()).decode()
            payload["report_filename"] = (
                f"nowcast_report_{datetime.now():%Y-%m-%d}.html")
        elif size:
            log(f"notify: report.html is {size / 1e6:.1f} MB (> "
                f"{MAX_REPORT_BYTES / 1e6:.0f} MB cap) — not attached")
    except Exception as e:  # noqa: BLE001
        log(f"notify: report attachment skipped: {e}")
    return payload


def push_status(payload: dict, log=print) -> None:
    """payload keys: status, quarter, quad, quad_name, gdp_yoy, cpi_yoy, note."""
    cfg = _config()
    if not cfg:
        return
    url = cfg.get("webapp_url")
    if url:
        try:
            _post(url, payload, log)
            log("notify: pushed to Google Sheet/email")
        except Exception as e:  # noqa: BLE001
            log(f"notify: webapp push failed: {e}")
    hook = cfg.get("slack_webhook")
    if hook:
        if payload.get("status") == "OK":
            text = (f":white_check_mark: *Nowcast Quad* {payload.get('quarter')}: "
                    f"Quad {payload.get('quad')} {payload.get('quad_name')} — "
                    f"GDP {payload.get('gdp_yoy')}% | CPI {payload.get('cpi_yoy')}%"
                    + (f"\n_{payload.get('note')}_" if payload.get("note") else "")
                    + (f"\n{payload.get('commentary')}"
                       if payload.get("commentary") else ""))
        else:
            text = (":rotating_light: *Nowcast Quad run FAILED* — check "
                    "`output\\run.log` on the PC. " + str(payload.get("note", "")))
        try:
            _post(hook, {"text": text}, log)
            log("notify: pushed to Slack")
        except Exception as e:  # noqa: BLE001
            log(f"notify: slack push failed: {e}")
