"""How the model compares with the simple methods people and websites use, on the same 5,995 test sales (Jan 2025 - Aug 2026).

Every method only sees sales completed at least two calendar months before the sale month, which is roughly when they show
up in Land Registry's published data (the UK House Price Index has a similar lag). The model is scored twice: as reported
(local price features use every earlier sale) and in this 'real-time' setting, recomputing its local features with the
same two-month cut-off.

  uk_hpi        last sale x ONS/HM Land Registry UK HPI for Doncaster (what online 'what is my house worth now' calculators do)
  uk_hpi_type   the same with the UK HPI for that property type (detached, semi, terraced, flat)
  own_index     last sale x this project's quality-adjusted Doncaster index
  sector_median median index-adjusted price of the same type in the postcode sector, last 12 months
  sector_ppsqm  median index-adjusted price per m2 of the same type in the sector, last 12 months, x EPC floor area
  nearest_10    median index-adjusted price per m2 of the 10 nearest same-type sales, last 12 months, x EPC floor area
  hedonic       a fair linear baseline: ridge regression of log price on the model's own 62 features (missing values
                filled with the training median plus a missing flag, logs of skewed counts and sizes, size by type, and a
                fixed effect for each postcode sector), trained and tested exactly like the model, with the same local
                correction fitted on its own errors
Output: outputs/compare_methods.json, outputs/dash2/method_compare.csv (written here since the fourth review; it used to
be written by src/export_v8.py, which also showed the version-1 ridge model on its smaller feature set)"""
import json, pathlib, sys, numpy as np, pandas as pd
from sklearn.neighbors import BallTree
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from export_v7 import s, X, met, fit_es, correction, between, ROOT, OUT, D

R = 6371.0
P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42) | json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
_sum = json.load(open(OUT / "export_v7_summary.json")); ALPHA, K = _sum["alpha"], _sum["k"]        # the dashboard model (src/export_v7.py)
te = s[s.sale_date > "2024-12-31"].copy().reset_index(drop=True)
te["cutoff"] = te.month - pd.DateOffset(months=2)
months = sorted(te.month.unique())

# ---------- model as reported ----------
tr23, va24 = between("2000-01-01", "2023-12-31", True), between("2023-12-31", "2024-12-31", True)
mB = fit_es(tr23, va24, P); n_iter = mB.best_iteration
poolB = s[s.sale_date > "2023-12-31"].copy(); poolB["r"] = poolB.y_defl.values - mB.predict(X(poolB), num_iteration=n_iter)
corr = correction(poolB, te, K)
pred_model = mB.predict(X(te), num_iteration=n_iter) + te.log_idx.values + ALPHA * corr

