"""Version 6 tests (3 seeds, same split as v5): building footprints from OS OpenMap Local, and a monotone constraint so
more floor area never lowers the estimate (needed for a sensible what-if tool)."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; P_ = ROOT / "data/processed"
sys.path.insert(0, str(ROOT / "src")); sys.argv = sys.argv[:1]
import model_v5_tests as M
s = M.s.merge(pd.read_parquet(P_ / "uprn_buildings.parquet"), on="uprn", how="left"); assert len(s) == len(M.s)
s["storeys_est"] = s.floor_area / s.bld_m2_per_uprn
s.to_parquet(P_ / "model_frame_v6.parquet")
M.tr = s[(s.sale_date <= "2023-12-31") & s.unique_id.isin(M.keep)]; M.va = s[(s.sale_date > "2023-12-31") & (s.sale_date <= "2024-12-31") & s.unique_id.isin(M.keep)]
M.te = s[s.sale_date > "2024-12-31"]
CORE = M.V2 + M.LAYERS["plot"] + M.LAYERS["street"] + M.LAYERS["epc_x"]
BLD = ["bld_m2", "bld_homes", "bld_uprns", "bld_m2_per_home", "bld_m2_per_uprn", "garden_m2", "storeys_est"]
print("building coverage:", f"{s.bld_m2.notna().mean():.1%}")
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
mono = lambda cols: {"monotone_constraints": [1 if c == "floor_area" else 0 for c in cols], "monotone_constraints_method": "advanced"}
# LightGBM refuses monotone constraints with the L1 objective, so the monotone versions use Huber loss (robust like L1)
huber = {"objective": "huber", "alpha": 0.15}
CONFIGS = {"core": (CORE, None), "core_bld": (CORE + BLD, None), "tuned": (CORE, tuned), "tuned_bld": (CORE + BLD, tuned),
           "tuned_huber": (CORE, tuned | huber), "tuned_huber_mono": (CORE, tuned | huber | mono(CORE))}
res = json.load(open(OUT / "metrics_v6_tests.json")) if (OUT / "metrics_v6_tests.json").exists() else {}
for name, (cols, p) in CONFIGS.items():
    if name in res: continue
    runs = [M.run(cols, sd, p) for sd in (1, 2, 3)]; res[name] = {k: [r[k] for r in runs] for k in runs[0]}
    print(f"{name:16s} test {np.mean(res[name]['mdape']):.4f} {[round(x, 4) for x in res[name]['mdape']]}  val {np.mean(res[name]['val_mdape']):.4f}", flush=True)
    json.dump(res, open(OUT / "metrics_v6_tests.json", "w"), indent=1)
for a, b in [("core", "core_bld"), ("tuned", "tuned_bld"), ("tuned", "tuned_huber"), ("tuned", "tuned_huber_mono"), ("tuned_huber", "tuned_huber_mono")]:
    g = np.array(res[a]["mdape"]) - np.array(res[b]["mdape"]); print(f"{b:16s} vs {a:11s}: {g.mean()*100:+.2f} pts (sd {g.std()*100:.2f})")
json.dump(res, open(OUT / "metrics_v6_tests.json", "w"), indent=1)
