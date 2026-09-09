"""Series definitions and model settings.

GDP panel follows the NY Fed Staff Nowcast spec (Bok et al., SR830): monthly
indicators in Labor/Real/Soft blocks plus a Global factor, quarterly real GDP
linked via Mariano-Murasawa aggregation inside statsmodels DynamicFactorMQ.
Transforms: 'chg' = first difference, 'pch' = percent change, 'lin' = level.
"""

SAMPLE_START = "2000-01-01"

# FRED id -> (transform, factor block, native frequency)
# transform: chg=diff, pch=100*dlog, lin=level; block None = Global loading only
# frequency: M monthly, W weekly (aggregated to monthly means, partial months kept)
SERIES_META = {
    # --- baseline panel (NY Fed style core) ---
    "PAYEMS":            ("chg", "Labor", "M"),   # payroll employment
    "UNRATE":            ("chg", "Labor", "M"),   # unemployment rate
    "JTSJOL":            ("chg", "Labor", "M"),   # job openings
    "INDPRO":            ("pch", "Real", "M"),    # industrial production
    "TCU":               ("chg", "Real", "M"),    # capacity utilization
    "DGORDER":           ("pch", "Real", "M"),    # durable goods orders
    "RSAFS":             ("pch", "Real", "M"),    # retail sales
    "HOUST":             ("pch", "Real", "M"),    # housing starts
    "PERMIT":            ("chg", "Real", "M"),    # building permits
    "DSPIC96":           ("pch", "Real", "M"),    # real disposable income
    "PCEC96":            ("pch", "Real", "M"),    # real PCE (monthly)
    "BOPTEXP":           ("pch", "Real", "M"),    # exports
    "BOPTIMP":           ("pch", "Real", "M"),    # imports
    "TTLCONS":           ("pch", "Real", "M"),    # construction spending
    "GACDISA066MSFRBNY": ("lin", "Soft", "M"),    # Empire State mfg survey
    "GACDFSA066MSFRBPHI": ("lin", "Soft", "M"),   # Philly Fed mfg survey
    # --- NY Fed completion: inventories, home sales, price block ---
    "WHLSLRIMSA":        ("pch", "Real", "M"),    # wholesale inventories
    "BUSINV":            ("pch", "Real", "M"),    # business inventories
    "RETAILIMSA":        ("pch", "Real", "M"),    # retail inventories
    "HSN1F":             ("pch", "Real", "M"),    # new home sales
    "CPIAUCSL":          ("pch", None, "M"),      # CPI (Global only, NY Fed style)
    "CPILFESL":          ("pch", None, "M"),      # core CPI
    "PCEPI":             ("pch", None, "M"),      # PCE prices
    "PCEPILFE":          ("pch", None, "M"),      # core PCE prices
    "PPIFIS":            ("pch", None, "M"),      # PPI final demand
    "IR":                ("pch", None, "M"),      # import prices
    "IQ":                ("pch", None, "M"),      # export prices
    # --- high-frequency / HEYE additions ---
    "ICSA":              ("pch", "Labor", "W"),   # initial claims
    "CCSA":              ("pch", "Labor", "W"),   # continued claims
    "WEI":               ("lin", "Real", "W"),    # NY Fed weekly economic index
    "TOTALSA":           ("pch", "Real", "M"),    # light vehicle sales
    "PSAVERT":           ("chg", "Real", "M"),    # personal savings rate
    "CES0500000003":     ("pch", "Labor", "M"),   # avg hourly earnings
    "AWHAETP":           ("chg", "Labor", "M"),   # avg weekly hours
    "UMCSENT":           ("chg", "Soft", "M"),    # UMich sentiment
    "NEWORDER":          ("pch", "Real", "M"),    # core capex orders
    "AMTMNO":            ("pch", "Real", "M"),    # factory orders
    "PNRESCONS":         ("pch", "Real", "M"),    # private nonres construction
    "PRRESCONS":         ("pch", "Real", "M"),    # private res construction
    "RSCCAS":            ("pch", "Real", "M"),    # retail sales control group
    "BOPGSTB":           ("chg", "Real", "M"),    # goods trade balance (signed)
    "BACTSAMFRBDAL":     ("lin", "Soft", "M"),    # Dallas Fed mfg survey
}

