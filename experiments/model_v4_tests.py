"""Version 4 tests: can the model follow areas whose prices move faster (or slower) than Doncaster as a whole?

E1  recent local features: the same neighbour and area levels but from the last 12 months only, plus the
    gap between the 12-month and 36-month levels (local momentum).
E2  local residual correction: after predicting, shift the estimate by a share (alpha) of the median error the
    model made on the k nearest sales of the previous 12 months (sold at least 60 days earlier, so they would be
    registered). alpha and k are tuned on 2024 with a model trained to 2022, then applied unchanged to 2025-26.
Same split, cleaned training data and 3 seeds as v3."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.neighbors import BallTree
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; R = 6371.0
s = pd.read_parquet(ROOT / "data/processed/model_frame_v2.parquet").sort_values("sale_date").reset_index(drop=True)
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
rad = np.radians(s[["lat", "lon"]].values)

# ---------- E1: 12-month local features (only sales before the month being valued) ----------
s["knn12_lvl"] = np.nan; s["knn12_n"] = 0.0; s["lvl12_sector_type"] = np.nan; s["lvl12_lsoa"] = np.nan
for m in pd.date_range("2015-01-01", s.month.max(), freq="MS"):
    q = (s.month == m).values
    if not q.any(): continue
    pool = ((s.month >= m - pd.DateOffset(months=12)) & (s.month < m)).values
    for t in "DSTF":
        qt, pt = q & (s.property_type == t).values, pool & (s.property_type == t).values
        if qt.sum() == 0 or pt.sum() < 3: continue
        tree = BallTree(rad[pt], metric="haversine"); dist, ind = tree.query(rad[qt], k=min(10, pt.sum()))
        within = dist * R <= 3.0                                     # only neighbours within 3 km count
        vals = np.where(within, s.y_defl.values[pt][ind], np.nan)
        n = within.sum(1); med = np.nanmedian(np.where(n[:, None] >= 3, vals, np.nan), axis=1) if True else None
        s.loc[qt, "knn12_lvl"] = med; s.loc[qt, "knn12_n"] = n
    pw = s[pool]
    st = pw.groupby(["sector", "property_type"]).y_defl.agg(["median", "count"]); st = st[st["count"] >= 5]["median"]
    ls = pw.groupby("lsoa21").y_defl.agg(["median", "count"]); ls = ls[ls["count"] >= 5]["median"]
    idx = np.where(q)[0]
    s.loc[q, "lvl12_sector_type"] = [st.get((a, b), np.nan) for a, b in zip(s.sector.values[idx], s.property_type.values[idx])]
    s.loc[q, "lvl12_lsoa"] = s.lsoa21.values[idx].tolist() and [ls.get(c, np.nan) for c in s.lsoa21.values[idx]]
s["mom_knn"] = s.knn12_lvl - s.knn_lvl; s["mom_sector"] = s.lvl12_sector_type - s.lvl_sector_type; s["mom_lsoa"] = s.lvl12_lsoa - s.lvl_lsoa
s = s[s.sale_date >= "2015-01-01"].reset_index(drop=True); rad = np.radians(s[["lat", "lon"]].values)
print("E1 coverage:", {c: f"{s[c].notna().mean():.0%}" for c in ["knn12_lvl", "lvl12_sector_type", "lvl12_lsoa"]})

BASE = ["lat","lon","dist_centre_km","imd_score","imd_income","imd_employment","imd_education","imd_health","imd_crime","imd_barriers","imd_living_env","lvl_sector_type","lvl_lsoa","n_sector_type","property_type","tenure","new_build"]
EPC = ["floor_area","rooms","age_year","bungalow","built_form_code","extensions","sap_current","sap_potential","sap_gap","mains_gas"]
FULL = BASE + EPC + ["knn_lvl","knn_dist","knn_ppsqm","prev_defl","years_since_prev","prev_nb"]
E1 = ["knn12_lvl", "knn12_n", "lvl12_sector_type", "lvl12_lsoa", "mom_knn", "mom_sector", "mom_lsoa"]
def X(d, cols):
    x = d[cols].copy(); x["property_type"] = d.property_type.map({"D":0,"S":1,"T":2,"F":3}).astype(int); x["tenure"]=(d.tenure=="L").astype(int); x["new_build"]=d.new_build.astype(int); return x.astype(float)
def fit(tr, va, cols, seed):
    P = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=30, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=seed)
    dt = lgb.Dataset(X(tr, cols), tr.y_defl, categorical_feature=["property_type"])
    return lgb.train(P, dt, 5000, valid_sets=[lgb.Dataset(X(va, cols), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
mdape = lambda d, logp: float(np.median(np.abs(np.exp(logp) - d.price.values) / d.price.values))

# ---------- E2: residual correction from nearby recent sales ----------
def correction(resid_pool: pd.DataFrame, target: pd.DataFrame, k: int, lag_days=60, months=12):
    """Median residual of the k nearest pool sales sold between `months` months and `lag_days` days before each target sale."""
    out = np.full(len(target), np.nan); tr_ = np.radians(target[["lat", "lon"]].values)
    pdates = resid_pool.sale_date.values; prad = np.radians(resid_pool[["lat", "lon"]].values); pr = resid_pool.r.values
    for m in pd.date_range(target.month.min(), target.month.max(), freq="MS"):
        q = (target.month == m).values
        if not q.any(): continue
        hi, lo = m - pd.Timedelta(days=lag_days), m - pd.DateOffset(months=months)
        sel = (pdates < np.datetime64(hi)) & (pdates >= np.datetime64(lo))
        if sel.sum() < k: continue
        tree = BallTree(prad[sel], metric="haversine"); _, ind = tree.query(tr_[q], k=k)
        out[q] = np.median(pr[sel][ind], axis=1)
    return out

def split(d, a, b): return d[(d.sale_date > a) & (d.sale_date <= b)]
res = {"seeds": {}}; SEEDS = [1, 2, 3]
for seed in SEEDS:
    row = {}
    for name, cols in [("v2", FULL), ("v2+E1", FULL + E1)]:
        # tuning run: train <= 2022, early-stop 2023, residuals on 2023-2024 (out of sample), tune on 2024
        trT = s[(s.sale_date <= "2022-12-31") & s.unique_id.isin(keep)]; vaT = split(s, "2022-12-31", "2023-12-31"); vaT = vaT[vaT.unique_id.isin(keep)]
        mT = fit(trT, vaT, cols, seed); pool = split(s, "2022-12-31", "2024-12-31").copy()
        pool["r"] = pool.y_defl.values - mT.predict(X(pool, cols), num_iteration=mT.best_iteration)
        tune = split(s, "2023-12-31", "2024-12-31").copy(); base_t = mT.predict(X(tune, cols), num_iteration=mT.best_iteration) + tune.log_idx.values
        best = (mdape(tune, base_t), 0.0, 0)
        for k in (10, 20, 40):
            c = np.nan_to_num(correction(pool, tune, k))
            for a in (0.25, 0.5, 0.75, 1.0):
                e = mdape(tune, base_t + a * c)
                if e < best[0]: best = (e, a, k)
        # test run: the usual model (train <= 2023, early-stop 2024); residual pool = 2024 + earlier test sales
        tr = s[(s.sale_date <= "2023-12-31") & s.unique_id.isin(keep)]; va = split(s, "2023-12-31", "2024-12-31"); va = va[va.unique_id.isin(keep)]
        te = s[s.sale_date > "2024-12-31"].copy(); m_ = fit(tr, va, cols, seed)
        pool2 = s[s.sale_date > "2023-12-31"].copy(); pool2["r"] = pool2.y_defl.values - m_.predict(X(pool2, cols), num_iteration=m_.best_iteration)
        p0 = m_.predict(X(te, cols), num_iteration=m_.best_iteration) + te.log_idx.values
        _, a, k = best; c = np.nan_to_num(correction(pool2, te, k)) if a > 0 else 0.0
        row[name] = mdape(te, p0); row[name + "+E2"] = mdape(te, p0 + a * c); row[name + "_E2_params"] = [a, k]
        if seed == SEEDS[0]:
            te[f"r_{name}"] = np.log(te.price) - p0; te[f"r_{name}_E2"] = np.log(te.price) - (p0 + a * c)
            te[["unique_id", "sector", "lsoa21", f"r_{name}", f"r_{name}_E2"]].to_parquet(ROOT / f"data/processed/test_resid_{name.replace('+', '_')}.parquet")
    res["seeds"][seed] = row; print(seed, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
summ = {}
for k in ["v2", "v2+E2", "v2+E1", "v2+E1+E2"]:
    v = np.array([res["seeds"][sd][k] for sd in SEEDS]); g = np.array([res["seeds"][sd]["v2"] for sd in SEEDS]) - v
    summ[k] = dict(mdape_mean=float(v.mean()), gain_pts=float(g.mean() * 100), gain_sd=float(g.std() * 100))
    print(f"{k:10s} mdape {v.mean():.4f}  gain {g.mean()*100:+.2f} pts (sd {g.std()*100:.2f})")
res["summary"] = summ; json.dump(res, open(OUT / "metrics_v4_tests.json", "w"), indent=1)
s.to_parquet(ROOT / "data/processed/model_frame_v4.parquet")
