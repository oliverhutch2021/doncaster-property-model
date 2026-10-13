"""Mark which postcodes in the lookup are inside Doncaster (fourth review).

The postcode list comes from every sale filed under Doncaster, and 145 of its 7,070 postcodes are elsewhere: Barnsley,
Rotherham and Sheffield, and a few further away (OX5, NG5, WF8). A postcode counts as Doncaster's when its 2021 small
area (LSOA) is one of the borough's 199 (outputs/dash2/lsoa_map.json). The dashboard and src/predict.py refuse the rest.
Adds or refreshes the in_doncaster column (1 or 0) of outputs/dash2/postcodes.csv and model/postcodes.csv."""
import json, pathlib, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]
ls = {r["lsoa21"] for r in json.load(open(ROOT / "outputs/dash2/lsoa_map.json"))}
for f in (ROOT / "outputs/dash2/postcodes.csv", ROOT / "model/postcodes.csv"):
    p = pd.read_csv(f, dtype=str, keep_default_na=False)
    p["in_doncaster"] = p.lsoa21.isin(ls).map({True: "1", False: "0"})
    p.to_csv(f, index=False); print(f.relative_to(ROOT), len(p), "postcodes,", int((p.in_doncaster == "0").sum()), "outside Doncaster")
