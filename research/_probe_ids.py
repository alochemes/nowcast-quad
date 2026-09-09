import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nowcast import fetch

CANDIDATES = {
    # user's HEYE list mapped to FRED
    "RSCCAS": "retail sales control group",
    "TOTALSA": "auto sales SAAR",
    "PSAVERT": "personal savings rate",
    "CES0500000003": "avg hourly earnings private",
    "AWHAETP": "avg weekly hours private",
    "UMCSENT": "UMich sentiment (CB confidence proxy)",
    "NEWORDER": "core capex orders",
    "AMTMNO": "factory orders (total mfg)",
    "PNRESCONS": "private nonres construction",
    "PRRESCONS": "private res construction",
    "BOPGSTB": "goods trade balance",
    # NY Fed completion
    "HSN1F": "new home sales",
    "WHLSLRIMSA": "wholesale inventories",
    "BUSINV": "business inventories",
    "RETAILIMSA": "retail inventories",
    "IR": "import price index",
    "IQ": "export price index",
    "PPIFIS": "PPI final demand",
    "PCEPI": "PCE price index",
    "PCEPILFE": "core PCE price index",
    # weekly block
    "ICSA": "initial claims (W)",
    "CCSA": "continued claims (W)",
    "WEI": "NY Fed weekly economic index (W)",
    "WGFUPUS2": "EIA gasoline product supplied (W)",
    # survey proxy
    "BACTSAMFRBDAL": "Dallas Fed mfg survey",
}

for sid, desc in CANDIDATES.items():
    try:
        s = fetch.get_series(sid, start="2004-01-01", log=lambda m: None)
        freq = pd.infer_freq(s.index[-8:]) or "?"
        print(f"OK   {sid:16s} {desc:42s} {s.index[0].date()}..{s.index[-1].date()} n={len(s)} freq~{freq}")
    except Exception as e:
        print(f"FAIL {sid:16s} {desc:42s} {str(e)[:80]}")
