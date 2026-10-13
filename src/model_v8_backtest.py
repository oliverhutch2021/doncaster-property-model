"""Year-by-year backtest, 2020 to 2026, of the dashboard model (v7 features and settings).

For each year Y: train on 2015 to Y-2 (cleaned), early-stop on Y-1, value every sale in Y. As in the main test:
  - the price index for each month of Y uses only sales at least two months older (fitted again for every month),
    chained to an index fitted on sales up to the end of Y-1; training prices and last-sale prices are deflated
    with that same index
  - the local correction uses the model's misses on sales from Y-1 and Y that are at least 60 days old
    (production settings: half of the median miss on the 40 nearest)
Local price features (sector, street, nearest sales) were built with the final index, so they carry small index
revisions; everything else is as of the valuation date.
Also saves every out-of-sample error with its inputs, for the confidence model (src/model_v8_confidence.py).
Output: outputs/backtest.json, data/processed/backtest_residuals.parquet"""
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; P_ = ROOT / "data/processed"
sys.path.insert(0, str(ROOT / "src"))
from price_index import fit_index
import correction as C
from features_v7 import EPC_H

s = pd.read_parquet(P_ / "model_frame_v7.parquet").sort_values(["sale_date", "unique_id"]).reset_index(drop=True)
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
allsales = pd.read_parquet(P_ / "sales_epc.parquet"); allsales["sale_date"] = pd.to_datetime(allsales.sale_date)
allsales["month"] = allsales.sale_date.values.astype("datetime64[M]")
meta = {r["key"]: r["value"] for r in json.load(open(OUT / "dash2/model_meta.json"))}
FULL = json.loads(meta["features"]); ALPHA, K = float(meta["local_alpha"]), int(meta["local_k"])
P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42) | json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]

def X(d):
    x = d[FULL].copy(); x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int); return x.astype(float)

def index_for(Y):
    """Index known at valuation time for every month of Y, chained to an index fitted on sales to the end of Y-1."""
    end = pd.Timestamp(f"{Y - 1}-12-01"); hist = fit_index(allsales[allsales.sale_date <= f"{Y - 1}-12-31"]); rt = {}
    for m in pd.date_range(f"{Y}-01-01", f"{Y}-12-01", freq="MS"):
        if m > s.month.max(): break
        ix = fit_index(allsales[allsales.month <= m - pd.DateOffset(months=2)])
        common = min(ix.index.max(), end); rt[m] = ix.iloc[-1] / ix.loc[common] * hist.loc[common]
    return pd.concat([hist, pd.Series(rt)]).sort_index()

def ratio_study(price, est):
    r = est / price; med = np.median(r)
    cod = 100 * np.mean(np.abs(r - med)) / med; prd = np.mean(r) / (est.sum() / price.sum())
    prb = np.polyfit(np.log2(0.5 * price + 0.5 * est / med), (r - med) / med, 1)[0]
    return dict(cod=float(cod), prd=float(prd), prb=float(prb))

if __name__ == "__main__":
    rows = json.load(open(OUT / "backtest.json")) if (OUT / "backtest.json").exists() else []
    done = {r["year"] for r in rows}; (P_ / "backtest").mkdir(exist_ok=True)
    for Y in range(2020, 2027):
        if Y in done and (P_ / f"backtest/resid_{Y}.parquet").exists(): continue
        rows = [r for r in rows if r["year"] != Y]
        idx = index_for(Y); li = np.log(s.month.map(idx).values.astype(float))
        d = s.copy(); d["log_idx"] = li; d["y_defl"] = d.y - li
        pm = d.prev_date.values.astype("datetime64[M]")
        d["prev_defl"] = np.log(d.prev_price) - np.log(pd.Series(pm).map(idx).values.astype(float))
        # the clean-up list covers 2015-2024; later sales are used as they are
        cleaned = d.unique_id.isin(keep) | (d.sale_date.dt.year >= 2025)
        tr = d[(d.sale_date <= f"{Y - 2}-12-31") & cleaned]; va = d[(d.sale_date.dt.year == Y - 1) & cleaned]
        te = d[d.sale_date.dt.year == Y].copy()
        dt = lgb.Dataset(X(tr), tr.y_defl, categorical_feature=["property_type"])
        m = lgb.train(P, dt, 8000, valid_sets=[lgb.Dataset(X(va), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
        pool = d[(d.sale_date.dt.year >= Y - 1) & (d.sale_date.dt.year <= Y)].copy(); pool["r"] = pool.y_defl.values - m.predict(X(pool), num_iteration=m.best_iteration)
        p0 = m.predict(X(te), num_iteration=m.best_iteration) + te.log_idx.values
        corr = C.knn(pool, te, K); p = p0 + ALPHA * corr
        # spread of the nearby misses, an input to the confidence model
        sp = np.zeros(len(te)); tr_ = np.radians(te[["lat", "lon"]].values); pdates, prad, pr = pool.sale_date.values, np.radians(pool[["lat", "lon"]].values), pool.r.values
        from sklearn.neighbors import BallTree
        for mo in sorted(te.month.unique()):
            q = (te.month == mo).values; mo = pd.Timestamp(mo)
            sel = (pdates < np.datetime64(mo - pd.Timedelta(days=60))) & (pdates >= np.datetime64(mo - pd.DateOffset(months=12)))
            if sel.sum() < K: continue
            _, ind = BallTree(prad[sel], metric="haversine").query(tr_[q], k=K); v = pr[sel][ind]
            sp[q] = np.median(np.abs(v - np.median(v, axis=1, keepdims=True)), axis=1)
        price = te.price.values.astype(float); est = np.exp(p); ape = np.abs(est - price) / price; ape0 = np.abs(np.exp(p0) - price) / price
        rr = dict(year=Y, n=int(len(te)), trained_to=f"{Y - 2}", trees=int(m.best_iteration), mdape=float(np.median(ape)), within10=float(np.mean(ape <= .1)),
                  within20=float(np.mean(ape <= .2)), mdape_no_correction=float(np.median(ape0)), median_bias=float(np.median(est / price) - 1), **ratio_study(price, est))
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in rr.items()}, flush=True)
        r = te[["unique_id", "sale_date", "price", "property_type"] + [c for c in FULL if c not in ("property_type",)]].copy()
        r["year"] = Y; r["pred_log"] = p; r["resid"] = np.log(price) - p; r["corr"] = ALPHA * corr; r["local_spread"] = sp
        r.to_parquet(P_ / f"backtest/resid_{Y}.parquet"); rr["partial"] = int(te.month.max().month < 12)
        rows = sorted(rows + [rr], key=lambda x: x["year"]); json.dump(rows, open(OUT / "backtest.json", "w"), indent=1)
    pd.concat([pd.read_parquet(P_ / f"backtest/resid_{Y}.parquet") for Y in range(2020, 2027)]).to_parquet(P_ / "backtest_residuals.parquet")
    print("saved", len(rows), "years")
