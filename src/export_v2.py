"""Version 2 dashboard export: compact browser model with EPC, neighbour and last-sale features,
condition recalibration, buy-to-let area statistics, rents, and EPC address lookup."""
import json, csv, re, pathlib, numpy as np, pandas as pd, lightgbm as lgb, duckdb
from sklearn.model_selection import KFold
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; D = OUT / "dash2"; D.mkdir(exist_ok=True)
s = pd.read_parquet(ROOT / "data/processed/model_frame_v2.parquet")
idx = pd.read_csv(OUT / "price_index_v2.csv", index_col=0, parse_dates=True)["index"]
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
mv2 = json.load(open(OUT / "metrics_v2.json"))
TRAIN_END, VAL_END = pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")
BASE = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime",
        "imd_barriers", "imd_living_env", "lvl_sector_type", "lvl_lsoa", "n_sector_type", "property_type", "tenure", "new_build"]
EPC = ["floor_area", "rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas"]
KNN = ["knn_lvl", "knn_dist", "knn_ppsqm"]; PREV = ["prev_defl", "years_since_prev", "prev_nb"]
FULL = BASE + EPC + KNN + PREV
def X(d, cols=FULL):
    x = d[cols].copy()
    x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int)
    return x.astype(float)
def wcsv(name, header, rows):
    with open(D / name, "w", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)

# ---------- compact model, same temporal validation ----------
P = dict(objective="regression_l1", learning_rate=0.08, num_leaves=31, min_data_in_leaf=40, feature_fraction=0.8,
         bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=42)
