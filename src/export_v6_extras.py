"""Version 6 dashboard extras.

tier_index.csv  quality-adjusted price index for Doncaster's cheaper, middle and dearer areas (postcode sectors split
                into thirds by their 2015-2019 median price), Jan 2015 = 100
epc_*.csv       adds each home's Land Registry sales history ('sales': date|price|new build;...) and its building
                footprint per address (OS OpenMap Local), so the page can fill in the last sale and flag possible
                extensions since the certificate
ext_flag.csv    the footprint check's thresholds: for each EPC type, the 10th percentile of floor area / footprint
                among homes whose certificate is under 2 years old"""
import csv, json, pathlib, sys, numpy as np, pandas as pd, duckdb
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from price_index import fit_index
from epc_match import load_epc
ROOT = pathlib.Path(__file__).resolve().parents[1]; P_ = ROOT / "data/processed"; D = ROOT / "outputs/dash2"

# ---------- price index by area tier ----------
con = duckdb.connect(str(P_ / "doncaster.duckdb"), read_only=True)
sales = con.execute("select * from sales_loc").df(); sales["sale_date"] = pd.to_datetime(sales.sale_date)
sales["sector"] = sales.postcode.str[:-2]
base = sales[(sales.sale_date >= "2015-01-01") & (sales.sale_date < "2020-01-01")].groupby("sector").price.agg(["median", "count"])
base = base[base["count"] >= 30]
cuts = base["median"].quantile([1 / 3, 2 / 3]).values
tier = pd.cut(base["median"], [0, cuts[0], cuts[1], 1e12], labels=["Cheaper areas", "Middle areas", "Dearer areas"])
sales["tier"] = sales.sector.map(tier)
rows = []
for t in ["Cheaper areas", "Middle areas", "Dearer areas"]:
    ix = fit_index(sales[(sales.tier == t) & (sales.sale_date >= "2015-01-01")])
    ix = ix / ix.loc["2015-01-01"] * 100
    rows += [[m.strftime("%Y-%m"), t, round(v, 2)] for m, v in ix.items()]
with open(D / "tier_index.csv", "w", newline="") as f: w = csv.writer(f); w.writerow(["month", "tier", "index"]); w.writerows(rows)
last = {t: [r for r in rows if r[1] == t][-1][2] for t in ["Cheaper areas", "Middle areas", "Dearer areas"]}
print("tier cut-offs (2015-19 sector medians):", [int(c) for c in cuts], "| latest index:", last)
json.dump({"cuts": [int(c) for c in cuts], "sectors": {k: str(v) for k, v in tier.dropna().items()}}, open(P_ / "tier_sectors.json", "w"))

# ---------- sales history + footprint into the EPC address files ----------
se = pd.read_parquet(P_ / "sales_epc.parquet", columns=["dwelling", "sale_date", "price", "new_build"]).dropna(subset=["dwelling"])
se = se.sort_values("sale_date")
hist = se.groupby("dwelling").apply(lambda g: ";".join(f"{d:%Y-%m-%d}|{int(p)}|{'Y' if nb else 'N'}" for d, p, nb in zip(g.sale_date, g.price, g.new_build)), include_groups=False)
e = load_epc()[["dwelling", "postcode", "address1", "address2", "lodgement_date", "uprn"]]
last_cert = e.sort_values("lodgement_date").groupby("dwelling").tail(1).copy()
last_cert["address"] = (last_cert.address1.fillna("") + ", " + last_cert.address2.fillna("")).str.strip(", ").where(last_cert.address2.notna(), last_cert.address1.fillna(""))
last_cert["sales"] = last_cert.dwelling.map(hist).fillna("")
bld = pd.read_parquet(P_ / "uprn_buildings.parquet")
last_cert["uprn_n"] = pd.to_numeric(last_cert.uprn, errors="coerce")
last_cert = last_cert.merge(bld[["uprn", "bld_m2_per_uprn"]], left_on="uprn_n", right_on="uprn", how="left")
key = last_cert.set_index(["postcode", "address"])
added = 0
for f in sorted(D.glob("epc_*.csv")):
    t = pd.read_csv(f, dtype=str, keep_default_na=False)
    k = pd.MultiIndex.from_frame(t[["postcode", "address"]])
    sub = key[~key.index.duplicated(keep="last")].reindex(k)
    t["sales"] = sub["sales"].fillna("").values
    t["footprint_m2"] = sub["bld_m2_per_uprn"].round(0).astype("Int64").astype(str).replace("<NA>", "").values
    added += (t.sales != "").sum(); t.to_csv(f, index=False)
