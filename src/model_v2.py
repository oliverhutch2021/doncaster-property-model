"""Version 2: EPC attributes + nearest-neighbour prices + optional last-sale price, with a feature-layer ablation.

Same temporal design as v1: train 2015-2023, early-stop on 2024, test Jan 2025 - Aug 2026,
target = log(price) - log(price index known at the valuation date)."""
import json, pathlib, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.neighbors import BallTree
from sklearn.model_selection import KFold
from price_index import fit_index
from features import add_prior_levels

ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"
s = pd.read_parquet(ROOT / "data/processed/sales_epc.parquet")
s["sale_date"] = pd.to_datetime(s.sale_date); s["month"] = s.sale_date.values.astype("datetime64[M]")
s["prev_date"] = pd.to_datetime(s.prev_date)
TRAIN_END, VAL_END = pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")

# ---------- price index 1995-2026, known at valuation time for 2025+ ----------
idx_hist = fit_index(s[s.sale_date <= VAL_END])
rt = {}
for m in pd.date_range("2025-01-01", s.month.max(), freq="MS"):
    ix = fit_index(s[s.month <= m - pd.DateOffset(months=2)])
    common = min(ix.index.max(), pd.Timestamp("2024-12-01"))
    rt[m] = ix.iloc[-1] / ix.loc[common] * idx_hist.loc[common]
index_known = pd.concat([idx_hist, pd.Series(rt)]).sort_index()
s["log_idx"] = np.log(s.month.map(index_known))
s["y"] = np.log(s.price); s["y_defl"] = s.y - s.log_idx

# ---------- last sale of the same home, index-adjusted ----------
pm = s.prev_date.values.astype("datetime64[M]")
s["prev_defl"] = np.log(s.prev_price) - np.log(pd.Series(pm).map(index_known).values)
s["years_since_prev"] = (s.sale_date - s.prev_date).dt.days / 365.25
s["prev_nb"] = s.prev_new_build.astype(float)

# ---------- local levels (v1) ----------
s = s[s.sale_date >= "2014-01-01"].copy()
s = add_prior_levels(s)

# ---------- nearest-neighbour prices from EARLIER sales (previous 36 months) ----------
R = 6371.0
s["knn_lvl"] = np.nan; s["knn_dist"] = np.nan; s["knn_ppsqm"] = np.nan
s["ppsqm"] = s.y_defl - np.log(s.floor_area)
rad = np.radians(s[["lat", "lon"]].values)
for m in pd.date_range("2015-01-01", s.month.max(), freq="MS"):
    q = (s.month == m).values
    if not q.any(): continue
    pool = ((s.month >= m - pd.DateOffset(months=36)) & (s.month < m)).values
    for t in "DSTF":
        qt, pt = q & (s.property_type == t).values, pool & (s.property_type == t).values
        if qt.sum() == 0 or pt.sum() < 3: continue
        k = min(10, pt.sum()); tree = BallTree(rad[pt], metric="haversine")
        dist, ind = tree.query(rad[qt], k=k)
        vals = s.y_defl.values[pt][ind]
        s.loc[qt, "knn_lvl"] = np.median(vals, axis=1); s.loc[qt, "knn_dist"] = dist.mean(axis=1) * R
    pa = pool & s.floor_area.notna().values
    if pa.sum() >= 5:
        tree = BallTree(rad[pa], metric="haversine"); dist, ind = tree.query(rad[q], k=min(15, pa.sum()))
        s.loc[q, "knn_ppsqm"] = np.median(s.ppsqm.values[pa][ind], axis=1)
s = s[s.sale_date >= "2015-01-01"].copy()

BASE = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime",
        "imd_barriers", "imd_living_env", "lvl_sector_type", "lvl_lsoa", "n_sector_type", "property_type", "tenure", "new_build"]
EPC = ["floor_area", "rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas"]
KNN = ["knn_lvl", "knn_dist", "knn_ppsqm"]
PREV = ["prev_defl", "years_since_prev", "prev_nb"]
LAYERS = {"v1_location": BASE, "plus_epc": BASE + EPC, "plus_neighbours": BASE + EPC + KNN, "plus_last_sale": BASE + EPC + KNN + PREV}

