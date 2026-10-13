"""Training and serving build the same features (fourth review).

For 400 sales from 2026 whose certificate in the address lookup is the one the training row used, the features that
src/predict.py builds from the lookup are compared with the training frame (data/processed/model_frame_v7.parquet):
  - home, place and certificate fields must match, to the rounding of the exported lookups
  - the last sale (price, month, whether it was a new build) must match, taking the sale before this one
  - price levels and neighbour prices are as of the valuation month in serving and as of the sale in training, so they
    differ by design and aren't compared; nor is the certificate's age
Needs a full checkout with the address lookup built (python src/assemble_model_dir.py --with-addresses); skips otherwise.
  python tests/test_parity.py"""
import json, pathlib, sys, numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
FRAME = ROOT / "data/processed/model_frame_v7.parquet"
if not FRAME.exists() or not any((ROOT / "model").glob("epc_*.csv")):
    print("SKIP: needs the training frame and the address lookup (full checkout)"); sys.exit(0)
import predict as PR
d = PR.load()
TIME = {"lvl_sector_type", "n_sector_type", "lvl_lsoa", "knn_lvl", "knn_dist", "knn_ppsqm", "lvl_street_type", "n_street_type", "lvl_postcode", "n_postcode",
        "years_since_prev", "epc_age_y"}
TOL = dict(lat=1e-5, lon=1e-5, dist_centre_km=5e-4, plot_m2=0.5, plot_m2_per_home=0.5, ceiling_m=0.005, glazing=0.005, prev_defl=1e-4)
s = pd.read_parquet(FRAME); s = s[(s.sale_date >= "2026-01-01") & s.dwelling.notna()].sample(400, random_state=1)
class A: pass
rows, used, cache = [], 0, {}
for r in s.itertuples():
    dist = r.postcode.split(" ")[0]
    if dist not in cache:
        f = PR.M / f"epc_{dist}.csv"; cache[dist] = pd.read_csv(f) if f.exists() else None
    e = cache[dist]
    if e is None: continue
    hit = e[(e.postcode == r.postcode) & e.sales.fillna("").str.contains(f"{r.sale_date:%Y-%m-%d}|{int(r.price)}", regex=False)]
    if len(hit) != 1: continue
    epc = hit.iloc[0].to_dict()
    if pd.Timestamp(epc["lodged"]) > r.sale_date + pd.Timedelta(days=90): continue      # serving uses a later certificate than training: different by design
    a = A(); a.postcode, a.type, a.tenure, a.new_build, a.bungalow = r.postcode, r.property_type, r.tenure, bool(r.new_build), False
    a.area = a.rooms = a.age = a.form = a.rating = a.plot = None
    ls = PR.last_sale(epc, before=f"{r.sale_date:%Y-%m-%d}")
    a.prev_price, a.prev_month, a.prev_new_build = (ls["price"], ls["month"], ls["new_build"]) if ls else (None, None, False)
    if PR.check_inputs(a, d): continue
    _, feat = PR.features(d, a, epc); used += 1
    for k in d["meta"]["features"]:
        if k in TIME: continue
        tv, sv = getattr(r, k), feat[k]
        tv = {"D": 0, "S": 1, "T": 2, "F": 3}[tv] if k == "property_type" else (1 if tv == "L" else 0) if k == "tenure" else int(tv) if k == "new_build" else tv
        tv = float(tv) if tv is not None and pd.notna(tv) else np.nan; sv = float(sv) if sv is not None and pd.notna(sv) else np.nan
        same = (np.isnan(tv) and np.isnan(sv)) or (np.isfinite(tv) and np.isfinite(sv) and abs(tv - sv) <= TOL.get(k, 1e-6) * (1 if k in TOL else max(1, abs(tv))))
        rows.append((k, same, tv, sv))
df = pd.DataFrame(rows, columns=["feature", "same", "train", "serve"])
share = df.groupby("feature").same.mean().sort_values()
print(f"{used} sales compared on {df.feature.nunique()} features")
fails = share[share < 0.99]          # a few homes have a second certificate in the 90-day window: allow 1%
for k, v in share[share < 1].items(): print(("FAIL " if k in fails else "note ") + f"{k}: {v:.1%} match", df[(df.feature == k) & ~df.same].head(2)[["train", "serve"]].values.tolist())
print("PASS: training and serving agree" if not len(fails) and used >= 200 else f"FAIL: {len(fails)} features differ"); sys.exit(0 if not len(fails) and used >= 200 else 1)
