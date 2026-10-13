"""Condition calibration, checked again (fourth review).

The published setting (src/export_v7.py, section D) takes homes resold within 3-18 months, mostly bought, refurbished and
resold, and reads the condition effect off a model's out-of-fold residuals: the median residual at purchase is "needs
full renovation", at resale "recently refurbished". Two things can bias that:
  - folds: the out-of-fold model used KFold(shuffle), so the same home's other sales could sit in the training folds
    and the model partly learns that home's price level. Here the folds are grouped by home (address).
  - the resale uplift every repeat sale shows: homes that sell again after a long hold also tend to sell above or
    below the model, for reasons that have nothing to do with a quick refurbishment (improvements over the years,
    who buys and sells). Here the same residuals for homes resold after 5 years or more are subtracted.
Run for the model without last-sale features (as published) and for the full served feature set.
Output: outputs/condition_calibration_v21.json (and outputs/dash2/condition.csv, model/condition.csv when --write; add
--from-json to write them from the last run without refitting)."""
import csv, json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.model_selection import GroupKFold, KFold
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import export_v7 as E

s, OUT, D = E.s.copy(), E.OUT, E.D
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42) | tuned
N_ITER = len(json.load(open(D / "model_trees.json")))                      # the production model's tree count
NOPREV = [c for c in E.FULL if c not in ("prev_defl", "years_since_prev", "prev_nb")]
pc = lambda v: round(100 * (np.exp(v) - 1), 2)

def oof(cols, grouped):
    out = np.zeros(len(s)); Xa = E.X(s, cols)
    folds = GroupKFold(5).split(Xa, groups=s.address_key.values) if grouped else KFold(5, shuffle=True, random_state=1).split(Xa)
    for a, b in folds:
        m = lgb.train(P, lgb.Dataset(Xa.iloc[a], s.y_defl.iloc[a], categorical_feature=["property_type"]), N_ITER); out[b] = m.predict(Xa.iloc[b])
    return s.y_defl.values - out

def calibrate(resid, purchase_had_prev=False):
    """purchase_had_prev: keep only pairs whose purchase had an earlier sale of its own, so that with the full model the
    purchase leg is an estimate that knew a last sale (54% of the quick resales; that sale was a median 10 years before)."""
    key = pd.Series(resid, index=pd.MultiIndex.from_frame(s[["address_key", "sale_date"]])); key = key[~key.index.duplicated()]
    hadprev = s.prev_price.notna().groupby([s.address_key, s.sale_date]).first()
    pairs = s[s.prev_price.notna() & (s.prev_new_build == False) & (s.prev_date >= "2015-01-01")].copy()
    pairs["resid"] = resid[pairs.index]
    pairs["prev_resid"] = [key.get((a, d), np.nan) for a, d in zip(pairs.address_key, pairs.prev_date)]
    if purchase_had_prev: pairs = pairs[[bool(hadprev.get((a, d), False)) for a, d in zip(pairs.address_key, pairs.prev_date)]]
    pairs = pairs.dropna(subset=["prev_resid"]); pairs["hold_m"] = (pairs.sale_date - pairs.prev_date).dt.days / 30.44
    flips, control = pairs[(pairs.hold_m >= 3) & (pairs.hold_m <= 18)], pairs[pairs.hold_m >= 60]
    r = dict(n_flips=int(len(flips)), n_control=int(len(control)),
             flips_purchase=pc(np.median(flips.prev_resid)), flips_resale=pc(np.median(flips.resid)),
             control_purchase=pc(np.median(control.prev_resid)), control_resale=pc(np.median(control.resid)))
    r["needs_full_renovation"] = pc(np.median(flips.prev_resid) - np.median(control.prev_resid))
    r["recently_refurbished"] = pc(np.median(flips.resid) - np.median(control.resid))
    r["needs_q"] = [pc(np.quantile(flips.prev_resid, q) - np.median(control.prev_resid)) for q in (.25, .75)]
    r["refurb_q"] = [pc(np.quantile(flips.resid, q) - np.median(control.resid)) for q in (.25, .75)]
    return r