def X(d, cols):
    x = d[cols].copy()
    x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int)
    return x.astype(float)

P = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=30, feature_fraction=0.8,
         bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=42)
def fit(tr, va, cols, params=P):
    dt = lgb.Dataset(X(tr, cols), tr.y_defl, categorical_feature=["property_type"])
    return lgb.train(params, dt, 5000, valid_sets=[lgb.Dataset(X(va, cols), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
def metrics(d, pred_log):
    p = np.exp(pred_log); ape = np.abs(p - d.price.values) / d.price.values
    return dict(n=int(len(d)), mae=float(np.mean(np.abs(p - d.price.values))), mdape=float(np.median(ape)),
                within10=float((ape <= .1).mean()), within20=float((ape <= .2).mean()))

tr, va, te = s[s.sale_date <= TRAIN_END], s[(s.sale_date > TRAIN_END) & (s.sale_date <= VAL_END)], s[s.sale_date > VAL_END]
print("train/val/test", len(tr), len(va), len(te), "| test with EPC:", f"{te.floor_area.notna().mean():.1%}", "with prior sale:", f"{te.prev_defl.notna().mean():.1%}")
res = {"ablation": {}}
for name, cols in LAYERS.items():
    m = fit(tr, va, cols)
    p = m.predict(X(te, cols), num_iteration=m.best_iteration) + te.log_idx.values
    res["ablation"][name] = metrics(te, p) | {"trees": m.best_iteration}
    print(name, {k: round(v, 4) for k, v in res["ablation"][name].items()})

# ---------- clean-up: drop training sales the model can't explain at all (likely non-market) ----------
full = LAYERS["plus_last_sale"]; trva = s[s.sale_date <= VAL_END]
oof = np.zeros(len(trva))
for a, b in KFold(5, shuffle=True, random_state=1).split(trva):
    mm = lgb.train(P, lgb.Dataset(X(trva.iloc[a], full), trva.y_defl.iloc[a], categorical_feature=["property_type"]), res["ablation"]["plus_last_sale"]["trees"])
    oof[b] = mm.predict(X(trva.iloc[b], full))
resid = trva.y_defl.values - oof
bad = np.abs(resid) > 0.8                          # price more than ~2.2x off the model, either way
res["cleaning"] = dict(threshold_log=0.8, removed=int(bad.sum()), share=float(bad.mean()),
                       removed_below=int((resid < -0.8).sum()), removed_above=int((resid > 0.8).sum()))
trva.assign(resid=resid)[bad][["sale_date", "price", "postcode", "property_type", "paon", "saon", "street", "floor_area", "resid"]] \
    .sort_values("resid").to_csv(OUT / "removed_outliers.csv", index=False)
keep_ids = set(trva.unique_id[~bad])
tr_c, va_c = tr[tr.unique_id.isin(keep_ids)], va[va.unique_id.isin(keep_ids)]
m = fit(tr_c, va_c, full)
p = m.predict(X(te, full), num_iteration=m.best_iteration) + te.log_idx.values
res["ablation"]["plus_last_sale_cleaned"] = metrics(te, p) | {"trees": m.best_iteration}
print("cleaned", res["cleaning"], {k: round(v, 4) for k, v in res["ablation"]["plus_last_sale_cleaned"].items()})
res["test_with_prior_sale"] = metrics(te[te.prev_defl.notna().values], p[te.prev_defl.notna().values])
res["test_without_prior_sale"] = metrics(te[te.prev_defl.isna().values], p[te.prev_defl.isna().values])
print("with prior sale", res["test_with_prior_sale"]); print("without", res["test_without_prior_sale"])

json.dump(res, open(OUT / "metrics_v2.json", "w"), indent=1)
index_known.rename("index").to_csv(OUT / "price_index_v2.csv")
s.to_parquet(ROOT / "data/processed/model_frame_v2.parquet")
pd.Series(sorted(keep_ids)).to_csv(OUT / "train_keep_ids.csv", index=False)
print("saved")