_BASELINE = ["PAYEMS", "UNRATE", "JTSJOL", "INDPRO", "TCU", "DGORDER", "RSAFS",
             "HOUST", "PERMIT", "DSPIC96", "PCEC96", "BOPTEXP", "BOPTIMP",
             "TTLCONS", "GACDISA066MSFRBNY", "GACDFSA066MSFRBPHI"]
_NYFED_ADD = ["WHLSLRIMSA", "BUSINV", "RETAILIMSA", "HSN1F", "CPIAUCSL",
              "CPILFESL", "PCEPI", "PCEPILFE", "PPIFIS", "IR", "IQ"]
_HF_ADD = ["ICSA", "CCSA", "WEI", "TOTALSA", "PSAVERT", "CES0500000003",
           "AWHAETP", "UMCSENT", "NEWORDER", "AMTMNO", "PNRESCONS",
           "PRRESCONS", "RSCCAS", "BOPGSTB", "BACTSAMFRBDAL"]

PANELS = {
    "baseline": _BASELINE,
    "nyfed_full": _BASELINE + _NYFED_ADD,
    "hf": _BASELINE + _NYFED_ADD + _HF_ADD,
}
# hf won the 2018-2026 vintage backtest: RMSE 2.35 vs 2.50 (baseline) / 3.00
# (nyfed_full), direction 76% vs 70% / 76% — see output/backtest/hf_indicator_report.html
ACTIVE_PANEL = "hf"

# backward-compatible view of the active panel used by gdp.py
GDP_MONTHLY_PANEL = {sid: SERIES_META[sid][:2] for sid in PANELS[ACTIVE_PANEL]}

GDP_QUARTERLY_SERIES = "GDPC1"   # real GDP, chained dollars, SA

# Outliers beyond this many IQRs from the median become missing (FRED-MD
# convention) — keeps COVID-scale observations from destabilizing the EM.
OUTLIER_IQR_K = 10.0

# CPI component series (all SA monthly indexes), weekly gasoline, daily Brent.
CPI_HEADLINE = "CPIAUCSL"
CPI_CORE = "CPILFESL"          # all items less food & energy
CPI_FOOD = "CPIUFDSL"          # food
CPI_GASOLINE = "CUSR0000SETB01"  # CPI gasoline (all types), SA
GAS_WEEKLY = "GASREGW"         # EIA weekly retail regular gasoline, $/gal (NSA)
CPI_BRENT = "DCOILBRENTEU"     # Brent spot, daily (Cleveland Fed's oil input)

GAS_REG_WINDOW = 60   # months, gasoline-on-oil levels regression (Cleveland spec)
AGG_WINDOW = 24       # months, headline-on-components aggregation regression

# Out-quarter projection: y/y adjusts inversely to the change in the 2-year
# comparative base ("comps", Hedgeye base-effect model); pass-through factor
# per series, OLS-calibrated on 1960/1985+ samples (see
# output/backtest/base_effects_report.html): GDP ~0.33-0.62 -> keep 0.5;
# CPI 0.56-0.88 -> 0.7.
BASE_EFFECT_K = 0.5        # GDP (and default)
BASE_EFFECT_K_CPI = 0.7
N_OUT_QUARTERS = 2       # comp-model quarters beyond the nowcast quarter
N_TRAILING_QUARTERS = 8  # realized quarters shown on the quad map

BENCHMARK_GDPNOW = "GDPNOW"  # Atlanta Fed GDPNow (q/q SAAR)

# Approved ensemble (2026-07-14): current-quarter q/q SAAR = w·DFM + (1-w)·GDPNow.
# Vintage backtest 2018-2026 ex-2020: RMSE 0.92pp (vs 1.00 pure GDPNow),
# direction 83%; optimum flat across w in 0.05-0.25. Falls back to pure DFM
# whenever GDPNow is unavailable or doesn't target the same quarter.
ENSEMBLE_ENABLED = True
ENSEMBLE_W_OURS = 0.15
