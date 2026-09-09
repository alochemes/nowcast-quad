# Adopted Configuration — US Growth/Inflation Quad Nowcast

Approved 2026-07-14. This document is the authoritative record of what the
system runs, why, and on what schedule. Supersedes nothing; PLAN.md holds the
original methodology research, REFINEMENT_PLAN.md the forward roadmap.

## 1. What we are moving forward with

**Growth (x-axis input).** Current-quarter real GDP q/q SAAR =
**0.15 · our DFM + 0.85 · Atlanta Fed GDPNow**, converted to YoY via implied
levels on realized GDPC1 history.
- Our DFM: `statsmodels DynamicFactorMQ`, **hf panel — 42 series** (16-series
  NY Fed-style core + inventories/home-sales/price block + weekly claims,
  continued claims, NY Fed WEI + the HEYE-list monthly indicators + Dallas Fed
  survey), Global + Labor/Real/Soft factor blocks, 10×IQR outlier removal,
  spec retry ladder Global(2)→Global(1)→no-idio-AR1.
- **Reproducibility (fixed 2026-07-29).** The factor blocks are now passed to
  statsmodels in **sorted** order. They came from a set comprehension, and set
  order for strings is randomized per Python process, which silently reordered
  the factor blocks on every run: four processes over one identical panel gave
  llf −14808, −14886 (×2) and an overflow crash, i.e. a different EM solution
  (sometimes a diverging one) each time. Sorted order is bitwise reproducible
  run-to-run and ~3× faster to fit. This was the cause of the two 2026-07-27
  runs disagreeing (DFM +3.91 vs +4.48 SAAR) on identical cached data.
- Ensemble fallback: pure DFM whenever GDPNow is unavailable or targets a
  different quarter. Later unreleased quarters keep the DFM's own q/q path,
  rebased on the blended current-quarter level.
- Rejected on evidence: NY Fed Staff Nowcast as third member (optimizer weight
  = 0), St. Louis ENI (optional +0.06pp, not worth the dependency).

