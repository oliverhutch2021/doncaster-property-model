"""Build everything the dashboard needs:
 - a compact LightGBM model (fewer, shallower trees) that runs in the browser, validated on the same 2025-26 test set
 - lookup tables to build the model's features from a postcode in JavaScript
 - comparables, market series, sector stats, rents, condition calibration, metrics."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, numpy as np, pandas as pd, lightgbm as lgb, duckdb
from features import matrix
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"
df = pd.read_parquet(ROOT / "data/processed/model_frame.parquet")
idx = pd.read_csv(OUT / "price_index.csv", index_col=0, parse_dates=True)["index"]
P = dict(objective="regression_l1", learning_rate=0.08, num_leaves=31, min_data_in_leaf=40, feature_fraction=0.8,
         bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=42)
TRAIN_END, VAL_END = pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")
tr, va, te = df[df.sale_date <= TRAIN_END], df[(df.sale_date > TRAIN_END) & (df.sale_date <= VAL_END)], df[df.sale_date > VAL_END]
d_tr = lgb.Dataset(matrix(tr), tr.y_defl, categorical_feature=["property_type"])
m = lgb.train(P, d_tr, 3000, valid_sets=[lgb.Dataset(matrix(va), va.y_defl, reference=d_tr)], callbacks=[lgb.early_stopping(100, verbose=False)])
n_iter = m.best_iteration
def score(d, mm):
    p = np.exp(mm.predict(matrix(d), num_iteration=n_iter) + d.log_idx.values); ape = np.abs(p - d.price) / d.price
    return p, dict(n=int(len(d)), mae=float(np.mean(np.abs(p - d.price))), mdape=float(ape.median()), within10=float((ape <= .1).mean()), within20=float((ape <= .2).mean()))
_, val_m = score(va, m); tp, test_m = score(te, m)
bands = [0, 100_000, 150_000, 200_000, 300_000, 10**9]
vp, _ = score(va, m); r = np.log(va.price.values) - np.log(vp); vb = np.digitize(vp, bands[1:-1])
conf = [[float(np.quantile(r[vb == b], .10)), float(np.quantile(r[vb == b], .90))] for b in range(5)]
tb = np.digitize(tp, bands[1:-1]); rt = np.log(te.price.values) - np.log(tp)
cover = float(np.mean([(conf[b][0] <= x <= conf[b][1]) for b, x in zip(tb, rt)]))
print("compact model iters", n_iter, "val", val_m, "test", test_m, "coverage", cover)

# production model: refit on ALL 2015-2026 sales with the same number of trees
prod = lgb.train(P, lgb.Dataset(matrix(df), df.y_defl, categorical_feature=["property_type"]), n_iter)
dump = prod.dump_model()
feat_names = dump["feature_names"]
def flat(tree):
    nodes = []
    def walk(n):
        i = len(nodes); nodes.append(None)
        if "leaf_value" in n:
            nodes[i] = [-1, 0, 0, 0, round(n["leaf_value"], 6), 0]; return i
        f = n["split_feature"]
        if n["decision_type"] == "==":     # categorical split: threshold like '0||2'
            cats = [int(c) for c in str(n["threshold"]).split("||")]
            thr = sum(1 << c for c in cats); kind = 1
        else:
            thr = round(n["threshold"], 6); kind = 0
        l = walk(n["left_child"]); rr = walk(n["right_child"])
        nodes[i] = [f, thr, l, rr, 1 if n.get("default_left", True) else 0, kind]; return i
    walk(tree["tree_structure"]); return nodes
trees = [flat(t) for t in dump["tree_info"]]
# sanity check: JS-style evaluation in Python must match LightGBM
def ev(trees, x):
    s = 0.0
    for nodes in trees:
        i = 0
        while nodes[i][0] != -1:
            f, thr, l, r_, dl, kind = nodes[i]; v = x[f]
            if v is None or (isinstance(v, float) and np.isnan(v)): go_left = dl == 1
            elif kind == 1: go_left = bool((thr >> int(v)) & 1)
            else: go_left = v <= thr
            i = l if go_left else r_
        s += nodes[i][4]
    return s
Xs = matrix(df.sample(200, random_state=3))
diff = max(abs(ev(trees, list(row)) - p) for row, p in zip(Xs.astype(float).values.tolist(), prod.predict(Xs)))
print("max |python-eval - lightgbm| =", diff)

# ---------- feature lookups for the browser ----------
con = duckdb.connect(str(ROOT / "data/processed/doncaster.duckdb"), read_only=True)
pcs = con.execute("""select p.postcode, p.lat, p.lon, p.lsoa21, p.ward, i.* exclude (lsoa21)
    from postcodes p left join imd i using (lsoa21) where p.lat is not null""").df()
c = con.execute("select * from centre").fetchone()
pcs["dist_centre_km"] = 2 * 6371 * np.arcsin(np.sqrt(np.sin(np.radians(pcs.lat - c[0]) / 2) ** 2 + np.cos(np.radians(c[0])) * np.cos(np.radians(pcs.lat)) * np.sin(np.radians(pcs.lon - c[1]) / 2) ** 2))
pcs["sector"] = pcs.postcode.str[:-2]
latest = df.sale_date.max(); win = df[df.sale_date > latest - pd.Timedelta(days=1095)]
lvl_st = win.groupby(["sector", "property_type"]).y_defl.agg(["median", "count"])
lvl_l = win.groupby("lsoa21").y_defl.agg(["median", "count"])
imdcols = ["imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime", "imd_barriers", "imd_living_env"]
pc_tab = {r.postcode: [round(r.lat, 5), round(r.lon, 5), round(r.dist_centre_km, 3)] + [None if pd.isna(getattr(r, k)) else round(getattr(r, k), 3) for k in imdcols]
          + [r.lsoa21, r.ward, int(r.imd_decile) if not pd.isna(r.imd_decile) else None] for r in pcs.itertuples()}
lvl_tab = {f"{s}|{t}": [round(v["median"], 4), int(v["count"])] for (s, t), v in lvl_st.iterrows()}
lsoa_tab = {k: round(v["median"], 4) for k, v in lvl_l.iterrows() if v["count"] >= 5}

# ---------- comparables (last 3 years) ----------
comps = win[["sale_date", "price", "postcode", "property_type", "tenure", "new_build", "lat", "lon", "address_key"]].copy()
comps["addr"] = comps.address_key.str.split("|").apply(lambda a: " ".join(x for x in [a[0], a[1], a[2].title()] if x).strip())
comp_rows = [[r.sale_date.strftime("%Y-%m-%d"), int(r.price), r.postcode, r.property_type, r.tenure, int(r.new_build), round(r.lat, 5), round(r.lon, 5), r.addr]
             for r in comps.itertuples()]

# ---------- market series ----------
d2 = df.assign(m=df.sale_date.dt.to_period("M").astype(str))
monthly = d2.groupby(["m", "property_type"]).price.agg(["median", "count"]).reset_index()
series = {"months": sorted(d2.m.unique().tolist()), "index": {k.strftime("%Y-%m"): round(v, 4) for k, v in idx.items() if k >= pd.Timestamp("2015-01-01")},
          "by_type": {t: {r.m: [int(r["median"]), int(r["count"])] for _, r in monthly[monthly.property_type == t].iterrows()} for t in "DSTF"}}
# sector stats: last 3 yrs vs the 3 yrs ending 5 years earlier (median, all types) + type mix
rent = pd.read_csv(ROOT / "data/raw/pipr_doncaster.csv", parse_dates=["Time period"])
lr_ = rent.iloc[-1]
rents = {"month": lr_["Time period"].strftime("%Y-%m"), "all": int(lr_["Rental price"]),
         "beds": {"1": int(lr_["Rental price one bed"]), "2": int(lr_["Rental price two bed"]), "3": int(lr_["Rental price three bed"]), "4": int(lr_["Rental price four or more bed"])},
         "type": {"D": int(lr_["Rental price detached"]), "S": int(lr_["Rental price semidetached"]), "T": int(lr_["Rental price terraced"]), "F": int(lr_["Rental price flat maisonette"])},
         "annual_change_pct": round(float(lr_["Annual change"]), 2),
         "history": [[r["Time period"].strftime("%Y-%m"), int(r["Rental price"])] for _, r in rent.iterrows()]}
old = df[(df.sale_date > latest - pd.Timedelta(days=1095 + 1826)) & (df.sale_date <= latest - pd.Timedelta(days=1826))]
sec = []
for s, g in win.groupby("sector"):
    if len(g) < 20: continue
    o = old[old.sector == s]
    by_t = {t: [int(gt.price.median()), int(len(gt))] for t, gt in g.groupby("property_type") if len(gt) >= 5}
    # growth on index-adjusted basis would hide growth; use raw medians of comparable mix: median of y_defl change + index change
    growth = float(np.exp(g.y.median() - o.y.median()) - 1) if len(o) >= 20 else None
    yields = {t: round(12 * rents["type"][t] / v[0] * 100, 2) for t, v in by_t.items()}
    sec.append(dict(sector=s, n=int(len(g)), median=int(g.price.median()), lat=round(g.lat.mean(), 4), lon=round(g.lon.mean(), 4),
                    imd=round(float(g.imd_score.mean()), 1) if g.imd_score.notna().any() else None, by_type=by_t, growth5=None if growth is None else round(growth * 100, 1),
                    yields=yields, wards=g.ward.value_counts().head(2).index.tolist()))
metrics = json.load(open(OUT / "metrics.json")); cond = json.load(open(OUT / "condition_calibration.json"))
test_sample = pd.DataFrame({"price": te.price.values, "pred": tp, "type": te.property_type.values}).sample(1500, random_state=7)
data = dict(
    meta=dict(latest_sale=latest.strftime("%Y-%m-%d"), n_sales_model=int(len(df)), centre=[round(c[0], 5), round(c[1], 5)],
              index_latest=round(float(idx.iloc[-1]), 5), index_latest_month=idx.index[-1].strftime("%Y-%m")),
    model=dict(features=feat_names, trees=trees, bands=bands[1:-1], conformal=conf),
    accuracy=dict(compact_validation_2024=val_m, compact_test_2025_26=test_m, compact_test_coverage_80=cover,
                  research=metrics, test_sample=test_sample.round(0).values.tolist()),
    postcodes=pc_tab, lvl_sector_type=lvl_tab, lvl_lsoa=lsoa_tab, comps=comp_rows, series=series, sectors=sec, rents=rents, condition=cond)
s = json.dumps(data, separators=(",", ":"), default=float)
(OUT / "dashboard_data.json").write_text(s); print("dashboard_data.json MB:", round(len(s) / 1e6, 2), "trees:", len(trees), "sectors:", len(sec), "comps:", len(comp_rows))
