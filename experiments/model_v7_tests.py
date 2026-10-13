"""Version 7 tests (3 seeds, same split and tuned settings as v5): energy-certificate history, the last-sale premium,
both, and lease length when available (src/features_v7.py, src/leases.py)."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, sys, numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; P_ = ROOT / "data/processed"
sys.path.insert(0, str(ROOT / "src")); argv = sys.argv[1:]; sys.argv = sys.argv[:1]
import model_v5_tests as M
from features_v7 import EPC_H
s = pd.read_parquet(P_ / "model_frame_v7.parquet")
if (P_ / "leases_frame.parquet").exists(): s = s.merge(pd.read_parquet(P_ / "leases_frame.parquet"), on="unique_id", how="left")
M.tr = s[(s.sale_date <= "2023-12-31") & s.unique_id.isin(M.keep)]; M.va = s[(s.sale_date > "2023-12-31") & (s.sale_date <= "2024-12-31") & s.unique_id.isin(M.keep)]
M.te = s[s.sale_date > "2024-12-31"]
print("test coverage:", {c: f"{M.te[c].notna().mean():.0%}" for c in EPC_H + ["prev_resid"] + (["lease_left_y"] if "lease_left_y" in s else [])})
CORE = M.V2 + M.LAYERS["plot"] + M.LAYERS["street"] + M.LAYERS["epc_x"]
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
LEASE = ["lease_left_y", "lease_term_y"]
CONFIGS = {"tuned": CORE, "tuned_hist": CORE + EPC_H, "tuned_prem": CORE + ["prev_resid"], "tuned_both": CORE + EPC_H + ["prev_resid"]}
if "lease_left_y" in s: CONFIGS |= {"tuned_lease": CORE + LEASE, "tuned_all": CORE + EPC_H + ["prev_resid"] + LEASE}
res = json.load(open(OUT / "metrics_v7_tests.json")) if (OUT / "metrics_v7_tests.json").exists() else {}
for name in (argv or CONFIGS):
    if name in res: continue
    runs = [M.run(CONFIGS[name], sd, tuned) for sd in (1, 2, 3)]; res[name] = {k: [r[k] for r in runs] for k in runs[0]}
    print(f"{name:12s} test {np.mean(res[name]['mdape']):.4f} {[round(x, 4) for x in res[name]['mdape']]}  val {np.mean(res[name]['val_mdape']):.4f}  w10 {np.mean(res[name]['within10']):.3f}  trees {res[name]['trees']}", flush=True)
    json.dump(res, open(OUT / "metrics_v7_tests.json", "w"), indent=1)
for k in res:
    if k == "tuned": continue
    g = np.array(res["tuned"]["mdape"]) - np.array(res[k]["mdape"]); gv = np.array(res["tuned"]["val_mdape"]) - np.array(res[k]["val_mdape"])
    print(f"{k:12s} vs tuned: test {g.mean()*100:+.3f} pts (sd {g.std()*100:.3f})  | 2024 validation {gv.mean()*100:+.3f} pts (sd {gv.std()*100:.3f})")