print("EPC homes with a sales history:", added)

# ---------- footprint check thresholds ----------
c = e.merge(load_epc()[["dwelling", "lodgement_date", "floor_area", "epc_type"]], on=["dwelling", "lodgement_date"])
c = c.sort_values("lodgement_date").groupby("dwelling").tail(1)
c["uprn_n"] = pd.to_numeric(c.uprn, errors="coerce"); c = c.merge(bld[["uprn", "bld_m2_per_uprn"]], left_on="uprn_n", right_on="uprn", how="inner")
c = c[(c.lodgement_date >= pd.Timestamp("2024-09-01")) & c.floor_area.notna()]
c["ratio"] = c.floor_area / c.bld_m2_per_uprn
thr = {t: round(float(g.ratio.quantile(0.10)), 3) for t, g in c.groupby("epc_type") if len(g) >= 200 and t in ("House", "Bungalow")}
pd.DataFrame([{"epc_type": k, "p10_floor_over_footprint": v, "n_recent_certificates": int((c.epc_type == k).sum())} for k, v in thr.items()]).to_csv(D / "ext_flag.csv", index=False)
print("footprint check thresholds (10th pct of floor area / footprint, recent certificates):", thr)

# ---------- cost assumptions for the what-if tool (appended once to assumptions.csv) ----------
NEW = [["ext_single_m2", "Single-storey extension build cost", 1775, "GBP per m2", "less.co.uk (2026): Yorkshire & Humber £1,350-£2,200/m², mid-range spec; excludes VAT, fees and fit-out"],
       ["ext_double_m2", "Two-storey extension build cost", 1600, "GBP per m2", "less.co.uk (2026): £1,200-£2,000/m² nationally; excludes VAT, fees and fit-out"],
       ["loft_m2", "Loft conversion (rear dormer) cost", 2500, "GBP per m2", "planwatch.co.uk (2026): rear dormer £2,200-£2,800/m² outside London, as quoted (check whether VAT is included)"],
       ["vat_works", "VAT on extension building work", 20, "pct", "Standard rate"],
       ["ext_fees", "Design, structural, planning and building control fees", 5000, "GBP", "less.co.uk (2026): typically £3,000-£10,000 (assumption - edit)"]]
CFG = ROOT / "config/assumptions.csv"                 # the one assumptions file (src/apply_assumptions.py copies it to the dashboard)
a = pd.read_csv(CFG)
add = [r for r in NEW if r[0] not in set(a.key)]
if add: pd.concat([a, pd.DataFrame(add, columns=a.columns)]).to_csv(CFG, index=False)
print("assumptions added:", [r[0] for r in add])

# ---------- tested-changes table: v6 rows ----------
m6 = json.load(open(ROOT / "outputs/metrics_v6_tests.json"))
d = lambda a, b: (float(np.mean(np.array(m6[a]["mdape"]) - np.array(m6[b]["mdape"])) * 100), float(np.std(np.array(m6[a]["mdape"]) - np.array(m6[b]["mdape"])) * 100))
lt = pd.read_csv(D / "layer_tests.csv"); lt = lt[~lt.layer.isin(["buildings", "monotone"])]
g1, s1 = d("tuned", "tuned_bld")
g2, s2 = d("tuned", "tuned_huber_mono")
new = pd.DataFrame([["buildings", "Building footprints from OS outlines (to catch extensions)", round(g1, 3), round(s1, 3), "Left out: no better (used only to flag possible extensions)"],
                    ["monotone", "Forcing more floor area to never lower the value", round(g2, 3), round(s2, 3), "Left out: needs Huber loss, about 0.1 points worse"]], columns=lt.columns)
pd.concat([new, lt]).to_csv(D / "layer_tests.csv", index=False)
print(pd.read_csv(D / "layer_tests.csv").head(4).to_string())
