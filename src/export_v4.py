"""Version 4 dashboard model: v2 features + a local correction from recent nearby sales.

Why: on 2025-26 sales the v2 model under-valued fast-rising areas (Conisbrough, Denaby, Mexborough) and
over-valued Bawtry and Tickhill, because one Doncaster-wide price index can't follow areas moving at
different speeds. The fix measures how far off the model has been on the nearest recent sales and shifts
the estimate by part of that.

  A. tune:  compact model trained to 2022, early-stopped on 2023; residuals on 2023-24 sales; choose the share
            (alpha) and number of neighbours (k) that minimise 2024 error. 80% ranges from these 2024 errors.
  B. test:  compact model trained to 2023, early-stopped on 2024; residual pool = 2024 onward; report 2025-26 accuracy.
  C. production: the same model trained on cleaned sales up to 12 months before the valuation month, so the
            last 12 months' residuals are out of sample, exactly as in B. The dashboard applies the correction
            from those residuals (stored in comps.csv)."""
import json, csv, pathlib, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.neighbors import BallTree
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; D = OUT / "dash2"
s = pd.read_parquet(ROOT / "data/processed/model_frame_v2.parquet").sort_values(["sale_date", "unique_id"]).reset_index(drop=True)
idx = pd.read_csv(OUT / "price_index_v2.csv", index_col=0, parse_dates=True)["index"]
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
BASE = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime",
        "imd_barriers", "imd_living_env", "lvl_sector_type", "lvl_lsoa", "n_sector_type", "property_type", "tenure", "new_build"]
EPC = ["floor_area", "rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas"]
FULL = BASE + EPC + ["knn_lvl", "knn_dist", "knn_ppsqm", "prev_defl", "years_since_prev", "prev_nb"]
P = dict(objective="regression_l1", learning_rate=0.08, num_leaves=31, min_data_in_leaf=40, feature_fraction=0.8,
         bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=42)
LAG_DAYS, POOL_MONTHS, BANDS = 60, 12, [100_000, 150_000, 200_000, 300_000]
def X(d):
    x = d[FULL].copy(); x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int); return x.astype(float)
def wcsv(name, header, rows):
    with open(D / name, "w", newline="") as f: w = csv.writer(f); w.writerow(header); w.writerows(rows)
def between(a, b, cleaned=False):
    d = s[(s.sale_date > a) & (s.sale_date <= b)]; return d[d.unique_id.isin(keep)] if cleaned else d
