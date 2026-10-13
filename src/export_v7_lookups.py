"""Version 7 lookups: adds each home's energy-certificate history, as of the valuation month, to the EPC address files
(epc_*.csv), so the dashboard and src/predict.py can fill the model's certificate-history inputs from an address.
Same definitions as src/features_v7.py, with the valuation month in place of the sale date."""
import json, pathlib, sys, numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from epc_match import load_epc
from features_v7 import epc_history, EPC_H
ROOT = pathlib.Path(__file__).resolve().parents[1]; D = ROOT / "outputs/dash2"
meta = {r["key"]: r["value"] for r in json.load(open(D / "model_meta.json"))}
t0 = pd.Timestamp(meta["valuation_month"] + "-01")
e = load_epc()
last = e.dropna(subset=["dwelling"]).sort_values("lodgement_date").groupby("dwelling").tail(1).copy()
# same address text as the EPC files (src/export_v6_extras.py)
last["address"] = (last.address1.fillna("") + ", " + last.address2.fillna("")).str.strip(", ").where(last.address2.notna(), last.address1.fillna(""))
h = epc_history(e[["dwelling", "lodgement_date", "transaction_type", "epc_tenure", "sap_current"]], last[["dwelling"]].assign(t=t0))
last = last.join(h)
key = last.drop_duplicates(["postcode", "address"], keep="last").set_index(["postcode", "address"])
fmt = {"epc_reason": "{:.0f}", "epc_tenure_n": "{:.0f}", "epc_rental_5y": "{:.0f}", "epc_age_y": "{:.2f}", "epc_n": "{:.0f}", "sap_jump": "{:.0f}"}
found = total = 0
for f in sorted(D.glob("epc_*.csv")):
    t = pd.read_csv(f, dtype=str, keep_default_na=False)
    sub = key.reindex(pd.MultiIndex.from_frame(t[["postcode", "address"]]))
    for c in EPC_H: t[c] = [fmt[c].format(v) if pd.notna(v) else "" for v in sub[c].values]
    found += (t.epc_n != "").sum(); total += len(t); t.to_csv(f, index=False)
print(f"certificate history added for {found:,} of {total:,} addresses (as of {t0:%b %Y})")
