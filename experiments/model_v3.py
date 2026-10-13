"""Version 3 test: do flood risk, transport, schools, OpenStreetMap amenities or rural-urban class improve the v2 model?

Same temporal split and cleaned training set as v2. Each layer is added on its own to the full v2 feature set and
fitted with 3 seeds; the gain is the paired mean difference in test median error, so seed noise is visible."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, numpy as np, pandas as pd, lightgbm as lgb

ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; P_ = ROOT / "data/processed"
s = pd.read_parquet(P_ / "model_frame_v2.parquet")
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
st, sch, osm = pd.read_parquet(P_ / "amenities_static.parquet"), pd.read_parquet(P_ / "amenities_schools.parquet"), pd.read_parquet(P_ / "amenities_osm.parquet")
n0 = len(s)
s["year"] = s.sale_date.dt.year.clip(2014, 2026)
s = s.merge(st, on="postcode", how="left").merge(sch, on=["postcode", "year"], how="left").merge(osm, on="postcode", how="left")
assert len(s) == n0, "row count changed in merge"

BASE = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime",
        "imd_barriers", "imd_living_env", "lvl_sector_type", "lvl_lsoa", "n_sector_type", "property_type", "tenure", "new_build"]
EPC = ["floor_area", "rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas"]
KNN = ["knn_lvl", "knn_dist", "knn_ppsqm"]; PREV = ["prev_defl", "years_since_prev", "prev_nb"]
FULL = BASE + EPC + KNN + PREV
LAYERS = {"flood": ["flood_hm", "flood_any"], "transport": ["dist_rail_km", "bus_stops_500m"],
          "schools": ["dist_primary_km", "dist_secondary_km", "dist_good_primary_km"],
          "osm": ["dist_supermarket_km", "dist_park_km", "dist_gp_km", "dist_junction_km", "food_drink_800m", "dist_major_road_m"],
          "rural": ["rural"]}
LAYERS["all"] = sum(LAYERS.values(), [])
print("coverage:", {c: f"{s[c].notna().mean():.1%}" for c in LAYERS["all"]})

def X(d, cols):
    x = d[cols].copy()
    x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int)
    return x.astype(float)
TRAIN_END, VAL_END = pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")
tr = s[(s.sale_date <= TRAIN_END) & s.unique_id.isin(keep)]; va = s[(s.sale_date > TRAIN_END) & (s.sale_date <= VAL_END) & s.unique_id.isin(keep)]
te = s[s.sale_date > VAL_END]
def run(cols, seed):
    P = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=30, feature_fraction=0.8,
             bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=seed)
    dt = lgb.Dataset(X(tr, cols), tr.y_defl, categorical_feature=["property_type"])
    m = lgb.train(P, dt, 5000, valid_sets=[lgb.Dataset(X(va, cols), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
    p = np.exp(m.predict(X(te, cols), num_iteration=m.best_iteration) + te.log_idx.values)
    ape = np.abs(p - te.price.values) / te.price.values
    return dict(mdape=float(np.median(ape)), within10=float((ape <= .1).mean()), within20=float((ape <= .2).mean()), trees=m.best_iteration), m

SEEDS = [1, 2, 3]; res = {}
for name, extra in [("v2_full", [])] + [(k, v) for k, v in LAYERS.items()]:
    runs = [run(FULL + extra, sd)[0] for sd in SEEDS]
    res[name] = {k: [r[k] for r in runs] for k in runs[0]}
    print(name, "mdape", [round(x, 4) for x in res[name]["mdape"]], "within10", [round(x, 3) for x in res[name]["within10"]], flush=True)
base = np.array(res["v2_full"]["mdape"])
summary = {k: dict(mdape_mean=float(np.mean(v["mdape"])), within10_mean=float(np.mean(v["within10"])), within20_mean=float(np.mean(v["within20"])),
                   gain_pts=float(np.mean(base - np.array(v["mdape"])) * 100), gain_sd=float(np.std(base - np.array(v["mdape"])) * 100)) for k, v in res.items()}
for k, v in summary.items(): print(f"{k:10s} mdape {v['mdape_mean']:.4f}  w10 {v['within10_mean']:.3f}  gain {v['gain_pts']:+.2f} pts (sd {v['gain_sd']:.2f})")
json.dump({"runs": res, "summary": summary}, open(OUT / "metrics_v3_layers.json", "w"), indent=1)
s.to_parquet(P_ / "model_frame_v3.parquet")
