# Nowcast Quad — Research Summary & Rebuild Plan

Goal: an autonomous system that nowcasts US real GDP growth and CPI inflation,
computes their **rate of change** (acceleration/deceleration), and renders the
result in the four-quadrant "quad" format for visual inspection.

## 1. How the reference systems work (research findings)

### GDP nowcasting

**Atlanta Fed GDPNow** (Higgins 2014, WP 2014-7) is a bottom-up *tracking
model*: it forecasts 13 GDP subcomponents with a BVAR, extracts a single
dynamic factor from ~124 monthly series to fill in unreported months
(factor-augmented autoregressions), then maps monthly source data to
subcomponents with *bridge equations* and aggregates with BEA chain-weighting.
Its current estimate is published as FRED series `GDPNOW` (q/q SAAR) — we use
it as a benchmark rather than rebuilding its 13-component plumbing.

**NY Fed Staff Nowcast** (Bok et al., SR830) is a mixed-frequency **dynamic
factor model**: ~25 monthly indicators + quarterly real GDP, one Global factor
plus Labor/Real/Soft block factors, AR(1) idiosyncratic errors, estimated by
EM + Kalman smoother (Bańbura–Modugno 2014). Quarterly GDP is linked to a
latent monthly growth rate via Mariano–Murasawa [1,2,3,2,1] aggregation. The
Kalman filter handles ragged-edge missing data natively — that is the whole
trick of nowcasting with it.

**Publicly available rebuild**: `statsmodels.tsa.statespace.DynamicFactorMQ`
implements exactly this (mixed M/Q frequencies, EM, block factors, news
decomposition). Chad Fulton's official statsmodels example replicates the NY
Fed model on FRED-MD data. → We rebuild the NY Fed approach, not GDPNow.

### Inflation nowcasting

**Cleveland Fed inflation nowcast** (Knotek & Zaman 2017, JMCB) is a small
component model, not a factor model:
- core CPI and food CPI m/m: 12-month moving averages (recursive);
- gasoline: monthly-averaged EIA weekly retail price (partial months included)
  regressed on monthly Brent in *levels* (rolling 60m), AR(1) on the gap for
  the pass-through lag, oil extended one month as a random walk; NSA m/m
  converted to SA with an empirical 3-year same-month seasonal factor;
- headline: rolling 24-month OLS of headline m/m on the three components
  (the regression absorbs non-gasoline energy, ~3.3% of the basket);
- months beyond the gasoline horizon: headline falls back to its own 12m MA.
Real-time RMSE on y/y CPI: ~0.19pp mid-month. Their published nowcast history
is downloadable JSON (benchmark). → We rebuild this recipe directly.

### The quad format (Hedgeye GIP model)

- Growth = real GDP **YoY %** by quarter; Inflation = headline CPI **YoY %,
  quarterly average of monthly YoY readings**.
- A quarter's quad is set by the **sign of the change vs the prior quarter**
  (bps): Quad 1 growth↑ inflation↓ (Goldilocks, policy Neutral); Quad 2 both↑
  (Reflation, Hawkish); Quad 3 growth↓ inflation↑ (Stagflation, Constrained);
  Quad 4 both↓ (Deflation, Dovish).
- Chart layout (verified from Hedgeye decks): **x-axis = Δ CPI YoY (bps),
  y-axis = Δ GDP YoY (bps)**; Quad 1 top-left, 2 top-right, 3 bottom-right,
  4 bottom-left; trailing ~8 quarters + forward estimates drawn as a smoothed
  black path; historical labels in white boxes, estimates in black boxes with
  an "E" suffix.
- Out-quarters: Hedgeye adjusts YoY forecasts *inversely and proportionally to
  the marginal change in 2-year comparative base effects* ("comps").

## 2. Data (all public)

Primary source: **FRED API** (`api.stlouisfed.org`, key in `private/config.yaml`).
Fallback: **DBnomics** (no key; BLS/BEA series mapped in `fetch.py`), then
stale local cache (`data_cache/`). Note: `fred.stlouisfed.org` (website CSV
endpoint) is unreachable from this machine; the API host works. Norton AV
intercepts TLS — `fetch.py` builds a combined CA bundle (certifi + the cert in
`NODE_EXTRA_CA_CERTS`) on first SSL failure.

- GDP panel: GDPC1 (quarterly) + 16 monthly indicators (PAYEMS, UNRATE,
  JTSJOL, INDPRO, TCU, DGORDER, RSAFS, HOUST, PERMIT, DSPIC96, PCEC96,
  BOPTEXP, BOPTIMP, TTLCONS, Empire & Philly Fed surveys) with NY Fed
  transforms (diff / 100·Δlog / level), sample from 2000, |z|>5 clipped
  (COVID stability).
- CPI: CPIAUCSL, CPILFESL, CPIUFDSL, CUSR0000SETB01 (all SA), GASREGW
  (weekly), DCOILBRENTEU (daily).
- Benchmark: GDPNOW.

## 3. Architecture

```
run_nowcast.py            entry point; logging; exit codes
nowcast/
  config.py               series lists, transforms, model settings
  fetch.py                FRED -> DBnomics -> stale-cache chain; CA handling
  gdp.py                  DynamicFactorMQ nowcast -> implied levels -> YoY
  inflation.py            Cleveland Fed component model -> monthly index -> YoY
  baseeffects.py          out-quarter YoY projection from 2Y comps (K=0.5)
  quads.py                delta-bps -> quad assignment
  report.py               quad map PNG (Hedgeye layout) + self-contained HTML
  pipeline.py             orchestration, benchmark check, CSV/meta outputs
tests/                    unit tests (quads, base effects) + integration smoke
```

Per run the system emits `output/quad_map.png`, `output/report.html`
(self-contained, table + chart + run metadata), `output/nowcast.csv`,
`output/run.log`.

## 4. Autonomy

- No interactive input; all keys/config on disk; every fetch cached so a
  network outage degrades to stale data instead of failing.
- Non-zero exit code on failure, append-only run.log.
- `schedule_task.ps1` registers a Windows Task Scheduler job (weekday morning
  run) — optional, run once by hand.

## 5. Test plan

1. Unit: quad assignment truth table incl. tie handling; base-effect math;
   quarter labels.
2. Integration: full pipeline run against live FRED; outputs exist and are
   fresh; nowcast values finite and within sane bounds (GDP YoY −5..8%, CPI
   YoY −2..10%).
3. Validation: (a) historical quads from pure actuals reproduce known regimes
   (2021 reflation = Quad 2, 2022 tightening = Quad 3→4, 2020Q2 = Quad 4);
   (b) model q/q SAAR nowcast within ~1.5pp of Atlanta Fed GDPNow; (c) CPI
   monthly nowcast within sanity range of recent realized m/m prints.

## 6. Out of scope for v1 (possible later)

- News decomposition of nowcast revisions (`res.news()` is available).
- Real-time vintage backtesting via ALFRED; Cleveland Fed JSON benchmarking.
- Policy (third) axis, non-US economies, monthly-resolution quads.
