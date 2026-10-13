"""Where does the v2 model miss? Test-set (2025-26) bias by price, type, area, local growth and local price spread.
Bias = median of log(actual / predicted); negative = the model over-values, positive = under-values."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, numpy as np, pandas as pd, lightgbm as lgb
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"
s = pd.read_parquet(ROOT / "data/processed/model_frame_v3.parquet"); keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])
BASE = ["lat","lon","dist_centre_km","imd_score","imd_income","imd_employment","imd_education","imd_health","imd_crime","imd_barriers","imd_living_env","lvl_sector_type","lvl_lsoa","n_sector_type","property_type","tenure","new_build"]
EPC = ["floor_area","rooms","age_year","bungalow","built_form_code","extensions","sap_current","sap_potential","sap_gap","mains_gas"]
FULL = BASE + EPC + ["knn_lvl","knn_dist","knn_ppsqm","prev_defl","years_since_prev","prev_nb"]
def X(d, cols=FULL):
    x = d[cols].copy(); x["property_type"] = d.property_type.map({"D":0,"S":1,"T":2,"F":3}).astype(int); x["tenure"]=(d.tenure=="L").astype(int); x["new_build"]=d.new_build.astype(int); return x.astype(float)
P = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=30, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=1)
tr = s[(s.sale_date <= "2023-12-31") & s.unique_id.isin(keep)]; va = s[(s.sale_date > "2023-12-31") & (s.sale_date <= "2024-12-31") & s.unique_id.isin(keep)]
te = s[s.sale_date > "2024-12-31"].copy()
dt = lgb.Dataset(X(tr), tr.y_defl, categorical_feature=["property_type"])
m = lgb.train(P, dt, 5000, valid_sets=[lgb.Dataset(X(va), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
te["pred"] = m.predict(X(te), num_iteration=m.best_iteration) + te.log_idx.values
te["r"] = np.log(te.price) - te.pred; te["ape"] = np.abs(np.exp(-te.r) - 1)
print("test n", len(te), "mdape", round(te.ape.median(), 4), "overall bias", f"{100*(np.exp(te.r.median())-1):+.2f}%")
def show(by, name):
    g = te.groupby(by, observed=True).agg(n=("r", "size"), bias=("r", "median"), mdape=("ape", "median"))
    g["bias"] = (np.exp(g.bias) - 1) * 100; g["mdape"] *= 100; print(f"\n{name}\n" + g.round(1).to_string())
show(pd.qcut(np.exp(te.pred), 5), "by PREDICTED price quintile (calibration)")
show(pd.qcut(te.price, 5), "by ACTUAL price quintile (includes regression to the mean)")
show(te.property_type, "by type")
# local growth: sector change in median deflated price, last 12 months before 2025 vs 24 months before that
pre = s[s.sale_date <= "2024-12-31"]
rec = pre[pre.sale_date > "2023-12-31"].groupby("sector").y_defl.median(); old = pre[(pre.sale_date > "2021-12-31") & (pre.sale_date <= "2023-12-31")].groupby("sector").y_defl.median()
mom = (rec - old).rename("momentum"); te = te.merge(mom, left_on="sector", right_index=True, how="left")
show(pd.qcut(te.momentum, 4), "by sector momentum before the test period (2024 vs 2022-23 local level)")
# local spread: IQR of deflated prices among the 10 nearest same-type earlier sales is not stored; use sector-type dispersion in training years
disp = tr.groupby(["sector", "property_type"]).y_defl.agg(lambda v: v.quantile(.9) - v.quantile(.1)).rename("spread")
te = te.merge(disp, left_on=["sector", "property_type"], right_index=True, how="left")
show(pd.qcut(te.spread, 4), "by local price spread (10th-90th pct range, sector+type)")
show(pd.cut(te.floor_area / np.exp(te.knn_ppsqm.fillna(np.nan)) , [0, 0, 1e9]).astype(str) if False else te.prev_defl.notna().map({True: "last sale known", False: "no last sale"}), "by last sale known")
# home bigger than neighbours? floor area relative to sector-type median floor area
fa_med = tr.groupby(["sector", "property_type"]).floor_area.median().rename("fa_med")
te = te.merge(fa_med, left_on=["sector", "property_type"], right_index=True, how="left"); te["fa_rel"] = te.floor_area / te.fa_med
show(pd.cut(te.fa_rel, [0, .8, 1.0, 1.25, 1.6, 10]), "by floor area vs typical for the sector and type")
sec = te.groupby("sector").agg(n=("r", "size"), bias=("r", "median"), mdape=("ape", "median")).query("n >= 40")
sec["bias_pct"] = (np.exp(sec.bias) - 1) * 100; sec["se"] = te.groupby("sector").r.agg(lambda v: 1.2533 * v.std() / np.sqrt(len(v))).reindex(sec.index) * 100
sec["z"] = sec.bias_pct / sec.se
print("\nsectors with 40+ test sales:", len(sec), "| |bias| > 2 standard errors:", int((sec.z.abs() > 2).sum()), "(expect ~", round(0.05 * len(sec), 1), "by chance)")
print(sec.sort_values("bias_pct").round(1)[["n", "bias_pct", "se", "mdape"]].head(6).to_string()); print(sec.sort_values("bias_pct").round(1)[["n", "bias_pct", "se", "mdape"]].tail(8).to_string())
te[["unique_id", "sale_date", "price", "pred", "r", "sector", "postcode", "property_type", "momentum", "spread", "fa_rel"]].to_parquet(ROOT / "data/processed/test_resid_v2.parquet")
