"""Version 5 tests: each candidate layer added to the v2 model on its own, then all together. 3 seeds, same split
(train 2015-2023 cleaned, early-stop 2024 cleaned, test Jan 2025 - Aug 2026), full-size model."""
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"
s = pd.read_parquet(ROOT / "data/processed/model_frame_v5.parquet"); keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
BASE = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime",
        "imd_barriers", "imd_living_env", "lvl_sector_type", "lvl_lsoa", "n_sector_type", "property_type", "tenure", "new_build"]
EPC = ["floor_area", "rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas"]
KNN = ["knn_lvl", "knn_dist", "knn_ppsqm"]; PREV = ["prev_defl", "years_since_prev", "prev_nb"]
V2 = BASE + EPC + KNN + PREV
EXACT = {"lat": "xlat", "lon": "xlon", "knn_lvl": "xknn_lvl", "knn_dist": "xknn_dist", "knn_ppsqm": "xknn_ppsqm"}
LAYERS = {
    "plot": ["plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home"],
    "street": ["lvl_street_type", "n_street_type", "lvl_postcode", "n_postcode"],
    "size_nn": ["size_nn_lvl", "size_nn_n", "size_nn_ppsqm"],
    "epc_x": ["wall_type", "ceiling_m", "floor_level_n", "top_floor", "heated_rooms", "glazed_area_n", "fireplaces",
              "wall_insulated", "loft_mm", "glazing", "elec_heating", "heat_pump", "woodburner", "low_energy_light", "solar_pv"],
    "voa": ["ct_band_mean", "ct_share_a", "ct_share_d_plus", "ct_share_pre1919", "ct_share_post2000"],
}
def X(d, cols):
    x = d[cols].copy(); x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int); return x.astype(float)
tr = s[(s.sale_date <= "2023-12-31") & s.unique_id.isin(keep)]; va = s[(s.sale_date > "2023-12-31") & (s.sale_date <= "2024-12-31") & s.unique_id.isin(keep)]
te = s[s.sale_date > "2024-12-31"]
def run(cols, seed, params=None):
    P = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=30, feature_fraction=0.8, bagging_fraction=0.8,
             bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=seed) | (params or {})
    dt = lgb.Dataset(X(tr, cols), tr.y_defl, categorical_feature=["property_type"])
    m = lgb.train(P, dt, 6000, valid_sets=[lgb.Dataset(X(va, cols), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
    p = m.predict(X(te, cols), num_iteration=m.best_iteration) + te.log_idx.values
    ape = np.abs(np.exp(p) - te.price.values) / te.price.values
    pv = m.predict(X(va, cols), num_iteration=m.best_iteration) + va.log_idx.values
    return dict(mdape=float(np.median(ape)), within10=float((ape <= .1).mean()), val_mdape=float(np.median(np.abs(np.exp(pv) - va.price.values) / va.price.values)), trees=m.best_iteration)

if __name__ == "__main__":
    exact = [EXACT.get(c, c) for c in V2]
    CONFIGS = {"v2": V2, "exact": exact} | {k: V2 + v for k, v in LAYERS.items()} | {"all": exact + sum(LAYERS.values(), [])}
    only = sys.argv[1:] or list(CONFIGS)
    res = json.load(open(OUT / "metrics_v5_tests.json")) if (OUT / "metrics_v5_tests.json").exists() else {}
    for name in only:
        runs = [run(CONFIGS[name], sd) for sd in (1, 2, 3)]
        res[name] = {k: [r[k] for r in runs] for k in runs[0]}
        print(f"{name:8s} test {np.mean(res[name]['mdape']):.4f} {[round(x, 4) for x in res[name]['mdape']]}  val {np.mean(res[name]['val_mdape']):.4f}  w10 {np.mean(res[name]['within10']):.3f}", flush=True)
        json.dump(res, open(OUT / "metrics_v5_tests.json", "w"), indent=1)
    if "v2" in res:
        b = np.array(res["v2"]["mdape"])
        for k, v in res.items():
            g = b - np.array(v["mdape"]); print(f"{k:8s} gain {g.mean()*100:+.2f} pts (sd {g.std()*100:.2f})")
