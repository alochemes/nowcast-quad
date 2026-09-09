"""Where does the base-effects GROWTH-axis forecast miss most, and what free,
horizon-available signal captures it?

Comp model calls GDP YoY direction ~60% (vs CPI ~70%), so growth is where the
joint-quad forecast (~40-45% at 120-130d) bleeds most. The comp captures the
base a quarter laps but ASSUMES normal new sequential growth; it must miss
wherever the actual move is driven by a growth SHOCK (new momentum), not the
base. This script:
  1. Diagnoses the misses — by comp conviction, at turning points, at knife-edges.
  2. Searches leading/coincident signals measured in quarter q-1 (known at the
     start of q, no lookahead) for the direction of the *acceleration* ΔYoY_q,
     each on its own and CONVICTION-GATED (use comp when its |Δcomp| is decisive,
     defer to the signal only when comp is ambivalent).
Print-only exploration; revised data (vintage caveat noted), ex-2020/21 headline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nowcast import fetch  # noqa: E402
from research.base_effects_analysis import yoy_series  # noqa: E402

nolog = lambda *a: None
gdp_yoy = yoy_series()["GDP"]
d_yoy = gdp_yoy.diff()
comp = (gdp_yoy.shift(4) + gdp_yoy.shift(8)) / 2.0
fc = -comp.diff()                       # comp forecast of Δyoy_q, known at q-start
true = np.sign(d_yoy).replace(0, -1)    # ties -> deceleration (quad convention)
pred = np.sign(fc).replace(0, -1)


def qser(sid, start="1960-01-01", how="avg"):
    """Quarterly series measured in each quarter (avg of monthly/weekly)."""
    s = fetch.get_series(sid, start=start, log=nolog)
    s = s.groupby(pd.PeriodIndex(s.index, freq="M")).mean()
    s = s.reindex(pd.period_range(s.index[0], s.index[-1], freq="M"))
    return s.groupby(s.index.asfreq("Q")).mean()


def qyoy(sid, start="1960-01-01"):
    q = qser(sid, start)
    return (q / q.shift(4) - 1) * 100


def mask(idx, start, ex2020=True):
    m = idx >= pd.Period(start, "Q")
    if ex2020:
        s = idx.astype(str)
        m &= ~(s.str.startswith("2020") | s.str.startswith("2021"))
    return m


def hit(p, t, idx):
    p, t = p.reindex(idx), t.reindex(idx)
    ok = (np.sign(p) == np.sign(t)) & p.notna() & t.notna()
    d = p.notna() & t.notna()
    return 100 * ok.sum() / max(d.sum(), 1), int(d.sum())


START = "1985Q1"
base_idx = gdp_yoy.index[mask(gdp_yoy.index, START)]
base_idx = pd.PeriodIndex([q for q in base_idx if pd.notna(fc.get(q)) and pd.notna(d_yoy.get(q))])

print(f"=== GROWTH-AXIS COMP DIAGNOSIS ({START}+, ex-COVID, n={len(base_idx)}) ===")
h0, n0 = hit(pred, true, base_idx)
print(f"comp GDP-direction hit: {h0:.0f}%  (n={n0})")

# 1a. by conviction (|Δcomp| terciles)
absfc = fc.abs().reindex(base_idx)
lo, hi = absfc.quantile([1 / 3, 2 / 3])
for lab, sub in (("low  |Δcomp| (ambivalent)", base_idx[absfc <= lo]),
                 ("mid  |Δcomp|", base_idx[(absfc > lo) & (absfc < hi)]),
                 ("high |Δcomp| (decisive)", base_idx[absfc >= hi])):
    hh, nn = hit(pred, true, sub)
    print(f"  {lab:28s} {hh:.0f}%  (n={nn})")

# 1b. turning points vs continuations
prev_dir = np.sign(d_yoy.shift(1)).replace(0, -1)
is_turn = (true != prev_dir.reindex(true.index))
turn_idx = base_idx[is_turn.reindex(base_idx).fillna(False).values]
cont_idx = base_idx[~is_turn.reindex(base_idx).fillna(False).values]
ht, nt = hit(pred, true, turn_idx)
hc, nc = hit(pred, true, cont_idx)
print(f"  turning points (Δyoy reverses)  {ht:.0f}%  (n={nt})")
print(f"  continuations (Δyoy persists)   {hc:.0f}%  (n={nc})")

# 1c. knife-edge vs decisive actual move
small = base_idx[d_yoy.abs().reindex(base_idx) < 0.25]
big = base_idx[d_yoy.abs().reindex(base_idx) >= 0.25]
hs, ns = hit(pred, true, small)
hb, nb = hit(pred, true, big)
print(f"  knife-edge |Δyoy|<25bps         {hs:.0f}%  (n={ns})")
print(f"  decisive   |Δyoy|>=25bps        {hb:.0f}%  (n={nb})")

# miss decomposition
miss = base_idx[(np.sign(pred.reindex(base_idx)) != np.sign(true.reindex(base_idx)))]
print(f"\n  of {len(miss)} misses: {100*is_turn.reindex(miss).fillna(False).mean():.0f}% at turns, "
      f"{100*(d_yoy.abs().reindex(miss)<0.25).mean():.0f}% knife-edge, "
      f"{100*(fc.abs().reindex(miss)<=lo).mean():.0f}% low-conviction")

# ---------------------------------------------------------------------------
# 2. capture signals — measured in q-1 (shift 1), voting on Δyoy direction of q
print(f"\n=== CAPTURE SIGNALS (own hit, then comp gated by conviction) ===")
sigs: dict[str, pd.Series] = {}
try:
    cf = qser("CFNAI", "1967-01-01")
    sigs["cfnai_level"] = np.sign(cf)                       # above/below trend
    sigs["cfnai_mom"] = np.sign(cf.diff())                  # activity accelerating
except Exception as e:  # noqa: BLE001
    print("cfnai fail", e)
try:
    cl = qser("ICSA", "1967-01-01")                          # initial claims, SA
    sigs["claims_mom"] = -np.sign(cl.diff())                # claims down -> growth up
    sigs["claims_yoy"] = -np.sign((cl / cl.shift(4) - 1))   # claims below yr-ago
except Exception as e:  # noqa: BLE001
    print("claims fail", e)
try:
    sigs["hours_mom"] = np.sign(qyoy("AWHAETP", "1965-01-01").diff())
except Exception as e:  # noqa: BLE001
    print("hours fail", e)
try:
    sigs["permits_mom"] = np.sign(qyoy("PERMIT").diff())
except Exception as e:  # noqa: BLE001
    print("permits fail", e)
try:
    cu = qser("T10Y3M", "1982-01-01")
    sigs["curve_lvl"] = np.sign(cu - cu.rolling(40).mean())
except Exception as e:  # noqa: BLE001
    print("curve fail", e)
try:
    sigs["indpro_mom"] = np.sign(qyoy("INDPRO").diff())
except Exception as e:  # noqa: BLE001
    print("indpro fail", e)
try:
    sigs["payems_mom"] = np.sign(qyoy("PAYEMS").diff())
except Exception as e:  # noqa: BLE001
    print("payems fail", e)
try:
    sl = qser("USSLIND", "1982-01-01")
    sigs["lead_mom"] = np.sign(sl.diff())
except Exception as e:  # noqa: BLE001
    print("sslind fail", e)

lowconv = base_idx[fc.abs().reindex(base_idx) <= lo]  # where comp is ambivalent
print(f"{'signal':16s} {'own hit':>8s} {'own@lowconv':>12s} {'gated hit':>10s} "
      f"{'gated 05+':>10s}   n")
results = []
for name, v in sigs.items():
    vp = v.shift(1)                                   # known at start of q
    own, n_own = hit(vp, true, base_idx)
    own_lc, _ = hit(vp, true, lowconv)
    # conviction-gated: comp when decisive, this signal when comp ambivalent
    gated = pred.copy()
    amb = fc.abs() <= lo
    gated[amb] = vp[amb]
    g, ng = hit(gated, true, base_idx)
    idx05 = base_idx[base_idx >= pd.Period("2005Q1", "Q")]
    g05, _ = hit(gated, true, idx05)
    results.append((name, own, own_lc, g, g05, n_own))
    print(f"{name:16s} {own:7.0f}% {own_lc:11.0f}% {g:9.0f}% {g05:9.0f}%  {n_own:4d}")

best = max(results, key=lambda r: r[3])
print(f"\nbest gated: {best[0]}  -> GDP hit {best[3]:.0f}% (comp alone {h0:.0f}%), "
      f"2005+ {best[4]:.0f}%")
print(f"implied joint quad if CPI axis ~70%: {best[3]*0.70/100:.0f}% "
      f"(comp-only joint ~{h0*0.70/100:.0f}%)")
