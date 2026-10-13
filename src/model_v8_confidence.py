"""A confidence score for each estimate, and ranges that adapt to it.

Trained on out-of-sample errors from the year-by-year backtest (src/model_v8_backtest.py): a small LightGBM model
predicts the typical size of the error (median absolute log error) from what the page knows about the estimate:
the estimate itself, type, size, age, whether and when the home last sold, how many recent sales there are on the
street, in the postcode and sector, how far away the nearest sales are, the certificate's age, the plot, deprivation,
the size of the local correction and how much the nearby misses disagree.

  train   errors from 2020-2023 (each year valued by a model that never saw it)
  scale   2024 errors: 10th and 90th percentiles of error / predicted typical error, for an 80% range
  test    the dashboard model on 2025-26 (trained to 2023, early-stopped on 2024), compared with the current ranges
Output: outputs/confidence.json, outputs/dash2/conf_trees.json, outputs/dash2/confidence.csv"""
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.neighbors import BallTree
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; P_ = ROOT / "data/processed"; D = OUT / "dash2"
sys.path.insert(0, str(ROOT / "src"))
import correction as C
from export_v7 import compact, flat
CONF_F = ["pred_log", "property_type", "floor_area", "rooms", "age_year", "years_since_prev", "n_sector_type", "n_street_type", "n_postcode",
          "knn_dist", "epc_age_y", "new_build", "tenure", "plot_m2_per_home", "imd_score", "corr_abs", "local_spread"]
CP = dict(objective="quantile", alpha=0.5, learning_rate=0.05, num_leaves=15, min_data_in_leaf=300, feature_fraction=0.8,
          bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=7)
NROUND = 300
LEVELS = [(0.05, "High"), (0.075, "Good"), (0.10, "Fair"), (9.9, "Low")]      # by predicted typical error

def CX(d):
    x = pd.DataFrame({c: d[c] for c in CONF_F if c not in ("property_type", "tenure", "new_build", "corr_abs")})
    x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(float)
    x["tenure"] = (d.tenure.astype(str) == "L").astype(float)
    x["new_build"] = d.new_build.astype(float); x["corr_abs"] = np.abs(d["corr"].values)
    return x[CONF_F].astype(float)

def level(sig):
    out = np.empty(len(sig), dtype=object)
    lo = 0
    for hi, name in LEVELS: out[(sig >= lo) & (sig < hi)] = name; lo = hi
    return out

if __name__ == "__main__":
    b = pd.read_parquet(P_ / "backtest_residuals.parquet")
    tr, cal = b[b.year.between(2020, 2023)], b[b.year == 2024]
    m = lgb.train(CP, lgb.Dataset(CX(tr), np.abs(tr.resid.values)), NROUND)
    sig_cal = m.predict(CX(cal)); z = cal.resid.values / sig_cal
    q10, q90 = float(np.quantile(z, .10)), float(np.quantile(z, .90))
    print(f"2024: typical error predicted {np.median(sig_cal):.3f} vs actual {np.median(np.abs(cal.resid)):.3f}; 80% range = estimate x exp(sigma x [{q10:.2f}, {q90:.2f}])")

    # ---------- the dashboard model on 2025-26, rebuilt exactly as in src/export_v7.py (section B) ----------
    import export_v7 as E
    P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42) | json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
    s = E.s; mB = E.fit_es(E.between("2000-01-01", "2023-12-31", True), E.between("2023-12-31", "2024-12-31", True), P); n_iter = mB.best_iteration
    te = s[s.sale_date > "2024-12-31"].copy(); pool = s[s.sale_date > "2023-12-31"].copy(); pool["r"] = pool.y_defl.values - mB.predict(E.X(pool), num_iteration=n_iter)
    meta = {r["key"]: r["value"] for r in json.load(open(D / "model_meta.json"))}; ALPHA, K = float(meta["local_alpha"]), int(meta["local_k"])
    corr = ALPHA * C.knn(pool, te, K); te["pred_log"] = mB.predict(E.X(te), num_iteration=n_iter) + te.log_idx.values + corr; te["corr"] = corr
    sp = np.zeros(len(te)); tr_ = np.radians(te[["lat", "lon"]].values); pdates, prad, pr = pool.sale_date.values, np.radians(pool[["lat", "lon"]].values), pool.r.values
    for mo in sorted(te.month.unique()):
        q = (te.month == mo).values; mo = pd.Timestamp(mo)
        sel = (pdates < np.datetime64(mo - pd.Timedelta(days=60))) & (pdates >= np.datetime64(mo - pd.DateOffset(months=12)))
        _, ind = BallTree(prad[sel], metric="haversine").query(tr_[q], k=K); v = pr[sel][ind]
        sp[q] = np.median(np.abs(v - np.median(v, axis=1, keepdims=True)), axis=1)
    te["local_spread"] = sp
    price = te.price.values.astype(float); est = np.exp(te.pred_log.values); r = np.log(price) - te.pred_log.values; ape = np.abs(est - price) / price
    print(f"dashboard model on 2025-26: median error {np.median(ape):.4f} (export said 0.0804)")
    sig = m.predict(CX(te)); lev = level(sig)
    new_in = (r >= sig * q10) & (r <= sig * q90); new_w = np.exp(sig * q90) - np.exp(sig * q10)
    conf = json.loads(meta["conformal"]); bands = json.loads(meta["bands"])
    g = np.digitize(est, bands) + 5 * te.prev_defl.notna().values.astype(int)
    lo = np.array([conf[i][0] for i in g]); hi = np.array([conf[i][1] for i in g])
    old_in = (r >= lo) & (r <= hi); old_w = np.exp(hi) - np.exp(lo)
    res = dict(q10=q10, q90=q90, levels=[[h, n] for h, n in LEVELS], features=CONF_F, adopt_adaptive=True, test=dict(
        new=dict(coverage=float(new_in.mean()), width_median=float(np.median(new_w)), width_mean=float(np.mean(new_w))),
        old=dict(coverage=float(old_in.mean()), width_median=float(np.median(old_w)), width_mean=float(np.mean(old_w))),
        corr_sigma_abs_error=float(np.corrcoef(sig, np.abs(r))[0, 1])))
    by = []
    for _, name in LEVELS:
        k = lev == name
        if not k.any(): continue
        by.append(dict(level=name, n=int(k.sum()), share=float(k.mean()), mdape=float(np.median(ape[k])), within10=float(np.mean(ape[k] <= .1)),
                       within20=float(np.mean(ape[k] <= .2)), coverage_new=float(new_in[k].mean()), coverage_old=float(old_in[k].mean()),
                       coverage_used=float(new_in[k].mean()), typical_error_predicted=float(np.median(sig[k]))))
    res["by_level"] = by
    order = np.argsort(sig); curve = []
    for keep_share in (1.0, .9, .8, .7, .6, .5):
        k = order[: int(len(order) * keep_share)]; curve.append(dict(kept=keep_share, mdape=float(np.median(ape[k])), within10=float(np.mean(ape[k] <= .1))))
    res["filter_curve"] = curve
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT / "confidence.json", "w"), indent=1)
    trees = [compact(flat(t)) for t in m.dump_model()["tree_info"]]
    json.dump([{"tree": i, "nodes": json.dumps(t, separators=(",", ":"))} for i, t in enumerate(trees)], open(D / "conf_trees.json", "w"), separators=(",", ":"))
    m.save_model(str(OUT / "model/confidence_v8.txt"))
    pd.DataFrame(by).to_csv(D / "confidence.csv", index=False)
    print("conf trees", len(trees), round((D / "conf_trees.json").stat().st_size / 1e3), "KB")