# ---------- model, real-time: local features recomputed from sales at least 2 months old ----------
rt = te.copy(); rad_all = np.radians(s[["lat", "lon"]].values); rad_te = np.radians(te[["lat", "lon"]].values)
for m in months:
    m = pd.Timestamp(m); q = (te.month == m).values; cut = m - pd.DateOffset(months=2); sub = te[q]
    win36 = s[(s.sale_date >= cut - pd.Timedelta(days=1095)) & (s.sale_date < cut)]
    g = win36.groupby(["sector", "property_type"]).y_defl.agg(["median", "count"]).reindex(pd.MultiIndex.from_frame(sub[["sector", "property_type"]]))
    rt.loc[q, "lvl_sector_type"] = np.where(g["count"].values >= 5, g["median"].values, np.nan); rt.loc[q, "n_sector_type"] = g["count"].fillna(0).values
    g = win36.groupby("lsoa21").y_defl.agg(["median", "count"]).reindex(sub.lsoa21)
    rt.loc[q, "lvl_lsoa"] = np.where(g["count"].values >= 5, g["median"].values, np.nan)
    pool = ((s.month >= m - pd.DateOffset(months=36)) & (s.sale_date < cut)).values
    for t in "DSTF":
        qt, pt = q & (te.property_type == t).values, pool & (s.property_type == t).values
        if qt.sum() == 0 or pt.sum() < 3: continue
        dist, ind = BallTree(rad_all[pt], metric="haversine").query(rad_te[qt], k=min(10, pt.sum()))
        rt.loc[qt, "knn_lvl"] = np.median(s.y_defl.values[pt][ind], axis=1); rt.loc[qt, "knn_dist"] = dist.mean(axis=1) * R
    pa = pool & s.floor_area.notna().values
    _, ind = BallTree(rad_all[pa], metric="haversine").query(rad_te[q], k=15); rt.loc[q, "knn_ppsqm"] = np.median(s.ppsqm.values[pa][ind], axis=1)
    pw = s[(s.month >= m - pd.DateOffset(months=60)) & (s.sale_date < cut)]
    a = pw.groupby(["street_key", "property_type"]).y_defl.agg(["median", "count"]).reindex(pd.MultiIndex.from_frame(sub[["street_key", "property_type"]]))
    b = pw.groupby("postcode").y_defl.agg(["median", "count"]).reindex(sub.postcode)
    rt.loc[q, "lvl_street_type"] = np.where(a["count"].values >= 2, a["median"].values, np.nan); rt.loc[q, "n_street_type"] = a["count"].fillna(0).values
    rt.loc[q, "lvl_postcode"] = np.where(b["count"].values >= 2, b["median"].values, np.nan); rt.loc[q, "n_postcode"] = b["count"].fillna(0).values
late_prev = (rt.prev_date >= rt.cutoff).values                       # last sale too recent to be published yet
rt.loc[late_prev, ["prev_defl", "years_since_prev", "prev_nb"]] = np.nan
pred_rt = mB.predict(X(rt), num_iteration=n_iter) + te.log_idx.values + ALPHA * corr
# ---------- hedonic regression on the same features (fair linear baseline) ----------
from sklearn.linear_model import Ridge
LOGS = ["floor_area", "plot_m2", "plot_m2_per_home", "knn_dist", "n_sector_type", "n_street_type", "n_postcode", "heated_rooms", "loft_mm", "epc_n", "rooms"]
sectors = sorted(tr23.sector.unique())
def hed_raw(d, med=None):
    x = X(d).copy()
    for c in LOGS: x[c] = np.log1p(x[c].clip(lower=0))
    med = x.median() if med is None else med
    cols = {}
    for c in x.columns:
        if c == "property_type": continue
        cols[c] = x[c].fillna(med[c]); cols[c + "_na"] = x[c].isna().astype(float)
    for t in range(4): cols[f"type{t}"] = (x.property_type == t).astype(float); cols[f"area_x_type{t}"] = cols["floor_area"] * cols[f"type{t}"]
    cols["age_sq"] = (cols["age_year"] - 1950) ** 2 / 1000
    sec = pd.get_dummies(pd.Categorical(d.sector, categories=sectors), prefix="sec", dtype=float); sec.index = d.index
    return pd.concat([pd.DataFrame(cols, index=d.index), sec], axis=1), med
Htr, hmed = hed_raw(tr23); hcols = Htr.columns[Htr.std() > 0]; mu, sd = Htr[hcols].mean(), Htr[hcols].std()
hz = lambda d: ((hed_raw(d, hmed)[0].reindex(columns=hcols, fill_value=0.0) - mu) / sd).values
Ztr, Zva = hz(tr23), hz(va24)
alphas = {a: float(np.median(np.abs(Ridge(alpha=a).fit(Ztr, tr23.y_defl.values).predict(Zva) - va24.y_defl.values))) for a in (1, 10, 100, 1000, 10000)}
h_alpha = min(alphas, key=alphas.get); hed = Ridge(alpha=h_alpha).fit(Ztr, tr23.y_defl.values)
poolH = s[s.sale_date > "2023-12-31"].copy(); poolH["r"] = poolH.y_defl.values - hed.predict(hz(poolH))
corrH = correction(poolH, te, K)
pred_hed = hed.predict(hz(te)) + te.log_idx.values + ALPHA * corrH
pred_hed_rt = hed.predict(hz(rt)) + te.log_idx.values + ALPHA * corrH
print(f"hedonic: {len(hcols)} columns, alpha {h_alpha} (validation median abs error by alpha {alphas})")
changed = {c: float(np.mean(~np.isclose(te[c].fillna(-99).values, rt[c].fillna(-99).values))) for c in
           ["lvl_sector_type", "lvl_lsoa", "knn_lvl", "knn_ppsqm", "lvl_street_type", "lvl_postcode", "prev_defl"]}

