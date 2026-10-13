"""Version 5 dashboard model: v2 features + plot size, street/postcode prices and more EPC detail, a size-capped
LightGBM chosen on 2024 validation, the local correction from v4, and node counts so the browser can explain each
estimate (TreeSHAP).

  0. choose browser-sized settings on 2024 validation (train to 2023), largest model file about 6 MB
  A. tune the local correction (alpha, k) on 2024 with a model trained to 2022; 80% ranges from those 2024 errors
  B. test on 2025-26 with a model trained to 2023
  C. production model trained to 12 months before the valuation month; the last 12 months give the correction
  D. condition calibration again (out-of-fold, model without last-sale features)"""
import json, csv, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.neighbors import BallTree
from sklearn.model_selection import KFold
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; D = OUT / "dash2"
s = pd.read_parquet(ROOT / "data/processed/model_frame_v5.parquet").sort_values(["sale_date", "unique_id"]).reset_index(drop=True)
idx = pd.read_csv(OUT / "price_index_v2.csv", index_col=0, parse_dates=True)["index"]
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
BASE = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime",
        "imd_barriers", "imd_living_env", "lvl_sector_type", "lvl_lsoa", "n_sector_type", "property_type", "tenure", "new_build"]
EPC = ["floor_area", "rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas"]
FULL = (BASE + EPC + ["knn_lvl", "knn_dist", "knn_ppsqm", "prev_defl", "years_since_prev", "prev_nb"]
        + ["plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home"] + ["lvl_street_type", "n_street_type", "lvl_postcode", "n_postcode"]
        + ["wall_type", "ceiling_m", "floor_level_n", "top_floor", "heated_rooms", "glazed_area_n", "fireplaces",
           "wall_insulated", "loft_mm", "glazing", "elec_heating", "heat_pump", "woodburner", "low_energy_light", "solar_pv"])
GROUPS = {"Location": ["lat", "lon", "dist_centre_km"], "Neighbourhood deprivation": [c for c in BASE if c.startswith("imd_")],
          "Prices nearby": ["lvl_sector_type", "lvl_lsoa", "n_sector_type", "knn_lvl", "knn_dist", "knn_ppsqm"],
          "Prices on the street and postcode": ["lvl_street_type", "n_street_type", "lvl_postcode", "n_postcode"],
          "Size": ["floor_area", "rooms", "heated_rooms"], "Plot": ["plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home"],
          "Type, age and build": ["property_type", "tenure", "new_build", "age_year", "bungalow", "built_form_code", "extensions", "wall_type", "ceiling_m",
                                  "floor_level_n", "top_floor", "glazed_area_n", "fireplaces"],
          "Energy, heating and upgrades": ["sap_current", "sap_potential", "sap_gap", "mains_gas", "wall_insulated", "loft_mm", "glazing", "elec_heating",
                                           "heat_pump", "woodburner", "low_energy_light", "solar_pv"],
          "Last sale": ["prev_defl", "years_since_prev", "prev_nb"]}
assert sorted(sum(GROUPS.values(), [])) == sorted(FULL)
LAG_DAYS, POOL_MONTHS, BANDS = 60, 12, [100_000, 150_000, 200_000, 300_000]
def X(d, cols=FULL):
    x = d[cols].copy(); x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int); return x.astype(float)
def wcsv(name, header, rows):
    with open(D / name, "w", newline="") as f: w = csv.writer(f); w.writerow(header); w.writerows(rows)
def between(a, b, cleaned=False):
    d = s[(s.sale_date > a) & (s.sale_date <= b)]; return d[d.unique_id.isin(keep)] if cleaned else d
def met(d, logp):
    p = np.exp(logp); ape = np.abs(p - d.price.values) / d.price.values
    return dict(n=int(len(d)), mae=float(np.mean(np.abs(p - d.price.values))), mdape=float(np.median(ape)), within10=float((ape <= .1).mean()), within20=float((ape <= .2).mean()))
