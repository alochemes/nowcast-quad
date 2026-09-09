# nowcast-quad

A self-running US **growth and inflation nowcaster**. Every week it pulls fresh
public data, estimates where real GDP and CPI are *right now* (before the
official numbers exist), works out whether each is speeding up or slowing down,
plots the result on a four-quadrant map, and emails you the change.

It is built to run unattended on a machine you already own, and to tell you
when it *stops* running — the failure mode that quietly ruins most personal
data pipelines.

> Not investment advice. This is a forecasting tool built from public data; it
> is wrong regularly, and it is designed to tell you *how* wrong it has been.

---

## What a "quad" is

The quad map plots the **rate of change** of two things, not their levels:

- **x-axis** — change in headline CPI year-over-year, in basis points vs the prior quarter
- **y-axis** — change in real GDP year-over-year, in basis points vs the prior quarter

That gives four regimes. This is the Hedgeye GIP (Growth/Inflation/Policy)
convention; the numbering below is theirs, and the code follows it exactly:

| Quad | Growth | Inflation | Name |
|---|---|---|---|
| 1 | accelerating | decelerating | Goldilocks |
| 2 | accelerating | accelerating | Reflation |
| 3 | decelerating | accelerating | Stagflation |
| 4 | decelerating | decelerating | Deflation |

The point is the **direction of the second derivative**, which is why a quarter
can sit in "Deflation" while inflation is still 3.3% — what matters is that
3.3% is lower than last quarter's.

**Read the distance from the axes, not just the label.** A quarter whose growth
change is +0.1 bps is on the line, not in a quadrant; the classifier uses a
strict `> 0` test, so a rounding-scale move flips the name. Treat a near-axis
call as "flat", and look at `d_gdp_bps` / `d_cpi_bps` in `nowcast.csv` before
believing a regime change.

---

## How the numbers are produced

**Real GDP** — a mixed-frequency dynamic factor model (`statsmodels`
`DynamicFactorMQ`), following the NY Fed Staff Nowcast design (Bok et al.,
SR830). 42 monthly and weekly indicators load onto Labor / Real / Soft factor
blocks plus a global factor; quarterly real GDP is linked by Mariano-Murasawa
aggregation. The panel and its transforms live in `nowcast/config.py`.

That model alone is *worse* than the Atlanta Fed's GDPNow, and the code says so
rather than pretending otherwise. So the shipped current-quarter number is an
**ensemble**:

```
q/q SAAR = 0.15 x (our DFM)  +  0.85 x GDPNow
```

Vintage backtest 2018-2026 excluding 2020: RMSE **0.92pp** vs 1.00pp for pure
GDPNow, direction 83%. The optimum is flat for weights between 0.05 and 0.25 —
the small DFM weight adds a little, and claiming more would be overfitting. If
GDPNow is unavailable or targets a different quarter, it falls back to the pure
DFM automatically.

**CPI** — a component model in the Cleveland Fed style: core, food and gasoline
are nowcast separately, then a 24-month regression aggregates them to headline.
Gasoline is modelled on Brent with an AR(1) gap. Backtest y/y RMSE **0.164pp**
vs the Cleveland Fed's 0.188pp over 88 months (pseudo-real-time, so read that
edge charitably).

**Out-quarters** — the two quarters past the nowcast are projected with a
base-effect model: year-over-year adjusts inversely to the change in the
two-year comparative base, with an OLS-calibrated pass-through (0.5 for GDP,
0.7 for CPI). These are labelled `E` on the chart and are genuinely weaker than
the current-quarter nowcast.

**Honest scoreboard** (2018Q1-2026Q1 vintage backtest, from `REFINEMENT_PLAN.md`):

| Model | RMSE ex-2020 (pp SAAR) | y/y direction |
|---|---|---|
| Atlanta Fed GDPNow (final) | 1.00 | 85% |
| NY Fed Staff Nowcast (final) | 1.40 | — |
| St. Louis Fed ENI | 2.28 | — |
| This DFM alone (16-series) | 2.50 | 70% |
| This DFM alone (42-series "hf") | 2.35 | 76% |
| **Shipped ensemble** | **0.92** | **83%** |

---

## Quick start

Requires **Python 3.12+**. Windows, macOS and Linux all work; only the Task
Scheduler scripts are Windows-specific, and there is a cron path below.

