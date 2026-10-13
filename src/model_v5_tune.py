"""Version 5: the kept feature set ('core' = v2 + plot + street + extra EPC fields), then a random search over
LightGBM settings chosen on 2024 validation only (the 2025-26 test is used once, for the winner vs the defaults)."""
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.argv = sys.argv[:1]
import model_v5_tests as M
CORE = M.V2 + M.LAYERS["plot"] + M.LAYERS["street"] + M.LAYERS["epc_x"]
res = json.load(open(M.OUT / "metrics_v5_tests.json"))
runs = [M.run(CORE, sd) for sd in (1, 2, 3)]; res["core"] = {k: [r[k] for r in runs] for k in runs[0]}
print(f"core     test {np.mean(res['core']['mdape']):.4f}  val {np.mean(res['core']['val_mdape']):.4f}", flush=True)
rng = np.random.default_rng(0); trials = []
space = dict(num_leaves=[31, 63, 127, 255], min_data_in_leaf=[10, 20, 40, 80], feature_fraction=[0.5, 0.65, 0.8, 1.0], lambda_l2=[0, 1, 5, 20],
             learning_rate=[0.03, 0.05], objective=["regression_l1", "huber", "regression"], max_bin=[255, 511], min_sum_hessian_in_leaf=[1e-3])
for t in range(18):
    p = {k: v[rng.integers(len(v))] for k, v in space.items()}
    if p["objective"] == "huber": p["alpha"] = 0.15
    r = M.run(CORE, 1, p); trials.append({"params": {k: (float(v) if isinstance(v, (np.floating, float)) else (int(v) if isinstance(v, (np.integer, int)) else v)) for k, v in p.items()}, **r})
    print(t, {k: p[k] for k in ["objective", "num_leaves", "min_data_in_leaf", "feature_fraction", "lambda_l2", "learning_rate"]}, "val", round(r["val_mdape"], 4), "trees", r["trees"], flush=True)
best = min(trials, key=lambda r: r["val_mdape"])
print("best by validation:", best["params"], round(best["val_mdape"], 4))
runs = [M.run(CORE, sd, best["params"]) for sd in (1, 2, 3)]; res["core_tuned"] = {k: [r[k] for r in runs] for k in runs[0]} | {"params": best["params"]}
print(f"core_tuned test {np.mean(res['core_tuned']['mdape']):.4f}  val {np.mean(res['core_tuned']['val_mdape']):.4f}", flush=True)
res["tuning_trials"] = trials
json.dump(res, open(M.OUT / "metrics_v5_tests.json", "w"), indent=1)