def fit_es(tr, va):
    dt = lgb.Dataset(X(tr), tr.y_defl, categorical_feature=["property_type"])
    return lgb.train(P, dt, 4000, valid_sets=[lgb.Dataset(X(va), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(120, verbose=False)])
def correction(pool, target, k, lag_days=LAG_DAYS):
    """Median residual of the k nearest pool sales sold 12 months to `lag_days` days before each target sale's month."""
    out = np.zeros(len(target)); tr_ = np.radians(target[["lat", "lon"]].values)
    pdates, prad, pr = pool.sale_date.values, np.radians(pool[["lat", "lon"]].values), pool.r.values
    for m in pd.date_range(target.month.min(), target.month.max(), freq="MS"):
        q = (target.month == m).values
        if not q.any(): continue
        sel = (pdates < np.datetime64(m - pd.Timedelta(days=lag_days))) & (pdates >= np.datetime64(m - pd.DateOffset(months=POOL_MONTHS)))
        if sel.sum() < k: continue
        _, ind = BallTree(prad[sel], metric="haversine").query(tr_[q], k=k); out[q] = np.median(pr[sel][ind], axis=1)
    return out
def met(d, logp):
    p = np.exp(logp); ape = np.abs(p - d.price.values) / d.price.values
    return dict(n=int(len(d)), mae=float(np.mean(np.abs(p - d.price.values))), mdape=float(np.median(ape)), within10=float((ape <= .1).mean()), within20=float((ape <= .2).mean()))
grp = lambda p, hasprev: np.digitize(p, BANDS) + 5 * hasprev.astype(int)

# ---------- A. tune alpha and k on 2024 ----------
mA = fit_es(between("2000-01-01", "2022-12-31", True), between("2022-12-31", "2023-12-31", True))
poolA = between("2022-12-31", "2024-12-31").copy(); poolA["r"] = poolA.y_defl.values - mA.predict(X(poolA), num_iteration=mA.best_iteration)
v24 = between("2023-12-31", "2024-12-31").copy(); bA = mA.predict(X(v24), num_iteration=mA.best_iteration) + v24.log_idx.values
grid = {(a, k): met(v24, bA + a * correction(poolA, v24, k))["mdape"] for k in (10, 20, 40) for a in (0.25, 0.5, 0.75, 1.0)}
(ALPHA, K), best = min(grid.items(), key=lambda kv: kv[1])
print(f"tuned on 2024: alpha={ALPHA}, k={K}: {best:.4f} (no correction {met(v24, bA)['mdape']:.4f})")
pA = bA + ALPHA * correction(poolA, v24, K); rA = np.log(v24.price.values) - pA; gA = grp(np.exp(pA), v24.prev_defl.notna().values)
conf = [[float(np.quantile(rA[gA == g], .10)), float(np.quantile(rA[gA == g], .90))] for g in range(10)]

# ---------- B. test on 2025-26 ----------
mB = fit_es(between("2000-01-01", "2023-12-31", True), between("2023-12-31", "2024-12-31", True)); n_iter = mB.best_iteration
te = s[s.sale_date > "2024-12-31"].copy(); poolB = s[s.sale_date > "2023-12-31"].copy()
poolB["r"] = poolB.y_defl.values - mB.predict(X(poolB), num_iteration=n_iter)
p0 = mB.predict(X(te), num_iteration=n_iter) + te.log_idx.values; cB = correction(poolB, te, K); tp = p0 + ALPHA * cB
test_m, test_raw = met(te, tp), met(te, p0)
tg = grp(np.exp(tp), te.prev_defl.notna().values); rt = np.log(te.price.values) - tp
cover = float(np.mean([conf[g][0] <= x <= conf[g][1] for g, x in zip(tg, rt)]))
print("test with correction", {k: round(v, 4) for k, v in test_m.items()}, "| without", round(test_raw["mdape"], 4), "| coverage", round(cover, 3), "| trees", n_iter)
sec = pd.DataFrame({"sector": te.sector.values, "r0": np.log(te.price.values) - p0, "r1": rt}).groupby("sector").agg(n=("r0", "size"), b0=("r0", "median"), b1=("r1", "median")).query("n >= 40")
area_bias = dict(sd_before=float(((np.exp(sec.b0) - 1) * 100).std()), sd_after=float(((np.exp(sec.b1) - 1) * 100).std()))
print("sector bias spread (sd, %):", {k: round(v, 2) for k, v in area_bias.items()})
sec["before_pct"] = (np.exp(sec.b0) - 1) * 100; sec["after_pct"] = (np.exp(sec.b1) - 1) * 100
wards = pd.read_csv(D / "sectors.csv").set_index("sector").wards
wcsv("area_bias.csv", ["sector", "wards", "n", "bias_before_pct", "bias_after_pct"],
     [[k, wards.get(k, ""), int(r.n), round(r.before_pct, 1), round(r.after_pct, 1)] for k, r in sec.reindex(sec.before_pct.abs().sort_values(ascending=False).index).iterrows()])

# ---------- C. production model: trained to 12 months before the valuation month ----------
val_month = s.month.max() + pd.DateOffset(months=1); pool_start = val_month - pd.DateOffset(months=POOL_MONTHS)
trC = s[(s.sale_date < pool_start) & s.unique_id.isin(keep)]
prod = lgb.train(P, lgb.Dataset(X(trC), trC.y_defl, categorical_feature=["property_type"]), n_iter)
(OUT / "model").mkdir(exist_ok=True); prod.save_model(str(OUT / "model/doncaster_lgbm_v4.txt"))
poolC = s[s.sale_date >= pool_start].copy(); poolC["r"] = poolC.y_defl.values - prod.predict(X(poolC))
print(f"production: trained on {len(trC):,} sales before {pool_start:%b %Y}; {len(poolC):,} recent sales give the local correction "
      f"(median residual {100*(np.exp(poolC.r.median())-1):+.1f}%)")

def flat(tree):
    nodes = []
    def walk(n):
        i = len(nodes); nodes.append(None)
        if "leaf_value" in n: nodes[i] = [-1, 0, 0, 0, round(n["leaf_value"], 9), 0, 0]; return i
        if n["decision_type"] == "==": thr, kind = sum(1 << int(c) for c in str(n["threshold"]).split("||")), 1
        else: thr, kind = float(n["threshold"]), 0
        l = walk(n["left_child"]); rr = walk(n["right_child"])
        nodes[i] = [n["split_feature"], thr, l, rr, 1 if n.get("default_left", True) else 0, kind, {"None": 0, "Zero": 1, "NaN": 2}[n.get("missing_type", "NaN")]]; return i
    walk(tree["tree_structure"]); return nodes
trees = [flat(t) for t in prod.dump_model()["tree_info"]]
json.dump([{"tree": i, "nodes": json.dumps(t, separators=(",", ":"))} for i, t in enumerate(trees)], open(D / "model_trees.json", "w"), separators=(",", ":"))

# ---------- dashboard datasets ----------
meta = dict(features=FULL, bands=BANDS, conformal=conf, index_latest=float(idx.iloc[-1]), index_latest_month=idx.index[-1].strftime("%Y-%m"),
            latest_sale=s.sale_date.max().strftime("%Y-%m-%d"), n_sales_model=int(len(s)), valuation_month=val_month.strftime("%Y-%m"),
            local_alpha=ALPHA, local_k=K, local_pool_from=pool_start.strftime("%Y-%m"), train_end=(pool_start - pd.Timedelta(days=1)).strftime("%Y-%m"))
json.dump([{"key": k, "value": json.dumps(v) if isinstance(v, (list, dict)) else str(v)} for k, v in meta.items()], open(D / "model_meta.json", "w"))
win = s[(s.month >= val_month - pd.DateOffset(months=36)) & (s.month < val_month)].copy()
win["addr"] = win.address_key.str.split("|").apply(lambda a: " ".join(x for x in [a[0], a[1], a[2].title()] if x).strip())
win = win.merge(poolC[["unique_id", "r"]], on="unique_id", how="left")
wcsv("comps.csv", ["date", "price", "postcode", "type", "tenure", "new_build", "lat", "lon", "address", "y_defl", "floor_area", "resid"],
     [[r.sale_date.strftime("%Y-%m-%d"), int(r.price), r.postcode, r.property_type, r.tenure, int(r.new_build), round(r.lat, 5), round(r.lon, 5), r.addr,
       round(r.y_defl, 5), "" if pd.isna(r.floor_area) else round(r.floor_area, 1), "" if pd.isna(r.r) else round(r.r, 4)] for r in win.itertuples()])
v24m = met(v24, pA)
acc = [["dashboard", "test_2025_26", k, v] for k, v in test_m.items()] + [["dashboard", "validation_2024", k, v] for k, v in v24m.items()] + [["dashboard", "test_2025_26", "coverage_80", cover]]
hp = te.prev_defl.notna().values
acc += [["dashboard_prior_sale", "test_2025_26", k, v] for k, v in met(te[hp], tp[hp]).items()] + [["dashboard_no_prior_sale", "test_2025_26", k, v] for k, v in met(te[~hp], tp[~hp]).items()]
acc += [["dashboard_without_local_correction", "test_2025_26", k, v] for k, v in test_raw.items()]
wcsv("accuracy.csv", ["model", "split", "metric", "value"], acc)
t = te.assign(pred=np.exp(tp)); t["ape"] = np.abs(t.pred - t.price) / t.price
t["band"] = pd.cut(t.price, [0] + BANDS + [10**9], labels=["<100k", "100-150k", "150-200k", "200-300k", "300k+"])
br = []
for dim, col in [("type", "property_type"), ("band", "band")]:
    for gname, g in t.groupby(col, observed=True): br.append([dim, str(gname), len(g), round(g.ape.median(), 5), round((g.ape <= .1).mean(), 4)])
for gname, g in t.groupby(t.floor_area.notna()): br.append(["epc", "EPC matched" if gname else "No EPC match", len(g), round(g.ape.median(), 5), round((g.ape <= .1).mean(), 4)])
wcsv("accuracy_breakdown.csv", ["dimension", "group", "n", "mdape", "within10"], br)
imp = pd.Series(prod.feature_importance("gain"), index=prod.feature_name()); imp = (imp / imp.sum()).sort_values(ascending=False)
wcsv("feature_importance.csv", ["feature", "gain_share"], [[k, round(v, 5)] for k, v in imp.items()])
smp = t.sample(1500, random_state=7)
wcsv("test_sample.csv", ["price", "predicted", "type"], [[int(a), int(b), c] for a, b, c in zip(smp.price, smp.pred, smp.property_type)])
json.dump(dict(alpha=ALPHA, k=K, tune_grid={f"{a}|{k}": v for (a, k), v in grid.items()}, test=test_m, test_without_correction=test_raw, coverage=cover,
               trees=n_iter, area_bias=area_bias, train_end=meta["train_end"], pool_from=meta["local_pool_from"]), open(OUT / "export_v4_summary.json", "w"), indent=1)
print("done")

# ---------- table of tested changes (v3 data layers + v4 local tests) ----------
m3 = json.load(open(OUT / "metrics_v3_layers.json"))["summary"]; m4 = json.load(open(OUT / "metrics_v4_tests.json"))["summary"]
L3 = {"flood": "Flood risk (Environment Agency)", "transport": "Station distance and bus stops (NaPTAN)", "schools": "Distance to schools and to a Good or Outstanding primary",
      "osm": "Supermarkets, parks, GPs, pubs and cafés, junctions, main roads (OpenStreetMap)", "rural": "Urban or rural neighbourhood (ONS)", "all": "All six data layers together"}
rows_ = [[k, L3[k], round(m3[k]["gain_pts"], 3), round(m3[k]["gain_sd"], 3), "Left out: within noise"] for k in L3]
rows_ += [["recent_levels", "Local prices from the last 12 months and local momentum", round(m4["v2+E1"]["gain_pts"], 3), round(m4["v2+E1"]["gain_sd"], 3), "Left out: worse"],
          ["local_correction", "Local correction from the nearest recent sales", round(m4["v2+E2"]["gain_pts"], 3), round(m4["v2+E2"]["gain_sd"], 3),
           f"Kept: area bias spread {area_bias['sd_before']:.1f}% to {area_bias['sd_after']:.1f}%"]]
wcsv("layer_tests.csv", ["layer", "label", "gain_pts", "gain_sd", "decision"], rows_)