tr = s[(s.sale_date <= TRAIN_END) & s.unique_id.isin(keep)]
va_all = s[(s.sale_date > TRAIN_END) & (s.sale_date <= VAL_END)]; va = va_all[va_all.unique_id.isin(keep)]
te = s[s.sale_date > VAL_END]
dt = lgb.Dataset(X(tr), tr.y_defl, categorical_feature=["property_type"])
m = lgb.train(P, dt, 4000, valid_sets=[lgb.Dataset(X(va), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(120, verbose=False)])
n_iter = m.best_iteration
pred = lambda d: np.exp(m.predict(X(d), num_iteration=n_iter) + d.log_idx.values)
def met(d, p):
    ape = np.abs(p - d.price.values) / d.price.values
    return dict(n=int(len(d)), mae=float(np.mean(np.abs(p - d.price.values))), mdape=float(np.median(ape)), within10=float((ape <= .1).mean()), within20=float((ape <= .2).mean()))
bands = [100_000, 150_000, 200_000, 300_000]
vp = pred(va_all); r = np.log(va_all.price.values) - np.log(vp)
grp = lambda p, hasprev: np.digitize(p, bands) + 5 * hasprev.astype(int)
vg = grp(vp, va_all.prev_defl.notna().values)
conf = [[float(np.quantile(r[vg == g], .10)), float(np.quantile(r[vg == g], .90))] for g in range(10)]
tp = pred(te); tg = grp(tp, te.prev_defl.notna().values); rt = np.log(te.price.values) - np.log(tp)
cover = float(np.mean([conf[g][0] <= x <= conf[g][1] for g, x in zip(tg, rt)]))
val_m, test_m = met(va_all, vp), met(te, tp)
print("compact trees", n_iter, "test", test_m, "coverage", cover)

# ---------- production model on all cleaned sales ----------
allc = s[s.unique_id.isin(keep) | (s.sale_date > VAL_END)]
prod = lgb.train(P, lgb.Dataset(X(allc), allc.y_defl, categorical_feature=["property_type"]), n_iter)
(OUT / "model").mkdir(exist_ok=True); prod.save_model(str(OUT / "model/doncaster_lgbm_v2.txt"))   # native LightGBM file for Python use
dump = prod.dump_model()
def flat(tree):
    nodes = []
    def walk(n):
        i = len(nodes); nodes.append(None)
        if "leaf_value" in n: nodes[i] = [-1, 0, 0, 0, round(n["leaf_value"], 9), 0, 0]; return i
        if n["decision_type"] == "==": thr, kind = sum(1 << int(c) for c in str(n["threshold"]).split("||")), 1
        else: thr, kind = float(n["threshold"]), 0
        l = walk(n["left_child"]); rr = walk(n["right_child"])
        mt = {"None": 0, "Zero": 1, "NaN": 2}[n.get("missing_type", "NaN")]
        nodes[i] = [n["split_feature"], thr, l, rr, 1 if n.get("default_left", True) else 0, kind, mt]; return i
    walk(tree["tree_structure"]); return nodes
trees = [flat(t) for t in dump["tree_info"]]
def ev(x):
    tot = 0.0
    for nodes in trees:
        i = 0
        while nodes[i][0] != -1:
            f, thr, l, r_, dl, kind, mt = nodes[i]; v = x[f]
            nan = v is None or (isinstance(v, float) and np.isnan(v))
            if kind == 0 and mt == 0 and nan: v, nan = 0.0, False            # missing type None: NaN is treated as 0
            if (mt == 2 and nan) or (mt == 1 and (nan or v == 0)): left = dl == 1
            elif nan: left = False
            elif kind == 1: left = bool((thr >> int(v)) & 1)
            else: left = v <= thr
            i = l if left else r_
        tot += nodes[i][4]
    return tot
Xs = X(s.sample(300, random_state=5))
print("max |eval - lightgbm| =", max(abs(ev(list(row)) - p) for row, p in zip(Xs.values.tolist(), prod.predict(Xs))),
      "| rows with missing values in check:", int(Xs.isna().any(axis=1).sum()))
json.dump([{"tree": i, "nodes": json.dumps(t, separators=(",", ":"))} for i, t in enumerate(trees)], open(D / "model_trees.json", "w"), separators=(",", ":"))

# ---------- condition calibration (model WITHOUT last-sale features, out-of-fold) ----------
NOPREV = BASE + EPC + KNN
oof = np.zeros(len(s)); Xa = X(s, NOPREV)
for a, b in KFold(5, shuffle=True, random_state=1).split(Xa):
    mm = lgb.train(P, lgb.Dataset(Xa.iloc[a], s.y_defl.iloc[a], categorical_feature=["property_type"]), n_iter)
    oof[b] = mm.predict(Xa.iloc[b])
s["resid_np"] = s.y_defl.values - oof
key = s.drop_duplicates(["address_key", "sale_date"]).set_index(["address_key", "sale_date"])["resid_np"]
pairs = s[s.prev_price.notna() & (s.prev_new_build == False) & (s.prev_date >= "2015-01-01")].copy()
pairs["prev_resid"] = [key.get((a, d), np.nan) for a, d in zip(pairs.address_key, pairs.prev_date)]
pairs = pairs.dropna(subset=["prev_resid"]); pairs["hold_m"] = (pairs.sale_date - pairs.prev_date).dt.days / 30.44
flips = pairs[(pairs.hold_m >= 3) & (pairs.hold_m <= 18)]; control = pairs[pairs.hold_m >= 60]
pc = lambda v: round(100 * (np.exp(v) - 1), 1)
needs, refurb = np.median(flips.prev_resid), np.median(flips.resid_np)
cond = [("needs_full_renovation", "Needs full renovation", pc(needs), pc(np.quantile(flips.prev_resid, .25)), pc(np.quantile(flips.prev_resid, .75)), f"Median model residual at purchase for 3-18 month resales (n={len(flips)})"),
        ("dated", "Dated", pc(needs / 2), "", "", "Half of the needs-renovation discount (interpolated)"),
        ("average", "Average", 0.0, "", "", "Model baseline"),
        ("good", "Good", pc(refurb / 2), "", "", "Half of the refurbished premium (interpolated)"),
        ("recently_refurbished", "Recently refurbished", pc(refurb), pc(np.quantile(flips.resid_np, .25)), pc(np.quantile(flips.resid_np, .75)), f"Median model residual at resale for 3-18 month resales (n={len(flips)})")]
wcsv("condition.csv", ["condition", "label", "adjustment_pct", "range_low_pct", "range_high_pct", "basis"], cond)
print("condition v2:", [(c[0], c[2]) for c in cond], "control first-sale median", pc(np.median(control.prev_resid)))

# ---------- lookups ----------
con = duckdb.connect(str(ROOT / "data/processed/doncaster.duckdb"), read_only=True)
pcs = con.execute("select p.postcode, p.lat, p.lon, p.lsoa21, p.ward, i.* exclude (lsoa21) from postcodes p left join imd i using (lsoa21) where p.lat is not null").df()
c = con.execute("select * from centre").fetchone()
pcs["dist_centre_km"] = 2 * 6371 * np.arcsin(np.sqrt(np.sin(np.radians(pcs.lat - c[0]) / 2) ** 2 + np.cos(np.radians(c[0])) * np.cos(np.radians(pcs.lat)) * np.sin(np.radians(pcs.lon - c[1]) / 2) ** 2))
imdc = ["imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime", "imd_barriers", "imd_living_env"]
wcsv("postcodes.csv", ["postcode", "lat", "lon", "dist_centre_km"] + imdc + ["lsoa21", "ward", "imd_decile"],
     [[r.postcode, round(r.lat, 5), round(r.lon, 5), round(r.dist_centre_km, 3)] + ["" if pd.isna(getattr(r, k)) else round(getattr(r, k), 3) for k in imdc]
      + [r.lsoa21, r.ward, "" if pd.isna(r.imd_decile) else int(r.imd_decile)] for r in pcs.itertuples()])
latest_m = s.month.max(); val_month = latest_m + pd.DateOffset(months=1)
win = s[(s.month >= val_month - pd.DateOffset(months=36)) & (s.month < val_month)]          # pool used for 'today'
lvl_st = win.groupby(["sector", "property_type"]).y_defl.agg(["median", "count"]); lvl_l = win.groupby("lsoa21").y_defl.agg(["median", "count"])
wcsv("levels.csv", ["kind", "key", "level", "n"], [["sector_type", f"{a}|{b}", round(v["median"], 5), int(v["count"])] for (a, b), v in lvl_st.iterrows()]
     + [["lsoa", k, round(v["median"], 5), int(v["count"])] for k, v in lvl_l.iterrows() if v["count"] >= 5])
win = win.assign(addr=win.address_key.str.split("|").apply(lambda a: " ".join(x for x in [a[0], a[1], a[2].title()] if x).strip()))
wcsv("comps.csv", ["date", "price", "postcode", "type", "tenure", "new_build", "lat", "lon", "address", "y_defl", "floor_area"],
     [[r.sale_date.strftime("%Y-%m-%d"), int(r.price), r.postcode, r.property_type, r.tenure, int(r.new_build), round(r.lat, 5), round(r.lon, 5), r.addr,
       round(r.y_defl, 5), "" if pd.isna(r.floor_area) else round(r.floor_area, 1)] for r in win.itertuples()])
base15 = idx.loc["2015-01-01"]
wcsv("price_index.csv", ["month", "index_raw", "index_2015"], [[k.strftime("%Y-%m"), round(v, 6), round(v / base15, 5)] for k, v in idx.items()])
meta = dict(features=FULL, bands=bands, conformal=conf, index_latest=float(idx.iloc[-1]), index_latest_month=idx.index[-1].strftime("%Y-%m"),
            latest_sale=s.sale_date.max().strftime("%Y-%m-%d"), n_sales_model=int(len(s)), valuation_month=val_month.strftime("%Y-%m"))
json.dump([{"key": k, "value": json.dumps(v) if isinstance(v, (list, dict)) else str(v)} for k, v in meta.items()], open(D / "model_meta.json", "w"))

# ---------- EPC address lookup, one file per postcode district ----------
el = pd.read_parquet(ROOT / "data/processed/epc_latest.parquet")
el["district"] = el.postcode.str.split(" ").str[0]
el["address"] = (el.address1.fillna("") + ((", " + el.address2) if True else "")).where(el.address2.notna(), el.address1.fillna(""))
el["bf"] = el.built_form.map({"Detached": 0, "Semi-Detached": 1, "End-Terrace": 2, "Mid-Terrace": 3, "Enclosed End-Terrace": 4, "Enclosed Mid-Terrace": 5})
el = el[el.postcode.isin(set(pcs.postcode))]
districts = []
for dname, g in el.groupby("district"):
    if len(g) < 50: continue
    districts.append(dname)
    wcsv(f"epc_{dname}.csv", ["postcode", "address", "lodged", "epc_type", "built_form_code", "age_year", "floor_area", "rooms", "sap_current", "sap_potential", "rating", "mains_gas", "extensions"],
         [[r.postcode, r.address, r.lodgement_date.strftime("%Y-%m"), r.epc_type, "" if pd.isna(r.bf) else int(r.bf), "" if pd.isna(r.age_year) else r.age_year,
           "" if pd.isna(r.floor_area) else r.floor_area, "" if pd.isna(r.rooms) else int(r.rooms), "" if pd.isna(r.sap_current) else int(r.sap_current),
           "" if pd.isna(r.sap_potential) else int(r.sap_potential), r.current_energy_rating or "", r.mains_gas_flag or "", "" if pd.isna(r.extensions) else int(r.extensions)] for r in g.sort_values(["postcode", "address"]).itertuples()])
print("EPC districts:", districts)

# ---------- rents ----------
rent = pd.read_csv(ROOT / "data/raw/pipr_doncaster.csv", parse_dates=["Time period"])
cols = {"all": "Rental price", "1 bed": "Rental price one bed", "2 bed": "Rental price two bed", "3 bed": "Rental price three bed", "4+ bed": "Rental price four or more bed",
        "Detached": "Rental price detached", "Semi-detached": "Rental price semidetached", "Terraced": "Rental price terraced", "Flat/maisonette": "Rental price flat maisonette"}
wcsv("rents.csv", ["month", "series", "monthly_rent"], [[r["Time period"].strftime("%Y-%m"), k, int(r[v])] for _, r in rent.iterrows() for k, v in cols.items() if pd.notna(r[v])])
lr = rent.iloc[-1]; l10 = rent[rent["Time period"] == lr["Time period"] - pd.DateOffset(years=10)].iloc[0]; l5 = rent[rent["Time period"] == lr["Time period"] - pd.DateOffset(years=5)].iloc[0]
rent_cagr10 = (lr["Rental price"] / l10["Rental price"]) ** 0.1 - 1; rent_cagr5 = (lr["Rental price"] / l5["Rental price"]) ** 0.2 - 1
price_cagr10 = (idx.loc[latest_m] / idx.loc[latest_m - pd.DateOffset(years=10)]) ** 0.1 - 1
wcsv("lha.csv", ["bedrooms", "monthly_rate", "source"], [["Shared room", 304.17, "DWP Universal Credit LHA rates 2026-27, Doncaster BRMA"], ["1", 425.00, "same"], ["2", 500.00, "same"], ["3", 550.00, "same"], ["4", 725.00, "same"]])

# ---------- buy-to-let area statistics by postcode sector ----------
latest = s.sale_date.max()
w3 = s[s.sale_date > latest - pd.Timedelta(days=1095)]
w5 = s[(s.sale_date > latest - pd.Timedelta(days=1095 + 1826)) & (s.sale_date <= latest - pd.Timedelta(days=1826))]
w10 = s[(s.sale_date > latest - pd.Timedelta(days=1095 + 3652)) & (s.sale_date <= latest - pd.Timedelta(days=3652))]
ep = el.assign(sector=el.postcode.str[:-2])
etn = pd.read_parquet(ROOT / "data/processed/epc_latest.parquet")  # tenure not in latest file -> reload from csv
ten = duckdb.sql(f"""select upper(trim(postcode)) postcode, coalesce(uprn, address1||'|'||coalesce(address2,'')||'|'||postcode) dw, lodgement_date, lower(tenure) tenure, try_cast(current_energy_efficiency as double) sap
    from read_csv_auto('{ROOT}/data/raw/epc_doncaster.csv', all_varchar=true, sample_size=-1)""").df()
ten = ten.sort_values("lodgement_date").groupby("dw").tail(1); ten["sector"] = ten.postcode.str[:-2]
rent_type = {"D": int(lr["Rental price detached"]), "S": int(lr["Rental price semidetached"]), "T": int(lr["Rental price terraced"]), "F": int(lr["Rental price flat maisonette"])}
rows = []
for sec, g in w3.groupby("sector"):
    if len(g) < 20: continue
    t = ten[ten.sector == sec]; known = t[t.tenure.isin(["owner-occupied", "rented (private)", "rented (social)"])]
    med = {ty: (int(gt.price.median()), len(gt)) for ty, gt in g.groupby("property_type") if len(gt) >= 5}
    fa = {ty: float(gt.floor_area.median()) for ty, gt in g.groupby("property_type") if gt.floor_area.notna().sum() >= 5}
    g5, g10 = w5[w5.sector == sec], w10[w10.sector == sec]
    gr = lambda o: round(100 * (np.exp(g.y.median() - o.y.median()) - 1), 1) if len(o) >= 20 else ""
    row = dict(sector=sec, sales_3y=len(g), sales_per_year=round(len(g) / 3, 1), median_price=int(g.price.median()),
               price_per_m2=int(np.exp(np.median(np.log(g.price[g.floor_area.notna()] / g.floor_area[g.floor_area.notna()])))) if g.floor_area.notna().sum() >= 10 else "",
               growth_5y_pct=gr(g5), growth_10y_pct=gr(g10), imd_score=round(float(g.imd_score.mean()), 1), crime_score=round(float(g.imd_crime.mean()), 2),
               private_rented_pct=round(100 * (known.tenure == "rented (private)").mean(), 1) if len(known) >= 30 else "",
               social_rented_pct=round(100 * (known.tenure == "rented (social)").mean(), 1) if len(known) >= 30 else "",
               epc_below_c_pct=round(100 * (t.sap.dropna() < 69).mean(), 1) if t.sap.notna().sum() >= 30 else "",
               lat=round(g.lat.mean(), 4), lon=round(g.lon.mean(), 4), wards="; ".join(g.ward.value_counts().head(2).index),
               licensing="Hexthorpe selective licensing covers part of this sector" if sec == "DN4 0" else "")
    for ty in "DSTF":
        row[f"median_{ty}"] = med.get(ty, ("", ""))[0]; row[f"n_{ty}"] = med.get(ty, ("", ""))[1]
        row[f"floor_area_{ty}"] = round(fa[ty]) if ty in fa else ""
        row[f"yield_{ty}"] = round(12 * rent_type[ty] / med[ty][0] * 100, 2) if ty in med else ""
    rows.append(row)
sec_df = pd.DataFrame(rows); sec_df.to_csv(D / "sectors.csv", index=False)
print("sectors:", len(sec_df))

# ---------- assumptions (with sources) ----------
A = [("sdlt_band_1", "Stamp duty: 0% up to", 125000, "GBP", "gov.uk SDLT residential rates (checked 9 Oct 2026)"),
     ("sdlt_band_2", "Stamp duty: 2% up to", 250000, "GBP", "gov.uk"), ("sdlt_band_3", "Stamp duty: 5% up to", 925000, "GBP", "gov.uk"),
     ("sdlt_band_4", "Stamp duty: 10% up to", 1500000, "GBP", "gov.uk"), ("sdlt_rate_1", "Rate band 1", 0, "pct", "gov.uk"), ("sdlt_rate_2", "Rate band 2", 2, "pct", "gov.uk"),
     ("sdlt_rate_3", "Rate band 3", 5, "pct", "gov.uk"), ("sdlt_rate_4", "Rate band 4", 10, "pct", "gov.uk"), ("sdlt_rate_5", "Rate above band 4", 12, "pct", "gov.uk"),
     ("sdlt_surcharge", "Additional-property surcharge", 5, "pct", "gov.uk higher rates for additional dwellings"),
     ("mortgage_rate", "Buy-to-let mortgage rate", 5.66, "pct", "Moneyfacts average 5-year fixed buy-to-let rate at 75% loan to value, 1 August 2026 (moneyfactscompare.co.uk); rates rose in September and October, so enter a current quote"),
     ("mortgage_term", "Mortgage term", 25, "years", "Typical (assumption - edit)"), ("product_fee", "Mortgage arrangement fee", 1999, "GBP", "Typical (assumption - edit)"),
     ("deposit", "Deposit", 25, "pct", "Typical buy-to-let minimum (assumption - edit)"), ("stress_rate", "Lender stress-test rate", 5.5, "pct", "Typical lender stress rate (assumption - edit)"),
     ("icr_basic", "Interest cover ratio, basic-rate or company", 125, "pct", "Typical lender ICR (assumption - edit)"), ("icr_higher", "Interest cover ratio, higher-rate", 145, "pct", "Typical lender ICR (assumption - edit)"),
     ("letting_fee", "Letting and management fee", 12, "pct of rent", "Estimate incl. VAT (assumption - edit)"), ("maintenance", "Maintenance", 8, "pct of rent", "Estimate (assumption - edit)"),
     ("voids", "Void weeks per year", 2, "weeks", "Estimate (assumption - edit)"), ("insurance", "Landlord insurance", 300, "GBP per year", "Estimate (assumption - edit)"),
     ("compliance", "Gas safety, electrical checks, licences", 250, "GBP per year", "Estimate (assumption - edit)"),
     ("buying_costs", "Legal and survey costs", 1500, "GBP", "Estimate (assumption - edit)"), ("selling_costs", "Selling agent and legal costs", 1.8, "pct of sale price", "Estimate incl. VAT (assumption - edit)"),
     ("refurb_light", "Refurbishment cost - cosmetic", 300, "GBP per m2", "Estimate (assumption - edit)"), ("refurb_medium", "Refurbishment cost - kitchen/bathroom", 700, "GBP per m2", "Estimate (assumption - edit)"),
     ("refurb_full", "Refurbishment cost - full renovation", 1200, "GBP per m2", "Estimate (assumption - edit)"),
     ("rent_growth", "Rent growth per year (Doncaster, last 10 years)", round(100 * rent_cagr10, 2), "pct", "ONS Price Index of Private Rents, Doncaster, Aug 2016 to Aug 2026"),
     ("rent_growth_5y", "Rent growth per year (Doncaster, last 5 years)", round(100 * rent_cagr5, 2), "pct", "ONS Price Index of Private Rents, Doncaster, Aug 2021 to Aug 2026"),
     ("price_growth", "House price growth per year (Doncaster, last 10 years)", round(100 * price_cagr10, 2), "pct", "This model's quality-adjusted Doncaster index, Aug 2016 to Aug 2026"),
     ("cost_inflation", "Cost inflation per year", 3, "pct", "Assumption - edit"),
     ("tax_basic", "Income tax on property income, basic rate (2026-27)", 20, "pct", "HMRC; rises to 22% from April 2027 (Autumn Budget 2025)"),
     ("tax_higher", "Income tax on property income, higher rate (2026-27)", 40, "pct", "HMRC; rises to 42% from April 2027 (Autumn Budget 2025)"),
     ("tax_basic_2027", "Property income basic rate from April 2027", 22, "pct", "Autumn Budget 2025"), ("tax_higher_2027", "Property income higher rate from April 2027", 42, "pct", "Autumn Budget 2025"),
     ("finance_credit", "Mortgage interest tax credit (Section 24)", 20, "pct", "HMRC; proposed 22% from April 2027 (Autumn Budget 2025)"),
     ("finance_credit_2027", "Mortgage interest tax credit from April 2027", 22, "pct", "Autumn Budget 2025 (proposed)"),
     ("corp_tax_small", "Corporation tax, profits up to £50k", 19, "pct", "HMRC small profits rate"),
     ("epc_upgrade_avg", "Average cost to reach EPC C", 5400, "GBP", "Government impact assessment, PRS energy efficiency response (21 Jan 2026)"),
     ("epc_cost_cap", "Landlord spending cap to reach EPC C", 10000, "GBP", "Government response, 21 Jan 2026 (10% of value if under £100k)"),
     ("floor_area", "Floor area if unknown", 85, "m2", "Placeholder (assumption - edit)")]
# the first assumptions: written to config/assumptions.csv only if it doesn't exist yet (it is the one place they are kept
# and edited; src/apply_assumptions.py copies it into the dashboard), so a rerun can't overwrite later values or rows
CFG = ROOT / "config/assumptions.csv"
if not CFG.exists():
    CFG.parent.mkdir(exist_ok=True)
    with open(CFG, "w", newline="") as f: w = csv.writer(f); w.writerow(["key", "label", "value", "unit", "source"]); w.writerows(A)

# ---------- rules that matter for buy-to-let (each with a source) ----------
rules = [("Stamp duty surcharge", "Buying an additional home adds 5 percentage points to every stamp duty band.", "https://www.gov.uk/stamp-duty-land-tax/residential-property-rates", "Checked 9 Oct 2026"),
 ("Renters' Rights Act 2025", "Section 21 'no-fault' evictions ended on 1 May 2026; existing assured shorthold tenancies became periodic assured tenancies.", "https://www.farleys.com/goodbye-section-21-a-landlords-guide-to-the-new-eviction-rules/", "In force 1 May 2026"),
 ("Energy efficiency (EPC C)", "All privately rented homes must reach EPC C (new metrics) by 1 October 2030, with a £10,000 spending cap per property (10% of value if worth under £100,000). Homes rated C before 1 October 2029 count as compliant until that EPC expires.", "https://www.gov.uk/government/consultations/improving-the-energy-performance-of-privately-rented-homes-2025-update/outcome/improving-the-energy-performance-of-privately-rented-homes-government-response-html", "Government response 21 Jan 2026; legislation expected 2027"),
 ("Mortgage interest relief (Section 24)", "Individual landlords can't deduct mortgage interest; they get a 20% tax credit on it instead. Companies deduct interest as a cost.", "https://www.gov.uk/guidance/changes-to-tax-relief-for-residential-landlords-how-its-worked-out-including-case-studies", "Current"),
 ("Property income tax from April 2027", "Property income tax rates rise to 22% / 42% / 47%, and the interest credit is proposed to rise to 22%.", "https://www.themortgageworks.co.uk/news-and-insights/post-autumn-budget-2025", "Autumn Budget 2025"),
 ("Selective licensing in Doncaster", "Hexthorpe has a selective licensing scheme (operational from 1 March 2022, for up to 5 years): landlords there need a licence. Edlington's scheme ended in February 2023.", "https://www.doncaster.gov.uk/services/business-investment/selective-licensing", "Checked 9 Oct 2026"),
 ("Local Housing Allowance", "Universal Credit housing support in Doncaster is capped at £425 (1 bed), £500 (2 bed), £550 (3 bed) and £725 (4 bed) a month in 2026-27.", "https://www.gov.uk/government/publications/local-housing-allowance-lha-rates-applicable-from-april-2026-to-march-2027", "April 2026 to March 2027")]
wcsv("rules.csv", ["topic", "summary", "source_url", "status"], rules)

# ---------- accuracy datasets ----------
ab = mv2["ablation"]; names = {"v1_location": "Location and deprivation only (v1)", "plus_epc": "+ EPC (floor area, rooms, age, energy)", "plus_neighbours": "+ nearest-neighbour prices",
                               "plus_last_sale": "+ last sale of the same home", "plus_last_sale_cleaned": "+ training data clean-up (final)"}
wcsv("ablation.csv", ["step", "label", "mdape", "within10", "within20", "mae"], [[k, names[k], round(v["mdape"], 5), round(v["within10"], 4), round(v["within20"], 4), round(v["mae"])] for k, v in ab.items()])
acc = [["dashboard", "test_2025_26", k, v] for k, v in test_m.items()] + [["dashboard", "validation_2024", k, v] for k, v in val_m.items()] + [["dashboard", "test_2025_26", "coverage_80", cover]]
acc += [["dashboard_prior_sale", "test_2025_26", k, v] for k, v in met(te[te.prev_defl.notna()], tp[te.prev_defl.notna().values]).items()]
acc += [["dashboard_no_prior_sale", "test_2025_26", k, v] for k, v in met(te[te.prev_defl.isna()], tp[te.prev_defl.isna().values]).items()]
wcsv("accuracy.csv", ["model", "split", "metric", "value"], acc)
t = te.assign(pred=tp, ape=np.abs(tp - te.price.values) / te.price.values)
t["band"] = pd.cut(t.price, [0] + bands + [10**9], labels=["<100k", "100-150k", "150-200k", "200-300k", "300k+"])
br = []
for dim, col in [("type", "property_type"), ("band", "band")]:
    for gname, g in t.groupby(col, observed=True): br.append([dim, str(gname), len(g), round(g.ape.median(), 5), round((g.ape <= .1).mean(), 4)])
for gname, g in t.groupby(t.floor_area.notna()): br.append(["epc", "EPC matched" if gname else "No EPC match", len(g), round(g.ape.median(), 5), round((g.ape <= .1).mean(), 4)])
wcsv("accuracy_breakdown.csv", ["dimension", "group", "n", "mdape", "within10"], br)
imp = pd.Series(prod.feature_importance("gain"), index=prod.feature_name()); imp = (imp / imp.sum()).sort_values(ascending=False)
wcsv("feature_importance.csv", ["feature", "gain_share"], [[k, round(v, 5)] for k, v in imp.items()])
smp = t.sample(1500, random_state=7)
wcsv("test_sample.csv", ["price", "predicted", "type"], [[int(a), int(b), c] for a, b, c in zip(smp.price, smp.pred, smp.property_type)])
json.dump(dict(compact=test_m, coverage=cover, trees=n_iter, rent_cagr10=rent_cagr10, price_cagr10=price_cagr10, districts=districts), open(OUT / "export_v2_summary.json", "w"), indent=1)
for f in sorted(D.iterdir()): print(f.name, round(f.stat().st_size / 1e6, 2), "MB")