```bash
git clone https://github.com/alochemes/nowcast-quad.git
cd nowcast-quad

python -m venv .venv
# Windows:   .venv\Scripts\activate
# mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Get a **free FRED API key** at <https://fredaccount.stlouisfed.org/apikeys>,
then:

```bash
mkdir private
cp config.example.yaml private/config.yaml
# edit private/config.yaml and paste the key
```

`private/` is gitignored. You can set `FRED_API_KEY` in the environment
instead. **Without any key it still runs** — the fetcher falls back to
DBnomics (no key required) for mapped series, then to the local cache in
`data_cache/`. A network outage degrades a run; it never crashes it.

Run it:

```bash
python run_nowcast.py
```

The first run takes roughly 2-5 minutes, most of it the EM fit of the factor
model. Later runs reuse cached data wherever FRED has nothing new.

### What you get in `output/`

| File | What it is |
|---|---|
| `quad_map.png` | The quad chart: trailing quarters, the nowcast, and base-effect out-quarters (estimates marked `E`) |
| `report.html` | Self-contained report — chart, per-quarter table, run metadata. Opens offline |
| `nowcast.csv` | The quad table as data: `gdp_yoy`, `cpi_yoy`, `d_gdp_bps`, `d_cpi_bps`, `quad`, `quad_name`, `is_estimate` |
| `quad_ribbon.png` | One strip per quarter, coloured by which quad was being called on each date — shows how stable the call has been |
| `quad_chartbook.png` | Per-quarter panels: x = days before/after that quarter ended, y = the quad, with a flip count |
| `history/quad_history.csv` | Every run's full table, one row per (as-of date, quarter) |
| `run.log` | Append-only log. The scheduling and monitoring scripts read this file, so do not delete it |

The headline quarter is **the quarter the calendar says you are in**, not the
first one the BEA has yet to publish. Those differ for about the first month of
each quarter, and the live one is the tradeable one. See
`ADOPTED_CONFIGURATION.md` section 4b.

---

## Email reminders and run history

This is the part that makes it a *system* rather than a script. After every run
the pipeline posts a status payload to two optional, independent channels. Set
either, both, or neither — each is best-effort and can never fail a run.

### Google Apps Script: email + a run-history spreadsheet

Full walkthrough in **[SETUP_NOTIFICATIONS.md](SETUP_NOTIFICATIONS.md)**, about
five minutes:

1. Create a Google Sheet, open **Extensions -> Apps Script**, and paste all of
   `nowcast_notifier.gs`.
2. **Edit the `EMAIL` constant at the top** to your own address.
3. Deploy as a **Web app** (execute as *Me*, access *Anyone with the link*) and
   put the resulting `/exec` URL into `notify.webapp_url` in
   `private/config.yaml`.
4. Add a **time-driven daily trigger** on the `dailyStalenessCheck` function.

You then get:

- a **success email** after each run, with the chart inline, the quad call, and
  a plain-language diff against the previous run ("GDP YoY: 2.25% -> 2.31%,
  +6 bps") so you can read it on a phone without opening anything;
- a **failure email** carrying the tail of the traceback;
- a row appended to a `runs` sheet on every run, giving you a permanent history
  you can chart yourself. Bulky fields (inline chart, attached report) are
  deliberately *not* written to the sheet.

### Slack

Put an incoming-webhook URL in `notify.slack_webhook`. Same payload, no setup
beyond creating the webhook.

### The dead-man switch — the part people forget

A watchdog running *on the same machine as the job* cannot tell you the machine
is off. So monitoring is deliberately split in two:

- **`watchdog.ps1`** (local, daily) — raises a desktop toast if the last run
  failed, or if no run has succeeded in over 8 days.
- **`dailyStalenessCheck`** (in Apps Script, off-machine) — emails you if the
  sheet has had no new row for `STALE_DAYS`. This fires **even if your PC is
  off, asleep, or the scheduled task was deleted.**

Set up the second one. It is the only thing that catches total failure.

---

## Running it on a schedule

### Windows (Task Scheduler)

```powershell
powershell -ExecutionPolicy Bypass -File schedule_task.ps1
```

Registers **`NowcastQuad`**, Mondays 11:00 local. Remove it with
`Unregister-ScheduledTask -TaskName NowcastQuad`. Optionally also register
`run_if_stale.ps1` at logon and `watchdog.ps1` daily — see
`ADOPTED_CONFIGURATION.md` section 3.

### macOS / Linux (cron)

Do not schedule the pipeline directly. Point a frequent cron entry at the
catch-up runner, which decides for itself whether anything is due:

```cron
*/30 * * * * cd /path/to/nowcast-quad && .venv/bin/python run_if_stale.py
```

`run_if_stale.py --day 0 --hour 11` (Monday = 0) is the cross-platform twin of
`run_if_stale.ps1`; both make identical decisions.

### Why the catch-up logic is shaped the way it is

Worth understanding before copying it, because the obvious design is wrong.

The natural approach — *"run if the last success is more than N days old"* —
cannot be tuned correctly against a 7-day cadence, and this repo shipped both
failure modes before arriving at the current design:

- **N = 6.** Fires *below* the cadence. A Monday check at 11:15 sees a
  7.0-day-old run and starts the pipeline; the missed 11:00 weekly trigger then
  fires at 11:22. Two runs, two emails, six minutes apart.
- **N = 8.** Can never cover a missed weekly run *at all*, because a same-day
  check only ever sees a roughly 7.1-day-old run. Observed 2026-09-07: the PC
  was off at 11:00 and booted at 13:46, Windows recorded the miss and rolled to
  the following Monday without running, and the catch-up at 14:14 measured 7.13
  days, called it fresh, and skipped. The nowcast went nine days stale.

No single threshold satisfies both constraints: it has to be under 7 days to
cover a missed run and over 7 days to avoid pre-empting the weekly trigger.

The fix is to stop measuring age and **anchor to the schedule**: *has a run
succeeded since the most recent Monday 11:00?* No parameter, no drift, neither
failure mode. Both runners additionally skip if a run started in the last 30
minutes, so a check landing seconds after the weekly job starts cannot launch a
concurrent second run, and `run_nowcast.py --skip-if-fresh 20` is a final
backstop that refuses to run or notify when the last success is under 20 hours
old (`--force` overrides; a bare manual run is never skipped).

---

## Backfilling history

`output/history/quad_history.csv` only grows from the day you start running it.
To reconstruct the past, replay from ALFRED vintages — the panel, real GDP and
the GDPNow print exactly as they stood on each historical date:

```bash
python research/replay_vintage_quads.py --start 2023-08-07
```

Resumable and idempotent per as-of date, so it can be stopped and restarted.
Budget about a minute per date against a cold vintage cache.

---

## Configuration

| What | Where |
|---|---|
| FRED key, notification URLs | `private/config.yaml` (gitignored; see `config.example.yaml`) |
| Series panel, transforms, factor blocks | `nowcast/config.py` -> `SERIES_META`, `PANELS`, `ACTIVE_PANEL` |
| Ensemble weight | `nowcast/config.py` -> `ENSEMBLE_W_OURS` |
| Base-effect pass-through | `nowcast/config.py` -> `BASE_EFFECT_K`, `BASE_EFFECT_K_CPI` |
| Chart window | `nowcast/config.py` -> `N_TRAILING_QUARTERS`, `N_OUT_QUARTERS` |
| Email recipient, stale threshold | `nowcast_notifier.gs` -> `EMAIL`, `STALE_DAYS` |

Three panels ship: `baseline` (16 series), `nyfed_full` (27), and `hf` (42, the
default — it won the vintage backtest at RMSE 2.35 against 2.50 and 3.00).

---

## Tests

```bash
python -m pytest tests -q
```

Covers the quad classifier, fetch retry and fallback behaviour, history and
notification payload assembly, and an end-to-end pipeline smoke test.

On a **fresh clone with no FRED key and no warm cache**, expect `29 passed, 4
errors`: the four in `test_pipeline_smoke.py` fetch real data and fail with
`all sources failed and no cache`. That is the environment, not a broken
checkout. Configure a key (or run `python run_nowcast.py` once to populate
`data_cache/`) and the full suite passes 33/33.

---

## Troubleshooting

**TLS/SSL failures on every fetch.** Antivirus products and corporate proxies
intercept HTTPS, and `certifi`'s bundle alone then fails. Point
`NODE_EXTRA_CA_CERTS` at your interceptor's root certificate;
`nowcast/fetch.py` detects the SSL error and builds a combined bundle (certifi
plus that cert) automatically on retry.

**`no FRED API key`.** Set `FRED_API_KEY`, or `api_key.FRED` in
`private/config.yaml`. Runs degrade to DBnomics and then to cache without one,
so this is a warning path rather than a hard stop.

**A scheduled run silently did not happen (Windows).** Windows can record a
missed trigger and roll to the next occurrence without running it, leaving no
trace by default. Enable the log first, from an **elevated** PowerShell:

```powershell
wevtutil sl "Microsoft-Windows-TaskScheduler/Operational" /e:true
```

Then check `Get-ScheduledTaskInfo -TaskName NowcastQuad` for
`NumberOfMissedRuns`. The logon/cron catch-up covers this case regardless.

**Two emails in one week.** A run started while another was in flight — see the
scheduling section above; the shipped design prevents it.

---

## Repo layout

```
nowcast/              model + pipeline
  config.py             series panel, transforms, model settings
  fetch.py              FRED/ALFRED + DBnomics + cache, TLS fallback
  gdp.py                DynamicFactorMQ nowcast + GDPNow ensemble
  inflation.py          Cleveland-Fed-style CPI component model
  baseeffects.py        out-quarter projection from comparative bases
  quads.py              rate-of-change -> quad assignment
  pipeline.py           orchestration
  report.py             chart + self-contained HTML report
  history.py            per-run history append
  vintage.py            point-in-time (ALFRED) data access
  notify_remote.py      Apps Script + Slack push
research/             backtests and model-selection studies
tests/                pytest suite
run_nowcast.py        one run (entry point)
run_if_stale.py       schedule-anchored catch-up (cron, cross-platform)
run_if_stale.ps1      same logic for Windows logon
schedule_task.ps1     register the weekly Task Scheduler job
watchdog.ps1          local daily staleness/failure toast
notify.ps1            Windows toast helper
nowcast_notifier.gs   Google Apps Script: email + run-history sheet
```

Deeper reading: **`PLAN.md`** (methodology and sources),
**`ADOPTED_CONFIGURATION.md`** (what was adopted and why, plus the full
scheduling and monitoring protocol), **`REFINEMENT_PLAN.md`** (benchmark
diagnosis and what would improve the model next).

## License

MIT — see [LICENSE](LICENSE).