if "--from-json" in sys.argv:                                   # write the dataset from the last run without refitting (15 models)
    res = json.load(open(OUT / "condition_calibration_v21.json"))
else:
    res = {}
    clean = lambda r: {k: (float(v) if isinstance(v, (float, np.floating)) else [float(x) for x in v] if isinstance(v, list) else v) for k, v in r.items()}
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    if only: res = json.load(open(OUT / "condition_calibration_v21.json"))
    for name, cols, grouped in (("published_kfold_noprev", NOPREV, False), ("grouped_noprev", NOPREV, True), ("grouped_full", E.FULL, True)):
        if only and name not in only: continue
        resid = oof(cols, grouped); res[name] = clean(calibrate(resid)); print(name, res[name], flush=True)
        if name == "grouped_full": res["grouped_full_purchase_had_prev"] = clean(calibrate(resid, True)); print("grouped_full_purchase_had_prev", res["grouped_full_purchase_had_prev"], flush=True)
    json.dump(res, open(OUT / "condition_calibration_v21.json", "w"), indent=1)

if "--write" in sys.argv:
    # two calibrations (fifth review). adjustment_pct: against the model without last-sale features, for an estimate
    # made without a last sale. adjustment_prev_pct: against the full served model, for an estimate that knows the last
    # sale. The full model's purchase leg has the purchase's own earlier sale, usually years before; its resale leg has
    # the purchase itself as the last sale, so its +0.6% applies to a last sale within 18 months (the dashboard and
    # src/predict.py use the no-last-sale premium when the last sale is older, a case this data can't measure).
    c, f_ = res["grouped_noprev"], dict(res["grouped_full"]); n = c["n_flips"]
    if "grouped_full_purchase_had_prev" in res:                    # the purchase leg, only where it knew an earlier sale
        fp = res["grouped_full_purchase_had_prev"]; f_["needs_full_renovation"], f_["needs_q"], n_p = fp["needs_full_renovation"], fp["needs_q"], fp["n_flips"]
    else: n_p = f_["n_flips"]
    q = lambda x: round(float(x), 1)
    rows = [("needs_full_renovation", "Needs full renovation", c["needs_full_renovation"], c["needs_q"][0], c["needs_q"][1],
             f"Median residual at purchase for 3-18 month resales (n={n}), less the same for resales after 5+ years; folds grouped by home",
             f_["needs_full_renovation"], f_["needs_q"][0], f_["needs_q"][1], f"Full model: purchases that had an earlier sale (n={n_p}), valued knowing it, less the same for long-hold resales"),
            ("dated", "Dated", c["needs_full_renovation"] / 2, "", "", "Half of the needs-renovation discount (interpolated)", f_["needs_full_renovation"] / 2, "", "", "Half (interpolated)"),
            ("average", "Average", 0.0, "", "", "Model baseline", 0.0, "", "", "Model baseline"),
            ("good", "Good", c["recently_refurbished"] / 2, "", "", "Half of the refurbished premium (interpolated)", f_["recently_refurbished"] / 2, "", "", "Half (interpolated)"),
            ("recently_refurbished", "Recently refurbished", c["recently_refurbished"], c["refurb_q"][0], c["refurb_q"][1],
             f"Median residual at resale for 3-18 month resales (n={n}), less the same for resales after 5+ years; folds grouped by home",
             f_["recently_refurbished"], f_["refurb_q"][0], f_["refurb_q"][1], "Full model: the resale, valued knowing the purchase 3-18 months before")]
    for f in (D / "condition.csv", E.ROOT / "model/condition.csv"):
        with open(f, "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["condition", "label", "adjustment_pct", "range_low_pct", "range_high_pct", "basis",
                                            "adjustment_prev_pct", "range_low_prev_pct", "range_high_prev_pct", "basis_prev"])
            w.writerows([[a, b, q(v), "" if lo == "" else q(lo), "" if hi == "" else q(hi), basis, q(vp), "" if lp == "" else q(lp), "" if hp == "" else q(hp), bp]
                         for a, b, v, lo, hi, basis, vp, lp, hp, bp in rows])
    print("wrote condition.csv")
