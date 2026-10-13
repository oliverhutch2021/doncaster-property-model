"""Version 5 lookups for the dashboard (independent of the model fit):

epc_<district>.csv  the latest certificate per home, now with plot size (HM Land Registry titles + OS Open UPRN)
                    and the extra EPC fields the v5 model uses
street_levels.csv   per postcode: the postcode's own price level and, for each street in it and each type, the street's
                    level - median index-adjusted log price over the 60 months before the valuation month
ct_mix.csv          VOA council tax bands by neighbourhood (LSOA), property type and bedrooms, March 2025
"""
import csv, json, pathlib, sys, re, numpy as np, pandas as pd, duckdb
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from epc_match import load_epc
ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; P_ = ROOT / "data/processed"; D = ROOT / "outputs/dash2"
def wcsv(name, header, rows):
    with open(D / name, "w", newline="") as f: w = csv.writer(f); w.writerow(header); w.writerows(rows)
fmt = lambda v, nd=None: "" if v is None or (isinstance(v, float) and np.isnan(v)) else (round(float(v), nd) if nd is not None else (int(v) if float(v).is_integer() else float(v)))

# ---------- EPC address files with plot + extra fields ----------
src = open(ROOT / "src/features_v5.py").read()
e = load_epc()[["certificate_number", "dwelling", "lodgement_date", "postcode", "address1", "address2", "epc_type", "built_form", "age_year",
                "floor_area", "rooms", "sap_current", "sap_potential", "current_energy_rating", "mains_gas_flag", "extensions", "uprn"]]
x = duckdb.sql(f"""select certificate_number, walls_description, roof_description, windows_description, main_fuel, mainheat_description,
        secondheat_description, number_open_fireplaces, low_energy_lighting, photo_supply, floor_height, floor_level, flat_top_storey,
        number_heated_rooms, glazed_area from read_csv_auto('{RAW}/epc_doncaster.csv', all_varchar=true, sample_size=-1)""").df()
e = e.merge(x, on="certificate_number", how="left")
# reuse the exact encodings from features_v5.py (the block between the two markers)
block = src[src.index('w = e.walls_description'):src.index('PHYS_X = [')]
exec(block)
last = e.sort_values("lodgement_date").groupby("dwelling").tail(1).copy()
up = pd.read_parquet(P_ / "uprn_plots.parquet"); last["uprn_n"] = pd.to_numeric(last.uprn, errors="coerce")
last = last.merge(up, left_on="uprn_n", right_on="uprn", how="left", suffixes=("", "_u"))
last["district"] = last.postcode.str.split(" ").str[0]
last["address"] = (last.address1.fillna("") + ", " + last.address2.fillna("")).str.strip(", ").where(last.address2.notna(), last.address1.fillna(""))
last["bf"] = last.built_form.map({"Detached": 0, "Semi-Detached": 1, "End-Terrace": 2, "Mid-Terrace": 3, "Enclosed End-Terrace": 4, "Enclosed Mid-Terrace": 5})
pcs = set(pd.read_csv(D / "postcodes.csv").postcode)
last = last[last.postcode.isin(pcs)]
XF = ["wall_type", "ceiling_m", "floor_level_n", "top_floor", "heated_rooms", "glazed_area_n", "fireplaces", "wall_insulated", "loft_mm", "glazing",
      "elec_heating", "heat_pump", "woodburner", "low_energy_light", "solar_pv"]
PF = ["plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home"]
H = ["postcode", "address", "lodged", "epc_type", "built_form_code", "age_year", "floor_area", "rooms", "sap_current", "sap_potential", "rating", "mains_gas", "extensions"] + PF + XF
districts = []
for dname, g in last.groupby("district"):
    if len(g) < 50: continue
    districts.append(dname); rows = []
    for r in g.sort_values(["postcode", "address"]).itertuples():
        rows.append([r.postcode, r.address, r.lodgement_date.strftime("%Y-%m"), r.epc_type, fmt(r.bf), fmt(r.age_year), fmt(r.floor_area), fmt(r.rooms), fmt(r.sap_current),
                     fmt(r.sap_potential), r.current_energy_rating or "", r.mains_gas_flag or "", fmt(r.extensions),
                     fmt(r.plot_m2, 0), fmt(r.plot_epc_homes), fmt(r.plot_uprns), fmt(r.plot_m2_per_home, 0)] + [fmt(getattr(r, c), 2) for c in XF])
    wcsv(f"epc_{dname}.csv", H, rows)
print("EPC files:", districts, "homes", len(last), "with plot", f"{last.plot_m2.notna().mean():.1%}")

# ---------- street and postcode levels at the valuation month ----------
s = pd.read_parquet(P_ / "model_frame_v5.parquet")
val_month = s.month.max() + pd.DateOffset(months=1)
w = s[(s.month >= val_month - pd.DateOffset(months=60)) & (s.month < val_month)]
st = w.groupby(["street_key", "property_type"]).y_defl.agg(lvl="median", n="count").reset_index()
pc = w.groupby("postcode").y_defl.agg(lvl="median", n="count")
allsales = pd.read_parquet(P_ / "model_frame_v5.parquet", columns=["postcode", "street_key", "street"])
pc_streets = allsales.drop_duplicates(["postcode", "street_key"])
rows = []
for r in pc.itertuples(): rows.append([r.Index, "", "*", round(r.lvl, 5) if r.n >= 2 else "", int(r.n)])
m = pc_streets.merge(st, on="street_key")
for r in m.itertuples(): rows.append([r.postcode, r.street or "", r.property_type, round(r.lvl, 5) if r.n >= 2 else "", int(r.n)])
wcsv("street_levels.csv", ["postcode", "street", "type", "level", "n"], rows)
# postcodes with streets but no recent sales still need the street list for matching
print("street_levels rows:", len(rows))

# ---------- VOA council tax mix by LSOA x type x bedrooms ----------
v3 = pd.read_csv(RAW / "voa/CTSOP3.1/CTSOP3.1/CTSOP3_1_2025_03_31.csv", encoding="utf-8-sig", low_memory=False)
lsoas = set(pd.read_csv(D / "postcodes.csv").lsoa21.dropna())
v3 = v3[(v3.geography == "LSOA") & v3.ecode.isin(lsoas) & (v3.band != "All")]
TY = {"bungalow": "bungalow", "flat_mais": "flat", "house_terraced": "T", "house_semi": "S", "house_detached": "D"}
rows = []
for r in v3.to_dict("records"):
    for pre, ty in TY.items():
        for b in ["1", "2", "3", "4", "5", "6"]:
            v = pd.to_numeric(r.get(f"{pre}_{b}"), errors="coerce")
            if pd.notna(v) and v > 0: rows.append([r["ecode"], ty, b, r["band"], int(v)])
wcsv("ct_mix.csv", ["lsoa21", "ptype", "beds", "band", "count"], rows)
print("ct_mix rows:", len(rows))
