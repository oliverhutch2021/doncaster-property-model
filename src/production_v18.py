"""Production model refit (v18): fixes the training filter in src/export_v7.py, which kept only sales in
outputs/train_keep_ids.csv. That list was made by src/model_v2.py from sales up to December 2024, so every sale from
January 2025 on was dropped even though the model claimed to be trained to August 2025.

Cleaning policy, now written down and applied to every sale the production model can use:
  - sales up to December 2024: the existing list (out-of-fold residual from src/model_v2.py within 0.8 log points)
  - sales from January 2025: kept unless the price is more than 0.8 log points (about 2.2x) from an out-of-sample
    estimate by the test model (trained to 2023, early-stopped on 2024), the same threshold
The production model is then trained on every kept sale before the local-correction window (the last 12 months), with
the tree count and settings of src/export_v7.py, and the training dates and counts are taken from the rows actually used.
Rewrites: outputs/dash2/model_trees.json, comps.csv (the recent-sale residuals for the local correction),
feature_importance.csv, model_meta.json (train_from, train_end, n_train), outputs/model/doncaster_lgbm_v7.txt,
outputs/train_keep_ids_v18.csv, outputs/production_v18.json"""
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import export_v7 as E

s, keep, OUT, D = E.s, E.keep, E.OUT, E.D
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42) | tuned
inkeep = s.unique_id.isin(keep)
tr23 = s[(s.sale_date <= "2023-12-31") & inkeep]; va24 = s[(s.sale_date > "2023-12-31") & (s.sale_date <= "2024-12-31") & inkeep]
mB = E.fit_es(tr23, va24, P); n_iter = mB.best_iteration
print(f"test model refitted: {n_iter} trees (export_v7 used the same settings)")

val_month = s.month.max() + pd.DateOffset(months=1); pool_start = val_month - pd.DateOffset(months=E.POOL_MONTHS)
eligible = s[s.sale_date < pool_start]
use, late = E.production_rows(s, keep, mB, n_iter, pool_start)          # the cleaning policy, shared with src/export_v7.py
bad = np.abs(late.r.values) > E.CLEAN_LOG
old = eligible[eligible.unique_id.isin(keep)]
print(f"eligible sales before {pool_start:%b %Y}: {len(eligible):,}; previously used {len(old):,} (latest {old.sale_date.max():%d %b %Y}); "
      f"now {len(use):,} (latest {use.sale_date.max():%d %b %Y}); Jan-Aug 2025: {len(late):,} sales, {int(bad.sum())} removed by the 0.8 rule")
# the fix must hold: recent eligible sales are in, and the dates come from the rows used
assert use.sale_date.max() >= pool_start - pd.DateOffset(months=1), "recent eligible sales missing from production training"
assert (late.unique_id.isin(use.unique_id)).mean() > 0.95, "most 2025 sales should be kept"

prod = lgb.train(P, lgb.Dataset(E.X(use), use.y_defl, categorical_feature=["property_type"]), n_iter)
(OUT / "model").mkdir(exist_ok=True); prod.save_model(str(OUT / "model/doncaster_lgbm_v7.txt"))
pd.Series(sorted(set(use.unique_id))).to_csv(OUT / "train_keep_ids_v18.csv", index=False, header=["unique_id"])
poolC = s[s.sale_date >= pool_start].copy(); poolC["r"] = poolC.y_defl.values - prod.predict(E.X(poolC))
trees = [E.flat(t) for t in prod.dump_model()["tree_info"]]
json.dump([{"tree": i, "nodes": json.dumps(E.compact(t), separators=(",", ":"))} for i, t in enumerate(trees)], open(D / "model_trees.json", "w"), separators=(",", ":"))

# recent sales and their residuals, for the local correction and comparables (same layout as export_v7)
win = s[(s.month >= val_month - pd.DateOffset(months=36)) & (s.month < val_month)].copy()
win["addr"] = win.address_key.str.split("|").apply(lambda a: " ".join(x for x in [a[0], a[1], a[2].title()] if x).strip())
win = win.merge(poolC[["unique_id", "r"]], on="unique_id", how="left")
E.wcsv("comps.csv", ["date", "price", "postcode", "type", "tenure", "new_build", "lat", "lon", "address", "y_defl", "floor_area", "resid"],
       [[r.sale_date.strftime("%Y-%m-%d"), int(r.price), r.postcode, r.property_type, r.tenure, int(r.new_build), round(r.lat, 5), round(r.lon, 5), r.addr,
         round(r.y_defl, 5), "" if pd.isna(r.floor_area) else round(r.floor_area, 1), "" if pd.isna(r.r) else round(r.r, 4)] for r in win.itertuples()])
imp = pd.Series(prod.feature_importance("gain"), index=prod.feature_name()); imp = (imp / imp.sum()).sort_values(ascending=False)
E.wcsv("feature_importance.csv", ["feature", "gain_share"], [[k, round(v, 5)] for k, v in imp.items()])

meta = json.load(open(D / "model_meta.json")); keys = {r["key"]: i for i, r in enumerate(meta)}
for k, v in (("train_from", use.sale_date.min().strftime("%Y-%m")), ("train_end", use.sale_date.max().strftime("%Y-%m")), ("n_train", str(len(use))),
             ("train_cleaning", "Sales to Dec 2024: out-of-fold rule (model_v2); from Jan 2025: more than 0.8 log points from the test model's estimate")):
    if k in keys: meta[keys[k]]["value"] = v
    else: meta.append({"key": k, "value": v})
json.dump(meta, open(D / "model_meta.json", "w"))
for f in ("model_meta.json", "comps.csv"):
    (OUT / "model" / f).write_bytes((D / f).read_bytes())
res = dict(n_iter=n_iter, eligible=len(eligible), used_before=len(old), used_now=len(use), latest_before=str(old.sale_date.max().date()), latest_now=str(use.sale_date.max().date()),
           late_sales=len(late), late_removed=int(bad.sum()), pool_from=pool_start.strftime("%Y-%m"), model_mb=round((D / "model_trees.json").stat().st_size / 1e6, 2),
           resid_recent_median=float(np.median(poolC.r)), resid_recent_mad=float(np.median(np.abs(poolC.r - np.median(poolC.r)))))
json.dump(res, open(OUT / "production_v18.json", "w"), indent=1); print(json.dumps(res, indent=1))
