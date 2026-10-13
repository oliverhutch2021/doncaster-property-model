"""Version 8 tests, 3 seeds, same protocol as src/model_v7_correction.py (local correction tuned on 2024 with a model
trained to 2022; tested on 2025-26 with a model trained to 2023, early-stopped on 2024).

Time inside the model (Zillow-style):
  time_hybrid  the v7 model plus time features: months since Jan 2015 and the month of the year (as a circle, so
               December sits next to January); prices still deflated by the index
  time_only    no index at all: the model predicts log price from the same features plus time; the last sale enters
               as its log price and its month instead of index-adjusted
Fixing regressivity (on the v7 model's estimates, both tuned on 2024 only):
  calib    shift by the 2024 median miss for estimates of that size (10 bands of the estimate)
  stretch  widen estimates around the 2024 median by (1 + b), b chosen to make 2024's price-related bias (PRB) zero
Scored with median error, within 10%, and the assessors' COD, PRD and PRB.
Output: outputs/metrics_v8_tests.json"""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; P_ = ROOT / "data/processed"
sys.path.insert(0, str(ROOT / "src")); sys.argv = sys.argv[:1]
import correction as C
from model_v8_backtest import ratio_study
s = pd.read_parquet(P_ / "model_frame_v7.parquet").sort_values(["sale_date", "unique_id"]).reset_index(drop=True)
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
meta = {r["key"]: r["value"] for r in json.load(open(OUT / "dash2/model_meta.json"))}; FULL = json.loads(meta["features"])
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
mo = s.month.dt.year * 12 + s.month.dt.month - (2015 * 12 + 1)
s["t_month"] = mo.astype(float); s["season_sin"] = np.sin(2 * np.pi * (s.month.dt.month - 1) / 12); s["season_cos"] = np.cos(2 * np.pi * (s.month.dt.month - 1) / 12)
pd_ = s.prev_date.dt
s["prev_t"] = (pd_.year * 12 + pd_.month - (2015 * 12 + 1)).astype(float); s["prev_logp"] = np.log(s.prev_price)
T = ["t_month", "season_sin", "season_cos"]
VARIANTS = {"base": (FULL, "y_defl", True), "time_hybrid": (FULL + T, "y_defl", True),
            "time_only": ([c for c in FULL if c != "prev_defl"] + ["prev_logp", "prev_t"] + T, "y", False)}
def X(d, cols):
    x = d[cols].copy(); x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int); return x.astype(float)
def between(a, b, cleaned=False):
    d = s[(s.sale_date > a) & (s.sale_date <= b)]; return d[d.unique_id.isin(keep)] if cleaned else d
def fit(tr, va, cols, target, seed):
    P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=seed) | tuned
    dt = lgb.Dataset(X(tr, cols), tr[target], categorical_feature=["property_type"])
    return lgb.train(P, dt, 8000, valid_sets=[lgb.Dataset(X(va, cols), va[target], reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
def score(d, p):
    price = d.price.values.astype(float); est = np.exp(p); ape = np.abs(est - price) / price
    return dict(mdape=float(np.median(ape)), within10=float(np.mean(ape <= .1)), **ratio_study(price, est))

if __name__ == "__main__":
    res = json.load(open(OUT / "metrics_v8_tests.json")) if (OUT / "metrics_v8_tests.json").exists() else {}
    for seed in (1, 2, 3):
        for name, (cols, target, use_idx) in VARIANTS.items():
            key = f"{name}|{seed}"
            if key in res: continue
            off = (lambda d: d.log_idx.values) if use_idx else (lambda d: np.zeros(len(d)))
            mA = fit(between("2000-01-01", "2022-12-31", True), between("2022-12-31", "2023-12-31", True), cols, target, seed)
            poolA = between("2022-12-31", "2024-12-31").copy(); poolA["r"] = poolA[target].values - mA.predict(X(poolA, cols), num_iteration=mA.best_iteration)
            v24 = between("2023-12-31", "2024-12-31").copy(); bA = mA.predict(X(v24, cols), num_iteration=mA.best_iteration) + off(v24)
            md = lambda d, p: float(np.median(np.abs(np.exp(p) - d.price.values) / d.price.values))
            gk = {(a, k): md(v24, bA + a * C.knn(poolA, v24, k)) for k in (10, 20, 40, 80) for a in (0.25, 0.5, 0.75, 1.0)}
            (ak, kk), _ = min(gk.items(), key=lambda kv: kv[1]); pA = bA + ak * C.knn(poolA, v24, kk)
            mB = fit(between("2000-01-01", "2023-12-31", True), between("2023-12-31", "2024-12-31", True), cols, target, seed)
            te = s[s.sale_date > "2024-12-31"].copy(); poolB = s[s.sale_date > "2023-12-31"].copy()
            poolB["r"] = poolB[target].values - mB.predict(X(poolB, cols), num_iteration=mB.best_iteration)
            p0 = mB.predict(X(te, cols), num_iteration=mB.best_iteration) + off(te); pk = p0 + ak * C.knn(poolB, te, kk)
            out = dict(none=score(te, p0), knn=score(te, pk), knn_settings=[ak, kk], trees=int(mB.best_iteration))
            if name == "base":
                rA = np.log(v24.price.values) - pA
                edges = np.quantile(pA, np.linspace(0, 1, 11)); cen = [(edges[i] + edges[i + 1]) / 2 for i in range(10)]
                med = [float(np.median(rA[(pA >= edges[i]) & (pA <= edges[i + 1])])) for i in range(10)]
                out["calib"] = score(te, pk + np.interp(pk, cen, med)); out["calib_curve"] = [cen, med]
                cA = float(np.median(pA)); price24 = v24.price.values.astype(float)
                bgrid = np.round(np.arange(0, 0.201, 0.01), 2)
                prb24 = {bb: ratio_study(price24, np.exp(cA + (1 + bb) * (pA - cA)))["prb"] for bb in bgrid}
                bb = min(prb24, key=lambda k: abs(prb24[k])); out["stretch"] = score(te, cA + (1 + bb) * (pk - cA)); out["stretch_b"] = float(bb)
                out["prb_2024_before"] = prb24[0.0]
            res[key] = out
            print(key, {k: ({kk: round(vv, 4) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in out.items() if k != "calib_curve"}, flush=True)
            json.dump(res, open(OUT / "metrics_v8_tests.json", "w"), indent=1)
    def col(name, part, metric): return np.array([res[f"{name}|{sd}"][part][metric] for sd in (1, 2, 3)])
    for name in ("time_hybrid", "time_only"):
        g = col("base", "knn", "mdape") - col(name, "knn", "mdape")
        print(f"{name:12s} vs base (with correction): {g.mean() * 100:+.3f} pts (sd {g.std() * 100:.3f}); without correction {np.mean(col(name, 'none', 'mdape')) * 100:.2f}%")
    for fix in ("calib", "stretch"):
        g = col("base", "knn", "mdape") - col("base", fix, "mdape")
        print(f"{fix:8s}: median error {g.mean() * 100:+.3f} pts (sd {g.std() * 100:.3f}) | PRD {np.mean(col('base', 'knn', 'prd')):.3f} -> {np.mean(col('base', fix, 'prd')):.3f}"
              f" | PRB {np.mean(col('base', 'knn', 'prb')):.3f} -> {np.mean(col('base', fix, 'prb')):.3f} | COD {np.mean(col('base', 'knn', 'cod')):.1f} -> {np.mean(col('base', fix, 'cod')):.1f}")