**Inflation (y-axis input).** Our Cleveland-Fed-replica CPI model, **unblended**
(beats the Cleveland Fed's own nowcast head-to-head; blending only hurt).
Quarterly CPI YoY = average of monthly YoY readings.

**Out-quarters.** Comparative base-effect projection (2-year comps), +2
quarters beyond the nowcast quarter. Pass-through K is OLS-calibrated per
series (base_effects_report.html): **GDP 0.5, CPI 0.7**. The comp signal is
used ONLY for out-quarters — the tie-breaker experiment showed it subtracts
accuracy when allowed to override current-quarter ensemble calls.

**Quads.** Hedgeye GIP convention: x = Δ headline CPI YoY (bps vs prior
quarter), y = Δ real GDP YoY (bps); Quad 1 top-left (G↑ I↓, Goldilocks),
Quad 2 top-right (Reflation), Quad 3 bottom-right (Stagflation), Quad 4
bottom-left (Deflation). Ties (Δ = 0) count as deceleration.

## 2. Evidence basis (real-time vintage backtests, day before advance release)

| Component | Metric | Result |
|---|---|---|
| Ensemble GDP (w=0.15) | RMSE ex-2020, 29 qtrs | **0.92pp** (pure GDPNow 1.00, pure DFM 2.35) |
| Ensemble GDP | y/y direction accuracy | **83%** (= GDPNow, DFM alone 76%) |
| Weight robustness | RMSE within 5% of optimum | w ∈ 0.05–0.25 (flat bowl) |
| CPI model | y/y RMSE, 88 months | **0.164pp** (Cleveland Fed 0.188pp) |

Full detail: `output/backtest/backtest_report.html` (baseline),
`hf_indicator_report.html` (panel selection + indicator screen),
`ensemble_sensitivity.html` (weights, 3-model surfaces, CPI blend).
Direction numbers are vintage-honest (real-time GDP levels), not
revised-history approximations.

## 3. Scheduling protocol

**Automated run:** Windows Task Scheduler job **`NowcastQuad`**, **Mondays
11:00 ET** (moved from 08:30 on 2026-07-16 — machine typically off early
Monday), executing `.venv\Scripts\python.exe run_nowcast.py --skip-if-fresh 20`
in the repo root, 30-minute execution limit, `StartWhenAvailable` (a missed
Monday runs at next logon/boot).

**Catch-up after travel:** task **`NowcastQuadCatchUp`** fires at user logon
(2-minute delay) and runs `run_if_stale.ps1`, which asks whether a run has
succeeded since the most recent scheduled slot (Monday 11:00). If yes it is a
no-op; if no it runs the full nowcast immediately. A machine that was off for
weeks refreshes itself within minutes of the first logon.

**Why the catch-up is schedule-anchored, not age-based (fixed 2026-09-09):**
an age threshold failed in both directions and was retuned twice before being
removed.
- At **6 days** (before 2026-07-29) it fired below the 7-day cadence: on
  2026-07-27 a Monday logon at 11:15 saw a 7.0-day-old run and started the
  pipeline, then the missed 11:00 weekly trigger fired at 11:22 — two runs,
  two emails, six minutes apart.
- At **8 days** (2026-07-29 → 2026-09-09) it could never cover a missed weekly
  run at all, because a same-day logon only ever sees a ~7.1-day-old run. On
  2026-09-09 the PC was off at Monday 11:00 and booted 13:46; the weekly task
  recorded the miss and rolled to the following Monday without running
  (`StartWhenAvailable` did not catch up — cause unproven, the
  `Microsoft-Windows-TaskScheduler/Operational` log was disabled), the
  catch-up ran at 14:14, measured 7.13 days ≤ 8, and skipped. The nowcast went
  9 days stale until the watchdog alerted on 2026-09-09.

`run_if_stale.ps1` now runs iff no `run OK` is newer than the most recent
Monday 11:00, which has neither failure mode and nothing to tune. It also
skips if a run started under 30 minutes ago, so a logon seconds after the
weekly task starts cannot launch a concurrent second run. Both tasks still
pass `--skip-if-fresh 20` as a backstop: `run_nowcast.py` exits without
running or notifying when the last success is under 20 hours old (`--force`
overrides; a bare manual run is never skipped).

Cadence rationale: Monday morning follows the weekly EIA gasoline survey and
claims week, precedes most monthly releases, and GDPNow updates ~6–7×/month —
a weekly pull keeps every input ≤1 week stale. CPI releases (mid-month) and
GDP advance releases (end of Jan/Apr/Jul/Oct) are picked up the following
Monday.

**Each run:** fetch fresh data (FRED API primary; DBnomics keyless fallback;
stale local cache as last resort — a network outage degrades, never crashes) →
nowcast GDP (DFM + ensemble) and CPI → quads → write outputs. Cache is
considered fresh for 6 hours; a scheduled run always refetches.

**Outputs per run (in `output/`):** `quad_map.png`, `report.html`
(levels/YoY/QoQ tables, quad map, CPI detail, model params, data vintages,
run meta incl. ensemble arithmetic), `nowcast.csv`, `levels.csv`, append-only
`run.log`. Exit code 0/1; if a CSV is locked (open in Excel) the run writes a
timestamped alternate instead of failing.

**Manual run:** `.venv\Scripts\python.exe run_nowcast.py` ·
**Force scheduled run:** `Start-ScheduledTask -TaskName NowcastQuad` ·
**Remove:** `Unregister-ScheduledTask -TaskName NowcastQuad -Confirm:$false`

**Failure signature:** LastTaskResult ≠ 0 on the task, `run FAILED` +
traceback in `output/run.log`.

### Monitoring (added 2026-07-14)

- **Per-run toast**: every run pops a Windows notification — green summary
  with the current quad call on success ("run OK — 2Q26E: Quad 3 ..."), red
  "run FAILED, see run.log" on failure (`notify.ps1`, called by
  `run_nowcast.py`; best-effort, never blocks the run).
- **Watchdog**: scheduled task **`NowcastQuadWatchdog`**, daily 09:00, runs
  `watchdog.ps1` — silent while healthy; toast alert if the last successful
  run is >8 days old, the most recent run failed, or the NowcastQuad task has
  been unregistered. Test the alert path anytime:
  `powershell -ExecutionPolicy Bypass -File watchdog.ps1 -TestAlert`;
  health check: `... watchdog.ps1 -VerboseCheck`.
- **Desktop shortcut**: "Quad Nowcast Report" on the Desktop opens
  `output/report.html`; the generated-timestamp in its header is the
  freshness check (should never be older than the most recent Monday).

## 4. Keys & dependencies

FRED API key: `private/config.yaml` (gitignored) or env `FRED_API_KEY`.
Norton TLS interception handled automatically (combined CA bundle built on
first SSL failure). `fred.stlouisfed.org` (website) is unreachable from this
machine — the system uses `api.stlouisfed.org` exclusively. Licensed series
(ISM, NFIB, Conference Board) are NOT in the live panel; free proxies are.

## 4b. The current quarter is the CALENDAR quarter (adopted 2026-08-03)

The report headlines the quarter the calendar says we are in, not the first
quarter BEA has yet to publish.

Those two differ for roughly the first month of every quarter — the gap
between a quarter ending and its advance GDP release. The old rule
(`first_estimate`, the earliest quarter without an actual) meant that through
all of July 2026 the headline read "2Q26E: Quad 3" for a quarter that had
already finished, while the market had long since moved on to 3Q26. Markets
look forward; the nowcast now does too.

What changed, in `pipeline.run`:

- `current_q = max(calendar quarter, first_estimate)` drives the headline, the
  highlighted point on the quad map, the notify payload and the email subject.
- `is_estimate` is **unchanged** — it still marks any quarter without a
  released actual, so during that first month both 2Q26 and 3Q26 show as
  estimates. The run log names the older ones explicitly.
- The base-effect extension now targets `current_q + N_OUT_QUARTERS` rather
  than two quarters past the DFM's own reach, so the calendar quarter always
  keeps its full set of out-quarters.
- Early in a quarter GDPNow is still estimating the *previous* one, so the
  headline quarter is often pure DFM. The run-details block says which
  ("current quarter (calendar)": `... — pure DFM (GDPNow still targets
  2026Q2)`), because a pure-DFM call carries more uncertainty than a blended
  one.

Side effect worth knowing: the headline quarter now rolls on calendar
boundaries (Jan/Apr/Jul/Oct 1) instead of on BEA release dates, which is also
what stops a roll from being mistaken for a quad change.

## 4c. Run history and the chart book (added 2026-08-03)

Every run appends its whole quad table to `output/history/quad_history.csv`
(`nowcast/history.py`), one row per (as-of date, quarter). Reading one
quarter's rows in date order shows how its call moved as data arrived.

Two charts are built from it and land in `report.html` (the ribbon also rides
in the email):

- **Ribbon** — one strip per quarter, colored by the quad being called on each
  date. The whole book at a glance.
- **Chart book** — one panel per quarter, x = run date, y = quad, with a flip
  count in each panel title. Panels stop about six weeks after a quarter goes
  actual, since a closed call only draws a flat line after that.

Colors are the quad-map colors, not a right/wrong scheme: while a quarter is
live there is no settled answer to score against, so the useful signal is
which quad it sat in and how steady it was.

**Backfill.** `research/replay_vintage_quads.py` reconstructs past runs from
ALFRED vintages — the 42-series panel, real GDP, and the GDPNow print actually
on the screen that day — then applies the same ensemble, base effects and quad
rules, with the calendar-quarter convention above. It is resumable and
idempotent per as-of date; roughly a minute per date on a cold vintage cache.
A three-year weekly backfill was run on 2026-08-03:

```
.venv\Scripts\python.exe research/replay_vintage_quads.py --start 2023-08-07
```

Replayed rows carry `source="replay"`; live runs carry `source="live"` and win
when both cover the same date.

## 4d. What the out-quarter call is worth (measured 2026-08-03)

From the 157-date weekly replay, scoring each quarter's call against the quad
it settled in once GDP was released (12 settled quarters):

| days before quarter end | on the settled quad |
|---|---|
| −210 to −150 | 20% |
| −120 to −90 | 27% |
| −60 to −30 | 18–25% |
| −10 | 58% |
| 0 (quarter close) | 67% |

**The out-quarter call is worth nothing.** Four quads means 25% by chance, and
the curve sits on that line from seven months out until roughly a month before
the quarter ends. Essentially all the information arrives in the final 30 days.

The cause is structural, not a tuning problem. The comp model sets

    d_yoy(t) = -K * (comp(t) - comp(t-1)),  comp(t) = (yoy(t-4) + yoy(t-8)) / 2

so the projected change for quarter T reads YoY at T−4/T−5/T−8/T−9 — all
settled long before T. The projected delta for T is therefore **identical
whether computed one quarter ahead or two** (verified to 8.9e-16 across 288
quarters by `research/base_effect_bias_by_era.py`). An out-quarter call cannot
update as the quarter approaches; it can only improve when the quarter enters
the DFM / CPI nowcast horizon, which is exactly where the curve turns up.

A second, regime-conditional weakness sits on top of it. Because the sign of
the projection is set entirely by which way the 2-year-ago comp is moving, a
large inflation shock — which takes about two years to traverse the comp
window — makes the projection one-signed for that whole passage:

| era | n | quad correct | CPI called accelerating | actual |
|---|---|---|---|---|
| 1975–1994 | 80 | 36% | 55% | 41% |
| 1995–2007 | 52 | 38% | 48% | 54% |
| 2008–2013 | 24 | 50% | 46% | 46% |
| 2014–2019 | 24 | 54% | 58% | 67% |
| 2022–2023H1 | 6 | 17% | 0% | 33% |
| 2023H2–2025 | 10 | 30% | 80% | 50% |

The two recent windows fail in *opposite* directions — comps rising off the
COVID base made the model call deceleration every quarter, comps falling off
the 2022 peak made it call acceleration every quarter. Pre-2022, across 180
quarters, it beats chance in every era. So this is not a bug in the sign; it
is that the input trends one way for years after a shock.

**How to read the report given this.** Treat the two out-quarters as a
base-effects arithmetic exercise — which is what they are — not as a forecast.
The current-quarter call is the one with information in it, and even that is
only ~67% at quarter close. `research/base_effect_bias_by_era.py` reproduces
the era table; it runs on revised history and is a diagnostic of the
projection's mechanics, **not** a performance backtest.

## 5. Change control

Model changes should clear the vintage backtest harness first
(`research/backtest_gdp_vintage.py --panel <name>`, then
`research/hf_report.py`): adopt only on improvement in ex-2020 RMSE *and*
direction accuracy. Ensemble weight lives in `nowcast/config.py`
(`ENSEMBLE_W_OURS`); the backtested-safe band is 0.05–0.25.
