"""Quad-map rendering (PNG) and self-contained HTML report.

Layout follows the Hedgeye GIP quad-map convention:
  x-axis = change in headline CPI YoY vs prior quarter (bps), right = accelerating
  y-axis = change in real GDP YoY vs prior quarter (bps), up = accelerating
  Quad 1 top-left, Quad 2 top-right, Quad 3 bottom-right, Quad 4 bottom-left.
Historical quarters get white label boxes, estimates black boxes with an E suffix.
"""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .quads import QUAD_NAMES, quarter_label

# dark-enough-on-white variants of the conventional quad colors
QUAD_COLORS = {1: "#1a7f37", 2: "#b45309", 3: "#b91c1c", 4: "#a21caf"}
QUAD_CORNERS = {1: ("left", "top"), 2: ("right", "top"),
                3: ("right", "bottom"), 4: ("left", "bottom")}
QUAD_SUBTITLES = {
    1: "Growth ↑  Inflation ↓",
    2: "Growth ↑  Inflation ↑",
    3: "Growth ↓  Inflation ↑",
    4: "Growth ↓  Inflation ↓",
}


def _smooth_path(x: np.ndarray, y: np.ndarray, n: int = 300):
    """Gently smoothed curve through the points in order (no overshoot).

    PCHIP on chord-length parameter: shape-preserving, unlike a cubic spline,
    which loops far outside the data when the path backtracks.
    """
    if len(x) < 3:
        return x, y
    try:
        from scipy.interpolate import PchipInterpolator

        d = np.hypot(np.diff(x), np.diff(y))
        d[d == 0] = 1e-9
        t = np.concatenate([[0.0], np.cumsum(d)])
        t /= t[-1]
        tt = np.linspace(0, 1, n)
        return PchipInterpolator(t, x)(tt), PchipInterpolator(t, y)(tt)
    except Exception:
        return x, y


def _place_labels(ax, pts_disp: np.ndarray) -> list[tuple[float, float]]:
    """Greedy per-point offset choice (display px) maximizing clearance from
    other points and already-placed labels, staying inside the axes."""
    candidates = [(dx * r, dy * r)
                  for r in (34, 55)
                  for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1),
                                 (1.4, 0), (-1.4, 0), (0, 1.4), (0, -1.4))]
    (x0, y0), (x1, y1) = ax.transAxes.transform([(0, 0), (1, 1)])
    placed = []
    chosen = []
    for i, p in enumerate(pts_disp):
        best, best_score = candidates[0], -np.inf
        for c in candidates:
            pos = p + np.asarray(c)
            others = np.vstack([np.delete(pts_disp, i, axis=0)] + ([placed] if placed else []))
            score = np.min(np.hypot(*(others - pos).T)) if len(others) else np.inf
            # half-label margins: keep the box inside the plot area
            if not (x0 + 55 < pos[0] < x1 - 55 and y0 + 28 < pos[1] < y1 - 28):
                score -= 10000
            if score > best_score:
                best, best_score = c, score
        chosen.append(best)
        placed.append(p + np.asarray(best))
    return chosen


