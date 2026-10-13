"""Calibrate condition adjustments from repeat sales.

Idea: a home bought and resold within 3-18 months (not a new build) is usually a refurbishment flip.
Using out-of-fold model predictions (the model only knows type/location/time, not condition):
  - residual at PURCHASE  ~ how far below an 'average-condition' value a property in poor condition sells
  - residual at RESALE    ~ how far above average a freshly refurbished property sells
Long-hold pairs (5+ years) are shown as a control group: their residuals should be close to zero."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.model_selection import KFold
from features import matrix
ROOT = pathlib.Path(__file__).resolve().parents[1]
df = pd.read_parquet(ROOT / "data/processed/model_frame.parquet").reset_index(drop=True)
best_iter = lgb.Booster(model_file=str(ROOT / "outputs/gbm_trainval.txt")).current_iteration()
params = dict(objective="regression_l1", learning_rate=0.03, num_leaves=63, min_data_in_leaf=30, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=42)
oof = np.zeros(len(df)); X = matrix(df)
for tr, te in KFold(5, shuffle=True, random_state=1).split(X):
    m = lgb.train(params, lgb.Dataset(X.iloc[tr], df.y_defl.iloc[tr], categorical_feature=["property_type"]), best_iter)
    oof[te] = m.predict(X.iloc[te])
df["resid"] = df.y_defl - oof
key = df.set_index(["address_key", "sale_date"])["resid"]
pairs = df[df.prev_price.notna() & (df.prev_new_build == False)].copy()
pairs["prev_date"] = pd.to_datetime(pairs.prev_date)
pairs = pairs[pairs.prev_date >= "2015-01-01"]
pairs["prev_resid"] = [key.get((a, d), np.nan) if not isinstance(key.get((a, d), np.nan), pd.Series) else key.get((a, d)).iloc[0]
                       for a, d in zip(pairs.address_key, pairs.prev_date)]
pairs = pairs.dropna(subset=["prev_resid"])
pairs["hold_m"] = (pairs.sale_date - pairs.prev_date).dt.days / 30.44
flips = pairs[(pairs.hold_m >= 3) & (pairs.hold_m <= 18)]
control = pairs[pairs.hold_m >= 60]
q = lambda s: {"median": float(np.median(s)), "p25": float(np.quantile(s, .25)), "p75": float(np.quantile(s, .75)), "n": int(len(s))}
out = {
    "flip_purchase_resid": q(flips.prev_resid), "flip_resale_resid": q(flips.resid),
    "control_first_resid": q(control.prev_resid), "control_second_resid": q(control.resid),
    "flip_excess_uplift": q(flips.resid - flips.prev_resid),
}
pct = lambda r: round(100 * (np.exp(r) - 1), 1)
needs = out["flip_purchase_resid"]["median"]; refurb = out["flip_resale_resid"]["median"]
out["condition_adjustments_pct"] = {
    "needs_full_renovation": pct(needs), "dated": pct(needs / 2), "average": 0.0,
    "good": pct(refurb / 2), "recently_refurbished": pct(refurb)}
out["condition_ranges_pct"] = {
    "needs_full_renovation": [pct(out["flip_purchase_resid"]["p25"]), pct(out["flip_purchase_resid"]["p75"])],
    "recently_refurbished": [pct(out["flip_resale_resid"]["p25"]), pct(out["flip_resale_resid"]["p75"])]}
json.dump(out, open(ROOT / "outputs/condition_calibration.json", "w"), indent=1)
print(json.dumps(out, indent=1))
