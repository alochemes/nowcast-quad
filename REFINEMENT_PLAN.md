# Model Refinement Plan

Grounded in the real-time vintage backtest (2018Q1–2026Q1, 33 quarters, day
before each advance GDP release; see `output/backtest/backtest_report.html`).

## Where we stand

| Model | RMSE ex-2020 (pp SAAR) | y/y direction accuracy |
|---|---|---|
| Atlanta Fed GDPNow (final) | 1.00 | 85% |
| NY Fed Staff Nowcast (final) | 1.40 | — |
| St. Louis Fed ENI | 2.28 | — |
| **Ours (16-series DFM)** | **2.50** | **70%** |

CPI is already competitive: y/y RMSE 0.164pp vs Cleveland Fed's 0.188pp at the
same stance (88 months, pseudo-real-time caveat).

## Why GDPNow is tighter — diagnosis

1. **Trade & inventories blindness (the dominant error).** Our error
   correlates **−0.57** with the net-exports+inventories contribution. The
   worst misses are exactly the import-surge/inventory-swing quarters: 2022Q1
   (+6.6pp), 2022Q2 (+4.5), 2022Q3/Q4 (−4.3), 2025Q1 (+4.4, tariff
   front-running). GDPNow forecasts these components explicitly from the FT900
   trade report and inventories releases; a common factor extracted from
   monthly activity data cannot see them (they are demand-composition shifts,
   not activity shifts).
2. **Nominal-real confusion.** RSAFS, DGORDER, BOPTEXP/IMP, TTLCONS enter
   nominal. In 2021–2026 inflation, nominal momentum overstated real activity.
3. **Component accounting.** GDPNow mimics BEA's chain-weighted bookkeeping for
   13 subcomponents; we map one latent factor to aggregate growth.
4. **Panel breadth/curation.** NY Fed uses a similar DFM but with a larger,
   curated panel and years of tuning — its 1.40 vs our 2.50 shows the DFM
   class itself is not the ceiling.

## Refinements, ordered by expected value

1. **PCE anchor (component hybrid, biggest win).** Monthly real PCE (PCEC96)
   *is* the consumption component (~68% of GDP). Accumulate it directly into a
   quarterly PCE contribution (BEA-style), and let the DFM handle only the
   non-PCE remainder. GDPNow's accuracy largely comes from this bookkeeping.
2. **Net exports + inventories bridge.** Add real goods trade (deflate BOPTEXP
   / BOPTIMP with BLS import/export price indexes IR/IQ) and inventories
   (WHLSLRIMSA, RETAILIMSA, BUSINV — deflated) as explicit contribution
   bridges, not factor inputs. Target the −0.57 correlation directly.
3. **Deflate remaining nominal panel series** (retail via CPI, durables via
   PPI, construction via construction PPI).
4. **Add high-signal monthly series** the Feds use: initial claims (ICSA),
   light vehicle sales (TOTALSA), real manufacturing & trade sales (CMRMTSPL),
   core capital goods shipments (AMDMVS), IP manufacturing (IPMAN).
5. **Within-quarter dynamics.** Track nowcast evolution as data arrives
   (res.news() decomposition); publish revision attribution in the report.
6. **Spec search under the vintage harness.** The backtest is now cheap to run
   (vintages cached); grid the factor structure (block counts, orders, sample
   start) and select on ex-2020 RMSE + direction accuracy, not in-sample fit.
7. **CPI (minor).** Oil futures curve instead of random walk for the
   out-month; food-at-home split; explicit non-gasoline energy leg
   (electricity/piped gas).

Note for the quad use-case: SAAR precision matters less than the *sign* of the
y/y rate-of-change. Refinements 1–2 should close most of the 70%→85%
direction-accuracy gap because the big sign flips came from trade-driven
quarters.
