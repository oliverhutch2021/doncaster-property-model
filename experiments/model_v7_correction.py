"""Does the local correction still help the tuned full-size model, and does a smoothed version beat the k-nearest one?
3 seeds. For each seed: settings tuned on 2024 with a model trained to 2022 (as in export_v5), then tested on 2025-26
with a model trained to 2023 and early-stopped on 2024."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, sys, itertools, numpy as np, pandas as pd, lightgbm as lgb
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; P_ = ROOT / "data/processed"
sys.path.insert(0, str(ROOT / "src")); NOHIST = "--no-hist" in sys.argv; sys.argv = sys.argv[:1]
import model_v5_tests as M
from features_v7 import EPC_H
import correction as C
s = pd.read_parquet(P_ / "model_frame_v7.parquet"); keep = M.keep
COLS = M.V2 + M.LAYERS["plot"] + M.LAYERS["street"] + M.LAYERS["epc_x"] + ([] if NOHIST else EPC_H)
TAG = "_nohist" if NOHIST else ""
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
def between(a, b, cleaned=False):
    d = s[(s.sale_date > a) & (s.sale_date <= b)]; return d[d.unique_id.isin(keep)] if cleaned else d
def fit(tr, va, seed):
    P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=seed) | tuned
    dt = lgb.Dataset(M.X(tr, COLS), tr.y_defl, categorical_feature=["property_type"])
    return lgb.train(P, dt, 8000, valid_sets=[lgb.Dataset(M.X(va, COLS), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
def mdape(d, p): return float(np.median(np.abs(np.exp(p) - d.price.values) / d.price.values))
def w10(d, p): return float(np.mean(np.abs(np.exp(p) - d.price.values) / d.price.values <= .1))
SET = list(itertools.product((0.5, 1.0, 2.0), (3, 6, 12), (1.0, 0.5)))
res = {"none": [], "knn": [], "smooth": [], "knn_w10": [], "smooth_w10": [], "none_w10": [], "chosen": []}
for seed in (1, 2, 3):
    mA = fit(between("2000-01-01", "2022-12-31", True), between("2022-12-31", "2023-12-31", True), seed)
    poolA = between("2022-12-31", "2024-12-31").copy(); poolA["r"] = poolA.y_defl.values - mA.predict(M.X(poolA, COLS), num_iteration=mA.best_iteration)
    v24 = between("2023-12-31", "2024-12-31").copy(); bA = mA.predict(M.X(v24, COLS), num_iteration=mA.best_iteration) + v24.log_idx.values
    gk = {(a, k): mdape(v24, bA + a * C.knn(poolA, v24, k)) for k in (10, 20, 40, 80) for a in (0.25, 0.5, 0.75, 1.0)}
    (ak, kk), vk = min(gk.items(), key=lambda kv: kv[1])
    parts = C.smooth_parts(poolA, v24, SET)
    gs = {}
    for st, (med, neff) in parts.items():
        for lam in (0, 5, 20):
            for a in (0.5, 0.75, 1.0): gs[st + (lam, a)] = mdape(v24, bA + a * med * neff / (neff + lam))
    best_s, vs = min(gs.items(), key=lambda kv: kv[1])
    print(f"seed {seed}: 2024 none {mdape(v24, bA):.4f} | knn a={ak} k={kk} {vk:.4f} | smooth h={best_s[0]} hl={best_s[1]} tw={best_s[2]} lam={best_s[3]} a={best_s[4]} {vs:.4f}", flush=True)
    tr23, va24 = between("2000-01-01", "2023-12-31", True), between("2023-12-31", "2024-12-31", True)
    mB = fit(tr23, va24, seed); te = s[s.sale_date > "2024-12-31"].copy(); poolB = s[s.sale_date > "2023-12-31"].copy()
    poolB["r"] = poolB.y_defl.values - mB.predict(M.X(poolB, COLS), num_iteration=mB.best_iteration)
    p0 = mB.predict(M.X(te, COLS), num_iteration=mB.best_iteration) + te.log_idx.values
    pk = p0 + ak * C.knn(poolB, te, kk)
    h, hl, tw, lam, a = best_s; ps = p0 + a * C.smooth(poolB, te, h, hl, tw, lam)
    for name, p in [("none", p0), ("knn", pk), ("smooth", ps)]: res[name].append(mdape(te, p)); res[name + "_w10"].append(w10(te, p))
    res["chosen"].append(dict(seed=seed, knn=[ak, kk], smooth=list(best_s), trees=mB.best_iteration))
    print(f"seed {seed}: test none {res['none'][-1]:.4f} | knn {res['knn'][-1]:.4f} | smooth {res['smooth'][-1]:.4f}  (trees {mB.best_iteration})", flush=True)
    json.dump(res, open(OUT / f"metrics_v7_correction{TAG}.json", "w"), indent=1)
for a, b in [("none", "knn"), ("none", "smooth"), ("knn", "smooth")]:
    g = np.array(res[a]) - np.array(res[b]); print(f"{b} vs {a}: {g.mean()*100:+.3f} pts (sd {g.std()*100:.3f}) | within 10%: {np.mean(np.array(res[b + '_w10']) - np.array(res[a + '_w10']))*100:+.2f} pts")