def render_quad_png(df: pd.DataFrame, out_path: Path, title: str = "United States",
                    subtitle: str = "", current: pd.Period | None = None) -> Path:
    """df: quad_table() output (needs d_cpi_bps, d_gdp_bps, is_estimate).

    current: the in-progress (nowcast) quarter — its label box is drawn in the
    color of the quad it sits in.
    """
    x = df["d_cpi_bps"].to_numpy(float)
    y = df["d_gdp_bps"].to_numpy(float)

    lim_x = max(40.0, np.nanmax(np.abs(x)) * 1.25)
    lim_y = max(40.0, np.nanmax(np.abs(y)) * 1.25)

    fig, ax = plt.subplots(figsize=(11, 8.5), dpi=150)
    fig.patch.set_facecolor("white")

    # quadrant tints, kept faint so the path stays dominant
    tints = {1: "#1a7f37", 2: "#d97706", 3: "#dc2626", 4: "#c026d3"}
    spans = {1: ((-lim_x, 0), (0, lim_y)), 2: ((0, lim_x), (0, lim_y)),
             3: ((0, lim_x), (-lim_y, 0)), 4: ((-lim_x, 0), (-lim_y, 0))}
    for q, ((x0, x1), (y0, y1)) in spans.items():
        ax.fill_between([x0, x1], y0, y1, color=tints[q], alpha=0.05, zorder=0)

    ax.axhline(0, color="#9ca3af", lw=1.2, zorder=1)
    ax.axvline(0, color="#9ca3af", lw=1.2, zorder=1)
    ax.grid(True, color="#e5e7eb", lw=0.6, zorder=0)
    ax.set_axisbelow(True)

    # quadrant corner labels
    pad_x, pad_y = 0.04 * lim_x, 0.05 * lim_y
    for q, (hx, vy) in QUAD_CORNERS.items():
        cx = -lim_x + pad_x if hx == "left" else lim_x - pad_x
        cy = lim_y - pad_y if vy == "top" else -lim_y + pad_y
        ax.text(cx, cy, f"QUAD {q} · {QUAD_NAMES[q]}\n{QUAD_SUBTITLES[q]}",
                ha=hx, va=vy, fontsize=11, fontweight="bold",
                color=QUAD_COLORS[q], linespacing=1.4, zorder=2)

    ax.set_xlim(-lim_x, lim_x)
    ax.set_ylim(-lim_y, lim_y)

    # trajectory
    xs, ys = _smooth_path(x, y)
    ax.plot(xs, ys, color="#111827", lw=1.6, zorder=3)
    ax.scatter(x, y, s=18, color="#111827", zorder=4)

    ax.set_xlabel("Δ Headline CPI YoY vs prior quarter (bps)  →  inflation accelerating",
                  fontsize=10, color="#374151")
    ax.set_ylabel("Δ Real GDP YoY vs prior quarter (bps)  →  growth accelerating",
                  fontsize=10, color="#374151")
    for spine in ax.spines.values():
        spine.set_color("#d1d5db")
    ax.tick_params(colors="#6b7280", labelsize=9)

    # header rows live in figure space so they never collide with axes content
    fig.suptitle(title, fontsize=15, fontweight="bold", color="#111827", y=0.985)
    if subtitle:
        fig.text(0.5, 0.952, subtitle, ha="center", fontsize=9.5, color="#6b7280")
    if current is not None and current in df.index:
        cur = df.loc[current]
        q = int(cur["quad"])
        fig.text(0.5, 0.915,
                 f"Current quarter {quarter_label(current, True)}:  QUAD {q} · "
                 f"{QUAD_NAMES[q]}   (GDP {cur['gdp_yoy']:.2f}%, CPI {cur['cpi_yoy']:.2f}%)",
                 ha="center", va="center", fontsize=12, fontweight="bold",
                 color=QUAD_COLORS[q],
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                           edgecolor=QUAD_COLORS[q], lw=1.4))
    fig.text(0.01, 0.005, "Data: FRED (BEA, BLS, EIA, Census, Fed surveys)",
             fontsize=8, color="#9ca3af")
    fig.text(0.99, 0.005, f"nowcast_quad · generated {datetime.now():%Y-%m-%d %H:%M}",
             fontsize=8, color="#9ca3af", ha="right")

    fig.tight_layout(rect=(0, 0.012, 1, 0.895))

    # boxed quarter labels (quarter + GDP/CPI YoY levels), placed after the
    # layout is final so display-coordinate collision checks hold
    pts_disp = ax.transData.transform(np.column_stack([x, y]))
    offsets = _place_labels(ax, pts_disp)
    for i, (p, row) in enumerate(df.iterrows()):
        est = bool(row["is_estimate"])
        is_current = current is not None and p == current
        label = quarter_label(p, est)
        if is_current:
            face, text_color = QUAD_COLORS[int(row["quad"])], "white"
        elif est:
            face, text_color = "#111827", "white"
        else:
            face, text_color = "white", "#111827"
        dx, dy = offsets[i]
        ax.annotate(
            label, (row["d_cpi_bps"], row["d_gdp_bps"]),
            xytext=(dx, dy), textcoords="offset pixels",
            fontsize=9, fontweight="bold", ha="center",
            color=text_color,
            bbox=dict(boxstyle="round,pad=0.32", facecolor=face,
                      edgecolor="#111827", lw=1.6 if is_current else 1.0),
            arrowprops=dict(arrowstyle="-", lw=0.6, color="#9ca3af",
                            shrinkA=4, shrinkB=3),
            zorder=6 if is_current else 5,
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# The chart book: how each quarter's reading moved as the data arrived.
#
# One small panel per quarter, x = the date the model ran, y = the quad it was
# calling for THAT quarter on that date. Points are colored by quad (the quad
# map's own colors) rather than by right/wrong: unlike a backtest there is no
# settled answer to score against while a quarter is still live, and the thing
# worth seeing is which quad the reading was sitting in and how steady it was.

_QUAD_Y = {1: 1, 2: 2, 3: 3, 4: 4}


def render_quad_history_png(hist: pd.DataFrame, out_path: Path,
                            ncol: int = 5) -> Path | None:
    """Per-quarter panels of the quad call over as-of time.

    hist: history.load() output. Returns None when there is not yet enough
    history to draw anything (a single as-of date is a scatter of dots).
    """
    from . import history as _history

    if hist is None or hist.empty or hist["asof"].nunique() < 2:
        return None
    quarters = _history.live_quarters(hist)
    tracks = {q: _history.quarter_track(hist, q) for q in quarters}
    # a panel needs at least two readings to show movement
    quarters = [q for q in quarters if len(tracks[q]) >= 2]
    if not quarters:
        return None

    # x is measured in days relative to each quarter's own end, not in calendar
    # dates: a quarter is only live for a few months, so on a shared calendar
    # axis every panel would be one dot marooned in white space. Relative days
    # put every panel on the same footing and make them comparable at a glance.
    def _rel_days(g, q):
        end = pd.Timestamp(q.end_time.normalize())
        return ((g["asof"] - end) / pd.Timedelta(1, unit="D")).to_numpy(float)

    # header height is fixed in INCHES, so the two title lines get the same
    # room whether the book is one row of panels or six
    nrow = int(np.ceil(len(quarters) / ncol))
    head_in = 0.95
    fig_h = 1.95 * nrow + head_in
    fig, axes = plt.subplots(nrow, ncol, figsize=(2.5 * ncol, fig_h),
                             sharey=True, sharex=True, squeeze=False)
    flat = axes.ravel()
    lo = min(_rel_days(t, q).min() for q, t in tracks.items() if len(t))
    hi = max(_rel_days(t, q).max() for q, t in tracks.items() if len(t))

    for ax, q in zip(flat, quarters):
        g = tracks[q]
        x = _rel_days(g, q)
        y = [_QUAD_Y[v] for v in g["quad"]]
        settled = _history.settled_quad(hist, q)
        if settled is not None:
            ax.axhline(_QUAD_Y[settled], color="#9ca3af", lw=1.2, ls="--",
                       zorder=1)
        ax.axvline(0, color="#d1d5db", lw=1.0, zorder=1)  # the quarter ends
        ax.plot(x, y, color="#d1d5db", lw=1.0, zorder=2)
        for xi, yi, qi, est in zip(x, y, g["quad"], g["is_estimate"]):
            # hollow marker once the quarter is an actual: the call is closed
            ax.plot(xi, yi, "o", ms=5, zorder=3,
                    color=QUAD_COLORS[int(qi)] if est else "white",
                    markeredgecolor=QUAD_COLORS[int(qi)],
                    markeredgewidth=1.4)
        first_actual = g[~g["is_estimate"]]
        if not first_actual.empty:
            ax.axvline(_rel_days(first_actual, q)[0], color="#111827", lw=0.9,
                       ls=":", zorder=1)
        n_flips = int((g["quad"].diff().fillna(0) != 0).sum())
        ax.set_title(f"{quarter_label(q, settled is None)}"
                     + (f"  ({n_flips} flip{'s' if n_flips != 1 else ''})"
                        if n_flips else "  (steady)"),
                     fontsize=8, color="#111827", pad=2)
        ax.set_ylim(4.6, 0.4)  # Quad 1 at the top, matching the map's reading
        ax.set_yticks([1, 2, 3, 4])
        ax.set_yticklabels(["1", "2", "3", "4"], fontsize=6.5)
        ax.set_xlim(lo, hi)
        ax.tick_params(labelsize=6.5, colors="#6b7280")
        ax.grid(True, axis="y", color="#f3f4f6", lw=0.6)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_color("#e5e7eb")
    for ax in flat[len(quarters):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("days from quarter end", fontsize=6.5, color="#6b7280")

    fig.tight_layout(rect=(0, 0, 1, 1 - head_in / fig_h))
    fig.text(0.5, 1 - 0.20 / fig_h,
             "What each quarter's quad reading did as the data arrived",
             ha="center", va="top", fontsize=12.5, fontweight="bold",
             color="#111827")
    fig.text(0.5, 1 - 0.46 / fig_h,
             "One panel per quarter. x = days before / after that quarter "
             "ended; y = the quad being called for it.",
             ha="center", va="top", fontsize=8, color="#6b7280")
    fig.text(0.5, 1 - 0.65 / fig_h,
             "Filled dot = still an estimate · hollow = GDP released · dotted "
             "line = the run it went actual · dashed = where it settled",
             ha="center", va="top", fontsize=8, color="#6b7280")
    out_path = Path(out_path)
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)
    return out_path


def lockin_curve(hist: pd.DataFrame, step: int = 10,
                 span: int = 210) -> pd.DataFrame:
    """For quarters that have since settled: how often the call that many days
    before the quarter ended already matched the quad it settled in.

    This is the honest read on how much weight a live call deserves. It can
    only be computed for closed quarters, so the current one is excluded by
    construction — as it must be, since its answer is not known yet.
    """
    from . import history as _history

    rows = []
    for q in _history.live_quarters(hist):
        settled = _history.settled_quad(hist, q)
        if settled is None:
            continue
        g = hist[(hist["quarter"] == q) & hist["is_estimate"]].sort_values("asof")
        if g.empty:
            continue
        end = pd.Timestamp(q.end_time.normalize())
        rel = ((g["asof"] - end) / pd.Timedelta(1, unit="D")).to_numpy(float)
        # anchored at 0 and stepping back, so the grid lands on round
        # milestones (-30, -60, -90 ...) that can be quoted directly
        for lead in range(0, -(span + 1), -step):
            prior = np.nonzero(rel <= lead)[0]
            if not len(prior):
                continue  # no call existed that early
            rows.append({"quarter": str(q), "lead": lead,
                         "match": bool(int(g["quad"].iloc[prior[-1]]) == settled)})
    if not rows:
        return pd.DataFrame(columns=["lead", "share", "n"])
    df = pd.DataFrame(rows)
    out = df.groupby("lead")["match"].agg(["mean", "count"])
    return out.rename(columns={"mean": "share", "count": "n"}).reset_index()


def render_quad_lockin_png(hist: pd.DataFrame, out_path: Path) -> Path | None:
    """The lock-in curve — agreement with the settled quad, by lead time."""
    curve = lockin_curve(hist)
    if curve.empty or curve["n"].max() < 3:
        return None
    fig, ax = plt.subplots(figsize=(9, 3.6), dpi=150)
    ax.plot(curve["lead"], curve["share"] * 100, color="#111827", lw=2,
            zorder=3)
    ax.fill_between(curve["lead"], 0, curve["share"] * 100, color="#111827",
                    alpha=0.06, zorder=1)
    ax.axhline(25, color="#9ca3af", lw=1, ls="--", zorder=2)
    ax.text(curve["lead"].min(), 26.5, "  25% = a coin toss between four quads",
            fontsize=8, color="#6b7280", va="bottom")
    ax.axvline(0, color="#d1d5db", lw=1, zorder=2)
    ax.set_ylim(0, 100)
    ax.set_xlim(curve["lead"].min(), max(curve["lead"].max(), 0))
    ax.set_xlabel("days before the quarter ended", fontsize=9, color="#374151")
    ax.set_ylabel("% of quarters already\non the settled quad", fontsize=9,
                  color="#374151")
    ax.grid(True, color="#f3f4f6", lw=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors="#6b7280", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#e5e7eb")
    n_q = curve["n"].max()
    ax.set_title(f"How early the quad call locks in  "
                 f"({n_q} settled quarters)",
                 fontsize=11.5, fontweight="bold", color="#111827", pad=8)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def render_quad_ribbon_png(hist: pd.DataFrame, out_path: Path,
                           max_hold_days: int = 14) -> Path | None:
    """One strip per quarter down the page, colored by the quad being called
    on each date — the whole book at a glance, showing when calls settled.

    max_hold_days caps how far a reading is drawn forward. Each reading is
    painted as holding until the next one, so without a cap a stretch with no
    runs (the PC off for a month, or a backfill that has not reached that
    span yet) would be painted as a solid bar and read as a call we were
    making the whole time. Capped, the gap shows as white space, which is what
    actually happened.
    """
    from . import history as _history

    if hist is None or hist.empty or hist["asof"].nunique() < 2:
        return None
    quarters = _history.live_quarters(hist)
    tracks = {q: _history.quarter_track(hist, q) for q in quarters}
    quarters = [q for q in quarters if len(tracks[q]) >= 2]
    if not quarters:
        return None

    cap = pd.Timedelta(max_hold_days, unit="D")
    fig, ax = plt.subplots(figsize=(11, 0.42 * len(quarters) + 1.9), dpi=150)
    for row, q in enumerate(quarters):
        g = tracks[q]
        xs = list(g["asof"])
        # each reading holds until the next run, but no longer than the cap
        for i, (x0, qd) in enumerate(zip(xs, g["quad"])):
            nxt = xs[i + 1] if i + 1 < len(xs) else x0 + pd.Timedelta(7, unit="D")
            x1 = min(nxt, x0 + cap)
            ax.barh(row, (x1 - x0) / pd.Timedelta(1, unit="D"), left=x0,
                    height=0.72, color=QUAD_COLORS[int(qd)],
                    alpha=0.55 if g["is_estimate"].iloc[i] else 1.0,
                    edgecolor="white", lw=0.4)
    ax.set_yticks(range(len(quarters)))
    ax.set_yticklabels([quarter_label(q, _history.settled_quad(hist, q) is None)
                        for q in quarters], fontsize=8)
    ax.invert_yaxis()
    ax.tick_params(colors="#6b7280", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#e5e7eb")
    ax.grid(True, axis="x", color="#f3f4f6", lw=0.6)
    ax.set_axisbelow(True)
    handles = [plt.Line2D([0], [0], marker="s", ls="", markersize=9,
                          color=QUAD_COLORS[q],
                          label=f"Quad {q} · {QUAD_NAMES[q]}") for q in (1, 2, 3, 4)]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.08),
              ncol=4, frameon=False, fontsize=8.5)
    ax.set_title("Every quarter's quad call over time "
                 "(pale = still an estimate, solid = GDP released)",
                 fontsize=11, fontweight="bold", color="#111827", pad=10)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def _quarter_cols_table(display: pd.DataFrame, rows: list[tuple[str, str, str, bool]]) -> str:
    """One Hedgeye-style table: quarters as columns.

    rows: (row label, display column, format, heat) — heat shades each cell by
    its change vs the prior quarter (green accelerating / red decelerating).
    """
    heads = "".join(
        f"<th class='{'est' if e else ''}'>{quarter_label(p, e)}</th>"
        for p, e in zip(display.index, display["is_estimate"]))
    body = []
    for label, col, fmt, heat in rows:
        vals = display[col]
        tds = []
        for i, (p, v) in enumerate(vals.items()):
            style = ""
            if heat and i > 0 and pd.notna(v) and pd.notna(vals.iloc[i - 1]):
                if v > vals.iloc[i - 1]:
                    style = "background:#dcfce7"
                elif v < vals.iloc[i - 1]:
                    style = "background:#fee2e2"
            cls = "est" if display["is_estimate"].iloc[i] else ""
            tds.append(f"<td class='{cls}' style='{style}'>{format(v, fmt)}</td>")
        body.append(f"<tr><th>{label}</th>{''.join(tds)}</tr>")
    return (f"<div class='scroll'><table class='qtab'><thead><tr><th></th>{heads}"
            f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


def _section_html(title: str, payload) -> str:
    if isinstance(payload, dict):
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in payload.items())
        return f"<h2>{title}</h2><table class='kv'>{rows}</table>"
    if isinstance(payload, list) and payload:
        cols = list(payload[0].keys())
        head = "".join(f"<th>{c}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{r.get(c, '')}</td>" for c in cols) + "</tr>"
            for r in payload)
        return (f"<h2>{title}</h2><div class='scroll'><table class='qtab'>"
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")
    return f"<h2>{title}</h2><p>n/a</p>"


def render_html(df: pd.DataFrame, png_path: Path, meta: dict, out_path: Path,
                display: pd.DataFrame | None = None,
                sections: list | None = None,
                current: pd.Period | None = None,
                history: pd.DataFrame | None = None) -> Path:
    b64 = base64.b64encode(Path(png_path).read_bytes()).decode()

    # headline: the calendar quarter we are in, plus the two ahead of it —
    # the report should read forward, the way the market does
    if current is not None and current in df.index:
        cur_rows = df.loc[[current]]
    else:
        cur_rows = df[df["is_estimate"]]
    headline = ""
    if not cur_rows.empty:
        p = cur_rows.index[0]
        r = cur_rows.iloc[0]
        qc = QUAD_COLORS[int(r["quad"])]
        headline = (f"<div class='headline' style='border-color:{qc};color:{qc}'>"
                    f"Current quarter {quarter_label(p, bool(r['is_estimate']))}: "
                    f"QUAD {int(r['quad'])} · "
                    f"{r['quad_name']} &nbsp;(GDP {r['gdp_yoy']:.2f}%, "
                    f"CPI {r['cpi_yoy']:.2f}%)</div>")
        ahead = df.loc[df.index > p].head(2)
        if not ahead.empty:
            chips = "".join(
                f"<span class='chip' style='border-color:{QUAD_COLORS[int(a['quad'])]};"
                f"color:{QUAD_COLORS[int(a['quad'])]}'>{quarter_label(ap, True)} "
                f"&rarr; Quad {int(a['quad'])} · {a['quad_name']}</span>"
                for ap, a in ahead.iterrows())
            headline += f"<div class='ahead'>Next up: {chips}</div>"

    # the three stacked quarter-column tables above the chart
    tables_html = ""
    if display is not None:
        tables_html = (
            "<h2>Levels</h2>"
            + _quarter_cols_table(display, [
                ("Real GDP ($bn, chained 2017, SAAR)", "gdp_level", ",.0f", False),
                ("CPI index (1982-84=100, SA, qtr avg)", "cpi_index", ".1f", False)])
            + "<h2>Year-over-year change (%)</h2>"
            + _quarter_cols_table(display, [
                ("Real GDP YoY %", "gdp_yoy", ".2f", True),
                ("Headline CPI YoY %", "cpi_yoy", ".2f", True)])
            + "<h2>Quarter-over-quarter change (%, annualized)</h2>"
            + _quarter_cols_table(display, [
                ("Real GDP QoQ SAAR %", "gdp_qq_saar", ".2f", True),
                ("CPI QoQ SAAR %", "cpi_qq_saar", ".2f", True)])
        )

    quad_rows = []
    for p, r in df.iterrows():
        est = bool(r["is_estimate"])
        cls = "est" if est else ""
        quad_color = QUAD_COLORS[int(r["quad"])]
        quad_rows.append(
            f"<tr class='{cls}'><td>{quarter_label(p, est)}</td>"
            f"<td>{r['gdp_yoy']:.2f}</td><td>{r['d_gdp_bps']:+.0f}</td>"
            f"<td>{r['cpi_yoy']:.2f}</td><td>{r['d_cpi_bps']:+.0f}</td>"
            f"<td style='color:{quad_color};font-weight:700'>Quad {int(r['quad'])} · "
            f"{r['quad_name']}</td></tr>"
        )
    rows = quad_rows
    meta_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in meta.items())
    sections_html = "".join(_section_html(t, p) for t, p in (sections or []))

    # the chart book — written next to the report so the HTML can inline them
    out_path = Path(out_path)
    book_html = ""
    if history is not None and not history.empty:
        n_runs = history["asof"].nunique()
        imgs = []
        for name, fn, cap in (
            ("quad_lockin.png", render_quad_lockin_png,
             "Only quarters that have since settled can be scored, so this "
             "says nothing about the current call directly — it says how much "
             "weight a call at that stage has earned historically. Where the "
             "line is near 25% the model is barely better than picking one of "
             "the four quads at random."),
            ("quad_ribbon.png", render_quad_ribbon_png,
             "Each strip is one quarter, read left to right as the model reran. "
             "A strip that holds one color is a call that never wavered; a "
             "strip that changes color is a quarter the data argued about."),
            ("quad_chartbook.png", render_quad_history_png,
             "The same history broken out per quarter. Flips are counted in "
             "each panel title — a quarter with several is one where the "
             "growth or inflation delta sat close to zero, so treat its quad "
             "as provisional even now."),
        ):
            try:
                p = fn(history, out_path.parent / name)
            except Exception:  # noqa: BLE001 - a chart must not break the report
                p = None
            if p:
                b = base64.b64encode(Path(p).read_bytes()).decode()
                imgs.append(f"<img src='data:image/png;base64,{b}' alt='{name}'>"
                            f"<p class='note'>{cap}</p>")
        if imgs:
            book_html = (
                "<h2>How the reading has moved over time</h2>"
                f"<p class='note'>Built from {n_runs} model runs on record. "
                "Colors are the quad colors used on the map above, so a "
                "quarter's strip or dot tells you which quad it was sitting "
                "in on that date. Pale / filled = still an estimate; solid / "
                "hollow = GDP has since been released and the call is "
                "closed.</p>" + "".join(imgs))
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>US Growth/Inflation Quad Nowcast</title>
<style>
 body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1100px;
        color: #111827; background: #fff; }}
 h1 {{ font-size: 22px; margin-bottom: 2px; }}
 .sub {{ color: #6b7280; font-size: 13px; margin-bottom: 18px; }}
 img {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; }}
 table {{ border-collapse: collapse; margin-top: 18px; font-size: 13.5px; width: 100%; }}
 th, td {{ padding: 6px 12px; border-bottom: 1px solid #e5e7eb; text-align: right; }}
 th:first-child, td:first-child {{ text-align: left; }}
 td:last-child {{ text-align: left; }}
 th {{ color: #6b7280; font-weight: 600; background: #f9fafb; }}
 tr.est td {{ background: #f3f4f6; font-style: italic; }}
 h2 {{ font-size: 15px; margin: 22px 0 4px; color: #374151; }}
 .headline {{ display: inline-block; margin: 10px 0 4px; padding: 8px 16px;
              border: 2px solid; border-radius: 8px; font-size: 16px; font-weight: 700; }}
 .scroll {{ overflow-x: auto; }}
 table.qtab {{ width: auto; }}
 table.qtab th, table.qtab td {{ padding: 5px 9px; white-space: nowrap; }}
 table.qtab tbody th {{ text-align: left; font-weight: 600; color: #374151; }}
 table.qtab th.est, table.qtab td.est {{ font-style: italic; }}
 table.qtab thead th.est {{ background: #111827; color: white; }}
 table.kv {{ width: auto; font-size: 12.5px; }}
 table.kv td {{ text-align: left; }}
 .meta {{ margin-top: 22px; font-size: 12px; color: #6b7280; }}
 .meta td {{ padding: 2px 12px 2px 0; border: none; text-align: left; }}
 .note {{ color: #6b7280; font-size: 12px; margin: 4px 0 14px; }}
 .ahead {{ margin: 6px 0 2px; font-size: 12.5px; color: #6b7280; }}
 .chip {{ display: inline-block; margin: 0 6px 4px 0; padding: 3px 9px;
          border: 1px solid; border-radius: 999px; font-size: 12px;
          font-weight: 600; }}
</style></head><body>
<h1>US Growth &amp; Inflation Quad Nowcast</h1>
<div class="sub">Generated {datetime.now():%Y-%m-%d %H:%M} · italic / dark-header columns are model estimates ("E")</div>
{headline}
{tables_html}
<p class="note">Heat shading: green = accelerating vs prior quarter, red = decelerating.
GDP levels for out-quarters are implied from the base-effect YoY path.</p>
<h2>Quad map</h2>
<img src="data:image/png;base64,{b64}" alt="Quad map">
<h2>Quad assignment</h2>
<table>
<thead><tr><th>Quarter</th><th>Real GDP YoY %</th><th>Δ bps</th>
<th>CPI YoY %</th><th>Δ bps</th><th>Quad</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
{book_html}
{sections_html}
<div class="meta"><b>Run details</b><table>{meta_rows}</table></div>
</body></html>"""
    out_path = Path(out_path)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Email rendering
#
# The emailed report cannot reuse render_html's markup: Gmail drops <style>
# blocks (so every rule must be an inline style attribute) and clips a message
# body past ~102 KB (so the chart stays a cid: attachment instead of the
# report's inlined data: URI). Quarters run down the rows rather than across
# the columns — a 12-column numeric table is unreadable on a phone.

_TH = ("padding:5px 8px;border-bottom:1px solid #d1d5db;background:#f9fafb;"
       "color:#6b7280;font-weight:600;font-size:11.5px;text-align:right;"
       "white-space:nowrap")
_TD = ("padding:5px 8px;border-bottom:1px solid #f3f4f6;font-size:12.5px;"
       "text-align:right;white-space:nowrap")
_EST_BG = "background:#f3f4f6;font-style:italic"


def esc_html(x) -> str:
    s = str(x)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _email_table(headers: list[str], rows: list[list[str]],
                 est_flags: list[bool]) -> str:
    head = "".join(
        f"<th style='{_TH}{';text-align:left' if i == 0 else ''}'>{h}</th>"
        for i, h in enumerate(headers))
    body = []
    for row, est in zip(rows, est_flags):
        tds = "".join(
            f"<td style='{_TD}{';text-align:left' if i == 0 else ''}"
            f"{';' + _EST_BG if est else ''}'>{c}</td>"
            for i, c in enumerate(row))
        body.append(f"<tr>{tds}</tr>")
    return ("<table role='presentation' cellspacing='0' cellpadding='0' "
            "style='border-collapse:collapse;margin:2px 0 14px'>"
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
            "</table>")


def _h3(text: str) -> str:
    return (f"<h3 style='font-size:13px;margin:16px 0 2px;color:#374151;"
            f"font-weight:600'>{text}</h3>")


def email_report_html(df: pd.DataFrame, display: pd.DataFrame | None = None,
                      meta: dict | None = None) -> str:
    """The report's substance as email-safe HTML (see the note above).

    df: quad_table() output; display: the levels/YoY/QoQ frame built by the
    pipeline; meta: the run-details dict shown at the foot of the report.
    """
    est_flags = [bool(v) for v in df["is_estimate"]]
    labels = [quarter_label(p, e) for p, e in zip(df.index, est_flags)]

    quad_rows = []
    for label, (_p, r) in zip(labels, df.iterrows()):
        q = int(r["quad"])
        quad_rows.append([
            label, f"{r['gdp_yoy']:.2f}", f"{r['d_gdp_bps']:+.0f}",
            f"{r['cpi_yoy']:.2f}", f"{r['d_cpi_bps']:+.0f}",
            f"<span style='color:{QUAD_COLORS[q]};font-weight:700'>"
            f"Quad {q} · {r['quad_name']}</span>"])
    out = [_h3("Quad assignment — year-over-year rate of change"),
           _email_table(["Quarter", "GDP YoY %", "Δ bps", "CPI YoY %", "Δ bps",
                         "Quad"], quad_rows, est_flags)]

    if display is not None:
        lvl_rows = []
        for label, (_p, r) in zip(labels, display.iterrows()):
            lvl_rows.append([
                label, f"{r['gdp_level']:,.0f}", f"{r['gdp_qq_saar']:.2f}",
                f"{r['cpi_index']:.1f}", f"{r['cpi_qq_saar']:.2f}"])
        out += [_h3("Levels and quarter-over-quarter change (annualized)"),
                _email_table(["Quarter", "Real GDP $bn", "GDP QoQ SAAR %",
                              "CPI index", "CPI QoQ SAAR %"],
                             lvl_rows, est_flags)]

    out.append("<p style='color:#6b7280;font-size:11.5px;margin:0 0 12px'>"
               "Shaded italic rows are model estimates (\"E\"). Out-quarter "
               "levels are implied by the base-effect YoY path.</p>")

    if meta:
        rows = "".join(
            f"<tr><td style='padding:1px 10px 1px 0;font-size:11.5px;"
            f"color:#6b7280'>{esc_html(k)}</td>"
            f"<td style='padding:1px 0;font-size:11.5px;color:#374151'>"
            f"{esc_html(v)}</td></tr>" for k, v in meta.items())
        out.append(_h3("Run details") +
                   f"<table role='presentation' cellspacing='0' cellpadding='0'"
                   f" style='border-collapse:collapse'>{rows}</table>")
    return "".join(out)
