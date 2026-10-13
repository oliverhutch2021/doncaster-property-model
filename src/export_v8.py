"""Version 8 dashboard datasets for the Model accuracy tab and the confidence score.

backtest.csv        median error and the assessors' checks for each year since 2020 (src/model_v8_backtest.py)
ratio_study.csv     the IAAO ratio-study checks (COD, PRD, PRB) on 2025-26, and the median estimate / price by price band
confidence.csv      accuracy by confidence level, and when only the most confident estimates are kept (src/model_v8_confidence.py)
model_meta.json     + the confidence model's inputs, range scaling and levels; conf_trees.json is written by the confidence script"""
import json, pathlib, sys, numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"; D = OUT / "dash2"
sys.path.insert(0, str(ROOT / "src"))
from model_v8_backtest import ratio_study

# ---------- against simple methods: written by src/compare_methods.py since the fourth review ----------

# ---------- year by year ----------
if (OUT / "backtest.json").exists():
    bt = pd.DataFrame(json.load(open(OUT / "backtest.json"))).drop_duplicates("year", keep="last")
    cols = ["year", "n", "trained_to", "mdape", "within10", "within20", "mdape_no_correction", "median_bias", "cod", "prd", "prb", "partial"]
    bt = bt[[c for c in cols if c in bt]]
    bt.round(5).to_csv(D / "backtest.csv", index=False); print("backtest:", bt[["year", "mdape"]].values.tolist())

# ---------- assessors' checks on the dashboard model's 2025-26 estimates ----------
pred_file = OUT / "dashboard_test_predictions.csv"
if not pred_file.exists(): pred_file = OUT / "compare_methods_predictions.csv"
p = pd.read_csv(pred_file); est_col = "estimate" if "estimate" in p else "model_reported"
price, est = p.price.values.astype(float), p[est_col].values.astype(float)
rs = [dict(kind="overall", group="This model", n=len(p), median_ratio=float(np.median(est / price)), **ratio_study(price, est))]
if "uk_hpi" in p:
    ok = p.uk_hpi.notna().values
    rs.append(dict(kind="overall", group="Last sale x UK HPI", n=int(ok.sum()), median_ratio=float(np.median(p.uk_hpi.values[ok] / price[ok])), **ratio_study(price[ok], p.uk_hpi.values[ok])))
edges = [0, 75e3, 100e3, 150e3, 200e3, 300e3, 1e9]; labels = ["Under £75k", "£75k-100k", "£100k-150k", "£150k-200k", "£200k-300k", "£300k+"]
band = pd.cut(price, edges, labels=labels)
for b in labels:
    k = (band == b)
    rs.append(dict(kind="band", group=b, n=int(k.sum()), median_ratio=float(np.median(est[k] / price[k]))))
o = rs[0]
rs.append(dict(kind="note", group=("Grouping by sale price exaggerates this: a home that sold unusually cheaply lands in a low band and looks over-valued, "
                                   "and any estimate shows some of it. Simple methods show less (indexing the last sale: PRB "
                                   f"{rs[1]['prb']:+.3f}), so part of it is the model pulling estimates towards the middle. Stretching the estimates to remove it "
                                   "cost 0.7 points of median error in testing, so they are left as they are." if len(rs) > 1 and rs[1]["kind"] == "overall" else "")))
pd.DataFrame(rs).to_csv(D / "ratio_study.csv", index=False)
print("ratio study:", {k: round(v, 3) for k, v in o.items() if isinstance(v, float)})

# ---------- confidence ----------
if (OUT / "confidence.json").exists():
    c = json.load(open(OUT / "confidence.json"))
    cr = [dict(kind="level", level=r["level"], share=round(r["share"], 4), n=r["n"], mdape=round(r["mdape"], 5), within10=round(r["within10"], 4),
               coverage=round(r.get("coverage_used", r["coverage_new"]), 4), typical_error=round(r["typical_error_predicted"], 4)) for r in c["by_level"]]
    cr += [dict(kind="filter", kept=r["kept"], mdape=round(r["mdape"], 5), within10=round(r["within10"], 4)) for r in c["filter_curve"]]
    pd.DataFrame(cr).to_csv(D / "confidence.csv", index=False)
    meta = json.load(open(D / "model_meta.json")); mm = {r["key"]: i for i, r in enumerate(meta)}
    adaptive = bool(c.get("adopt_adaptive", False))
    ty = json.load(open(OUT / "confidence_typed.json")) if (OUT / "confidence_typed.json").exists() else None   # src/model_v8_typed.py
    extra = dict(conf_typed_scale=str(ty["scale"]), conf_typed_q10=str(ty["q10"]), conf_typed_q90=str(ty["q90"])) if ty else {}
    for k, v in (dict(conf_features=json.dumps(c["features"]), conf_q10=str(c["q10"]), conf_q90=str(c["q90"]),
                      conf_levels=json.dumps(c["levels"]), conf_adaptive="true" if adaptive else "false") | extra).items():
        if k in mm: meta[mm[k]]["value"] = v
        else: meta.append({"key": k, "value": v})
    json.dump(meta, open(D / "model_meta.json", "w"))
    print("confidence levels:", [(r["level"], r["share"], r["mdape"]) for r in cr if r["kind"] == "level"], "| adaptive ranges:", adaptive)