# ---------- simple methods ----------
u = pd.read_csv(ROOT / "data/raw/ukhpi/UK-HPI-full-file-2026-07.csv"); u = u[u.RegionName == "Doncaster"].copy()
u["month"] = pd.to_datetime(u.Date, dayfirst=True); u = u.set_index("month").sort_index()
col = {"D": "DetachedIndex", "S": "SemiDetachedIndex", "T": "TerracedIndex", "F": "FlatIndex"}
pm = te.prev_date.values.astype("datetime64[M]"); hp = te.prev_price.notna().values & ~late_prev
def hpi_calc(series_for_row):
    out = np.full(len(te), np.nan)
    for i in np.where(hp)[0]:
        ser = series_for_row(i); a, b = ser.get(pd.Timestamp(pm[i])), ser.get(te.cutoff[i])
        if pd.notna(a) and pd.notna(b): out[i] = np.log(te.prev_price[i] * b / a)
    return out
pred = {}
pred["uk_hpi"] = hpi_calc(lambda i: u["Index"])
pred["uk_hpi_type"] = hpi_calc(lambda i: u[col[te.property_type[i]]])
uk_same = np.full(len(te), np.nan)                                     # generous check: the index for the sale month itself (not yet published then)
for i in np.where(hp)[0]:
    a, b = u["Index"].get(pd.Timestamp(pm[i])), u["Index"].get(min(te.month[i], u.index.max()))
    if pd.notna(a) and pd.notna(b): uk_same[i] = np.log(te.prev_price[i] * b / a)
pred["own_index"] = np.where(hp, te.prev_defl.values + te.log_idx.values, np.nan)
sm, sp, nn = (np.full(len(te), np.nan) for _ in range(3))
lfa = np.log(te.floor_area.values)
for m in months:
    m = pd.Timestamp(m); q = (te.month == m).values; cut = m - pd.DateOffset(months=2); sub = te[q]
    w12 = s[(s.sale_date >= cut - pd.DateOffset(months=12)) & (s.sale_date < cut)]
    for lvl, dest, need in [(["sector", "property_type"], sm, "y_defl"), (["district", "property_type"], None, "y_defl")]:
        g = w12.groupby(lvl)[need].agg(["median", "count"]).reindex(pd.MultiIndex.from_frame(sub[lvl]))
        v = np.where(g["count"].values >= 5, g["median"].values, np.nan)
        if dest is not None: sm[q] = v
        else: sm[q] = np.where(np.isnan(sm[q]), v, sm[q])            # fall back to the district when the sector is thin
    g = w12.dropna(subset=["ppsqm"]).groupby(["sector", "property_type"]).ppsqm.agg(["median", "count"]).reindex(pd.MultiIndex.from_frame(sub[["sector", "property_type"]]))
    sp[q] = np.where(g["count"].values >= 5, g["median"].values, np.nan) + lfa[q]
    poolw = w12.dropna(subset=["ppsqm"]); prad = np.radians(poolw[["lat", "lon"]].values)
    for t in "DSTF":
        qt, pt = q & (te.property_type == t).values, (poolw.property_type == t).values
        if qt.sum() == 0 or pt.sum() < 10: continue
        _, ind = BallTree(prad[pt], metric="haversine").query(rad_te[qt], k=10)
        nn[qt] = np.median(poolw.ppsqm.values[pt][ind], axis=1) + lfa[qt]