def fit_es(tr, va, P, cols=FULL):
    dt = lgb.Dataset(X(tr, cols), tr.y_defl, categorical_feature=["property_type"])
    return lgb.train(P, dt, 6000, valid_sets=[lgb.Dataset(X(va, cols), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
def correction(pool, target, k, lag_days=LAG_DAYS):
    out = np.zeros(len(target)); tr_ = np.radians(target[["lat", "lon"]].values)
    pdates, prad, pr = pool.sale_date.values, np.radians(pool[["lat", "lon"]].values), pool.r.values
    for m in pd.date_range(target.month.min(), target.month.max(), freq="MS"):
        q = (target.month == m).values
        if not q.any(): continue
        sel = (pdates < np.datetime64(m - pd.Timedelta(days=lag_days))) & (pdates >= np.datetime64(m - pd.DateOffset(months=POOL_MONTHS)))
        if sel.sum() < k: continue
        _, ind = BallTree(prad[sel], metric="haversine").query(tr_[q], k=k); out[q] = np.median(pr[sel][ind], axis=1)
    return out
grp = lambda p, hasprev: np.digitize(p, BANDS) + 5 * hasprev.astype(int)
def flat(tree):
    nodes = []
    def walk(n):
        i = len(nodes); nodes.append(None)
        if "leaf_value" in n: nodes[i] = [-1, 0, 0, 0, round(n["leaf_value"], 9), 0, 0, int(n["leaf_count"])]; return i
        if n["decision_type"] == "==": thr, kind = sum(1 << int(c) for c in str(n["threshold"]).split("||")), 1
        else: thr, kind = float(n["threshold"]), 0
        l = walk(n["left_child"]); rr = walk(n["right_child"])
        nodes[i] = [n["split_feature"], thr, l, rr, 1 if n.get("default_left", True) else 0, kind, {"None": 0, "Zero": 1, "NaN": 2}[n.get("missing_type", "NaN")], int(n["internal_count"])]; return i
    walk(tree["tree_structure"]); return nodes
size_mb = lambda m: len(json.dumps([{"tree": i, "nodes": json.dumps(t, separators=(",", ":"))} for i, t in enumerate(flat(t) for t in m.dump_model()["tree_info"])], separators=(",", ":"))) / 1e6

if __name__ == "__main__":
    # ---------- 0. browser-sized settings, chosen on 2024 ----------
    base = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42)
    cands = [dict(learning_rate=0.08, num_leaves=31, min_data_in_leaf=40, feature_fraction=0.8, lambda_l2=1.0),
             dict(learning_rate=0.06, num_leaves=31, min_data_in_leaf=80, feature_fraction=0.65, lambda_l2=20.0),
             dict(learning_rate=0.08, num_leaves=63, min_data_in_leaf=80, feature_fraction=0.65, lambda_l2=20.0),
             dict(learning_rate=0.05, num_leaves=31, min_data_in_leaf=80, feature_fraction=0.65, lambda_l2=20.0)]
    tr23, va24 = between("2000-01-01", "2023-12-31", True), between("2023-12-31", "2024-12-31", True)
    scored = []
    for c in cands:
        m = fit_es(tr23, va24, base | c); v = met(va24, m.predict(X(va24), num_iteration=m.best_iteration) + va24.log_idx.values)["mdape"]
        mb = size_mb(m) * m.best_iteration / m.num_trees()
        scored.append((v, mb, c, m.best_iteration)); print("candidate", c, "val", round(v, 4), "trees", m.best_iteration, "≈", round(mb, 1), "MB", flush=True)
    # smallest model whose 2024 error is within 0.03 points of the best (differences that small are seed noise), file <= 6 MB
    fit_ok = [x for x in scored if x[1] <= 6.0]; vbest = min(x[0] for x in fit_ok)
    v, mb, best, _ = min([x for x in fit_ok if x[0] <= vbest + 0.0003], key=lambda x: x[1]); P = base | best
    print("chosen", best, "val", round(v, 4))

    # ---------- A. tune alpha, k on 2024 ----------
    mA = fit_es(between("2000-01-01", "2022-12-31", True), between("2022-12-31", "2023-12-31", True), P)
    poolA = between("2022-12-31", "2024-12-31").copy(); poolA["r"] = poolA.y_defl.values - mA.predict(X(poolA), num_iteration=mA.best_iteration)
    v24 = between("2023-12-31", "2024-12-31").copy(); bA = mA.predict(X(v24), num_iteration=mA.best_iteration) + v24.log_idx.values
    grid = {(a, k): met(v24, bA + a * correction(poolA, v24, k))["mdape"] for k in (10, 20, 40) for a in (0.25, 0.5, 0.75, 1.0)}
    (ALPHA, K), bestc = min(grid.items(), key=lambda kv: kv[1])
    print(f"local correction tuned on 2024: alpha={ALPHA}, k={K}: {bestc:.4f} (none {met(v24, bA)['mdape']:.4f})")
    pA = bA + ALPHA * correction(poolA, v24, K); rA = np.log(v24.price.values) - pA; gA = grp(np.exp(pA), v24.prev_defl.notna().values)
    conf = [[float(np.quantile(rA[gA == g], .10)), float(np.quantile(rA[gA == g], .90))] for g in range(10)]

    # ---------- B. test 2025-26 ----------
    mB = fit_es(tr23, va24, P); n_iter = mB.best_iteration
    te = s[s.sale_date > "2024-12-31"].copy(); poolB = s[s.sale_date > "2023-12-31"].copy()
    poolB["r"] = poolB.y_defl.values - mB.predict(X(poolB), num_iteration=n_iter)
    p0 = mB.predict(X(te), num_iteration=n_iter) + te.log_idx.values; tp = p0 + ALPHA * correction(poolB, te, K)
    test_m, test_raw = met(te, tp), met(te, p0)
    tg = grp(np.exp(tp), te.prev_defl.notna().values); rt = np.log(te.price.values) - tp
    cover = float(np.mean([conf[g][0] <= x <= conf[g][1] for g, x in zip(tg, rt)]))
    print("test", {k: round(v, 4) for k, v in test_m.items()}, "| without correction", round(test_raw["mdape"], 4), "| coverage", round(cover, 3), "| trees", n_iter)
    sec = pd.DataFrame({"sector": te.sector.values, "r0": np.log(te.price.values) - p0, "r1": rt}).groupby("sector").agg(n=("r0", "size"), b0=("r0", "median"), b1=("r1", "median")).query("n >= 40")
    sec["before_pct"] = (np.exp(sec.b0) - 1) * 100; sec["after_pct"] = (np.exp(sec.b1) - 1) * 100
    area_bias = dict(sd_before=float(sec.before_pct.std()), sd_after=float(sec.after_pct.std()))
    wards = pd.read_csv(D / "sectors.csv").set_index("sector").wards
    wcsv("area_bias.csv", ["sector", "wards", "n", "bias_before_pct", "bias_after_pct"],
         [[k, wards.get(k, ""), int(r.n), round(r.before_pct, 1), round(r.after_pct, 1)] for k, r in sec.reindex(sec.before_pct.abs().sort_values(ascending=False).index).iterrows()])

    # ---------- C. production ----------
    val_month = s.month.max() + pd.DateOffset(months=1); pool_start = val_month - pd.DateOffset(months=POOL_MONTHS)
    trC = s[(s.sale_date < pool_start) & s.unique_id.isin(keep)]
    prod = lgb.train(P, lgb.Dataset(X(trC), trC.y_defl, categorical_feature=["property_type"]), n_iter)
    (OUT / "model").mkdir(exist_ok=True); prod.save_model(str(OUT / "model/doncaster_lgbm_v5.txt"))
    poolC = s[s.sale_date >= pool_start].copy(); poolC["r"] = poolC.y_defl.values - prod.predict(X(poolC))
    trees = [flat(t) for t in prod.dump_model()["tree_info"]]
    json.dump([{"tree": i, "nodes": json.dumps(t, separators=(",", ":"))} for i, t in enumerate(trees)], open(D / "model_trees.json", "w"), separators=(",", ":"))
    print(f"production: {len(trC):,} sales before {pool_start:%b %Y}; {len(poolC):,} recent sales for the correction; model file {(D / 'model_trees.json').stat().st_size/1e6:.1f} MB")

    # ---------- D. condition calibration (no last-sale features, out-of-fold) ----------
    NOPREV = [c for c in FULL if c not in ("prev_defl", "years_since_prev", "prev_nb")]
    oof = np.zeros(len(s)); Xa = X(s, NOPREV)
    for a, b in KFold(5, shuffle=True, random_state=1).split(Xa):
        mm = lgb.train(P, lgb.Dataset(Xa.iloc[a], s.y_defl.iloc[a], categorical_feature=["property_type"]), n_iter); oof[b] = mm.predict(Xa.iloc[b])
    s["resid_np"] = s.y_defl.values - oof
    key = s.drop_duplicates(["address_key", "sale_date"]).set_index(["address_key", "sale_date"])["resid_np"]
    pairs = s[s.prev_price.notna() & (s.prev_new_build == False) & (s.prev_date >= "2015-01-01")].copy()
    pairs["prev_resid"] = [key.get((a, d), np.nan) for a, d in zip(pairs.address_key, pairs.prev_date)]
    pairs = pairs.dropna(subset=["prev_resid"]); pairs["hold_m"] = (pairs.sale_date - pairs.prev_date).dt.days / 30.44
    flips = pairs[(pairs.hold_m >= 3) & (pairs.hold_m <= 18)]; control = pairs[pairs.hold_m >= 60]
    pc = lambda v: round(100 * (np.exp(v) - 1), 1); needs, refurb = np.median(flips.prev_resid), np.median(flips.resid_np)
    cond = [("needs_full_renovation", "Needs full renovation", pc(needs), pc(np.quantile(flips.prev_resid, .25)), pc(np.quantile(flips.prev_resid, .75)), f"Median model residual at purchase for 3-18 month resales (n={len(flips)})"),
            ("dated", "Dated", pc(needs / 2), "", "", "Half of the needs-renovation discount (interpolated)"), ("average", "Average", 0.0, "", "", "Model baseline"),
            ("good", "Good", pc(refurb / 2), "", "", "Half of the refurbished premium (interpolated)"),
            ("recently_refurbished", "Recently refurbished", pc(refurb), pc(np.quantile(flips.resid_np, .25)), pc(np.quantile(flips.resid_np, .75)), f"Median model residual at resale for 3-18 month resales (n={len(flips)})")]
    wcsv("condition.csv", ["condition", "label", "adjustment_pct", "range_low_pct", "range_high_pct", "basis"], cond)
    print("condition:", [(c[0], c[2]) for c in cond], "control", pc(np.median(control.prev_resid)))

    # ---------- datasets ----------
    meta = dict(features=FULL, groups=GROUPS, bands=BANDS, conformal=conf, index_latest=float(idx.iloc[-1]), index_latest_month=idx.index[-1].strftime("%Y-%m"),
                latest_sale=s.sale_date.max().strftime("%Y-%m-%d"), n_sales_model=int(len(s)), valuation_month=val_month.strftime("%Y-%m"),
                local_alpha=ALPHA, local_k=K, local_pool_from=pool_start.strftime("%Y-%m"), train_end=(pool_start - pd.Timedelta(days=1)).strftime("%Y-%m"))
    json.dump([{"key": k, "value": json.dumps(v) if isinstance(v, (list, dict)) else str(v)} for k, v in meta.items()], open(D / "model_meta.json", "w"))
    win = s[(s.month >= val_month - pd.DateOffset(months=36)) & (s.month < val_month)].copy()
    win["addr"] = win.address_key.str.split("|").apply(lambda a: " ".join(x for x in [a[0], a[1], a[2].title()] if x).strip())
    win = win.merge(poolC[["unique_id", "r"]], on="unique_id", how="left")
    wcsv("comps.csv", ["date", "price", "postcode", "type", "tenure", "new_build", "lat", "lon", "address", "y_defl", "floor_area", "resid"],
         [[r.sale_date.strftime("%Y-%m-%d"), int(r.price), r.postcode, r.property_type, r.tenure, int(r.new_build), round(r.lat, 5), round(r.lon, 5), r.addr,
           round(r.y_defl, 5), "" if pd.isna(r.floor_area) else round(r.floor_area, 1), "" if pd.isna(r.r) else round(r.r, 4)] for r in win.itertuples()])
    v24m = met(v24, pA); hp = te.prev_defl.notna().values
    acc = [["dashboard", "test_2025_26", k, v] for k, v in test_m.items()] + [["dashboard", "validation_2024", k, v] for k, v in v24m.items()] + [["dashboard", "test_2025_26", "coverage_80", cover]]
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
    # ---------- ablation and tested-changes tables ----------
    m5 = json.load(open(OUT / "metrics_v5_tests.json")); mv2 = json.load(open(OUT / "metrics_v2.json"))
    names = {"v1_location": "Location and deprivation only (v1)", "plus_epc": "+ EPC (floor area, rooms, age, energy)", "plus_neighbours": "+ nearest-neighbour prices",
             "plus_last_sale": "+ last sale of the same home", "plus_last_sale_cleaned": "+ training data clean-up"}
    ab = [[k, names[k], round(v["mdape"], 5), round(v["within10"], 4), round(v["within20"], 4), round(v["mae"])] for k, v in mv2["ablation"].items()]
    ab.append(["v5_core", "+ plot size, street prices, more EPC detail (v5)", round(float(np.mean(m5["core"]["mdape"])), 5), round(float(np.mean(m5["core"]["within10"])), 4), "", ""])
    if "core_tuned" in m5: ab.append(["v5_tuned", "+ tuned settings (final, full size)", round(float(np.mean(m5["core_tuned"]["mdape"])), 5), round(float(np.mean(m5["core_tuned"]["within10"])), 4), "", ""])
    wcsv("ablation.csv", ["step", "label", "mdape", "within10", "within20", "mae"], ab)
    old = pd.read_csv(D / "layer_tests.csv")
    b5 = np.array(m5["v2"]["mdape"]); g = lambda k: (float(np.mean(b5 - np.array(m5[k]["mdape"])) * 100), float(np.std(b5 - np.array(m5[k]["mdape"])) * 100))
    ba = np.array(m5["all"]["mdape"]); ga = lambda k: (float(np.mean(ba - np.array(m5[k]["mdape"])) * 100), float(np.std(ba - np.array(m5[k]["mdape"])) * 100))
    new = [["plot", "Plot size from Land Registry title plans", *g("plot"), "Kept"], ["street", "Recent prices on the same street and postcode", *g("street"), "Kept"],
           ["epc_x", "More EPC detail: walls, loft, glazing, heating, fireplaces, ceiling height", *g("epc_x"), "Kept"],
           ["size_nn", "Prices of nearby homes of similar size", *g("size_nn"), "Left out: adds nothing once street prices are in"],
           ["exact", "Exact address position instead of postcode centre", *g("exact"), "Left out: within noise"],
           ["voa", "Neighbourhood council tax band mix (VOA)", *g("voa"), "Left out: adds nothing once the rest is in"]]
    if "core_tuned" in m5: new.append(["tuned", "Tuned LightGBM settings (more regularised)", float(np.mean(np.array(m5["core"]["mdape"]) - np.array(m5["core_tuned"]["mdape"])) * 100),
                                        float(np.std(np.array(m5["core"]["mdape"]) - np.array(m5["core_tuned"]["mdape"])) * 100), "Kept, at browser size"])
    new = [[a, b, round(c, 3), round(d, 3), e] for a, b, c, d, e in new]
    old = old[~old.layer.isin([r[0] for r in new])]          # re-running replaces this version's rows instead of repeating them
    wcsv("layer_tests.csv", ["layer", "label", "gain_pts", "gain_sd", "decision"], new + old.values.tolist())
    json.dump(dict(params=best, alpha=ALPHA, k=K, test=test_m, test_without_correction=test_raw, coverage=cover, trees=n_iter, area_bias=area_bias,
                   train_end=meta["train_end"], pool_from=meta["local_pool_from"], candidates=[dict(val=a, mb=b, params=c, trees=d) for a, b, c, d in scored]),
              open(OUT / "export_v5_summary.json", "w"), indent=1)
    print("done")