pred["sector_median"] = sm + te.log_idx.values
pred["sector_ppsqm"] = sp + te.log_idx.values
pred["nearest_10"] = nn + te.log_idx.values
pred["model_reported"] = pred_model
pred["model_realtime"] = pred_rt
pred["hedonic"] = pred_hed_rt
pred["hedonic_reported"] = pred_hed

# ---------- score: every method on the sales it can value, and head-to-head with the model on the same sales ----------
def score(mask, p):
    d = te[mask]; r = met(d, p[mask]); r["coverage"] = float(mask.mean()); r["mean_bias_pct"] = float(np.median(np.exp(p[mask]) / d.price.values - 1) * 100); return r
res = {}
for k, p in pred.items():
    ok = np.isfinite(p); res[k] = score(ok, p)
    res[k]["model_realtime_same_sales"] = score(ok, pred_rt)["mdape"]
res["uk_hpi_sale_month_index"] = score(np.isfinite(uk_same), uk_same)
yrs = te.years_since_prev.values; bands = [(0, 5, "under 5 years"), (5, 10, "5-10 years"), (10, 40, "10+ years")]
res["by_years_since_last_sale"] = {lab: {k: score(np.isfinite(pred["uk_hpi"]) & (yrs >= a) & (yrs < b), pred[k])["mdape"] for k in ("uk_hpi", "own_index", "model_realtime")}
                                   | {"n": int((np.isfinite(pred["uk_hpi"]) & (yrs >= a) & (yrs < b)).sum())} for a, b, lab in bands}
pd.DataFrame({"unique_id": te.unique_id, "price": te.price, **{k: np.exp(v) for k, v in pred.items()}}).to_csv(OUT / "compare_methods_predictions.csv", index=False)
res["prior_sale_subset_n"] = int(hp.sum())
res["realtime_feature_change_share"] = changed; res["late_prev_n"] = int(late_prev.sum())
mv1 = json.load(open(OUT / "metrics.json")); res["ridge_v1"] = mv1["ridge"]["test_2025_26"]       # kept for the record; no longer charted
res["hedonic_alpha"] = h_alpha; res["hedonic_columns"] = int(len(hcols))
json.dump(res, open(OUT / "compare_methods.json", "w"), indent=1, default=float)
LAB = {"model_realtime": "This model", "hedonic": "Hedonic regression, same features", "uk_hpi": "Last sale × UK HPI", "uk_hpi_type": "Last sale × UK HPI by type",
       "nearest_10": "£/m² of 10 nearest sales", "sector_ppsqm": "£/m² in the sector", "sector_median": "Sector median price"}
rows = [dict(method=k, label=v, kind="model" if k == "model_realtime" else "simple", coverage=round(res[k]["coverage"], 4), mdape=round(res[k]["mdape"], 5),
             within10=round(res[k]["within10"], 4), model_same_sales=round(res[k].get("model_realtime_same_sales", res[k]["mdape"]), 5)) for k, v in LAB.items()]
pd.DataFrame(rows).to_csv(D / "method_compare.csv", index=False); print("method_compare:", [(r["method"], r["mdape"]) for r in rows])
for k, v in res.items():
    if isinstance(v, dict) and "coverage" in v:
        print(f"{k:16s} n={v['n']:5d} cover={v['coverage']:.0%}  MdAPE={v['mdape']:.2%}  w10={v['within10']:.0%}  w20={v['within20']:.0%}  "
              f"median bias={v['mean_bias_pct']:+.1f}%  | model real-time on same sales {v.get('model_realtime_same_sales', float('nan')):.2%}")
print("UK HPI with the sale-month index:", round(res["uk_hpi_sale_month_index"]["mdape"], 4)); print(json.dumps(res["by_years_since_last_sale"], indent=0))
print("share of test sales whose feature changed under the 2-month cut-off:", {k: round(v, 3) for k, v in changed.items()}, "| last sale too recent:", int(late_prev.sum()))
