"""Train and validate the Doncaster valuation model.

Split (temporal, like a real valuation tool): train 2015-2023, validate 2024, test Jan 2025 - Aug 2026.
Target: log(price) minus log(price index known at the valuation date).
Models: (1) ridge hedonic baseline with LSOA dummies, (2) LightGBM.
Interval: split-conformal on 2024 residuals, by predicted-price band (80% coverage target)."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import json, pathlib, numpy as np, pandas as pd, duckdb, lightgbm as lgb
from sklearn.linear_model import Ridge
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from price_index import fit_index
from features import add_prior_levels, matrix, NUM, CAT

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"; OUT.mkdir(exist_ok=True)
con = duckdb.connect(str(ROOT / "data/processed/doncaster.duckdb"), read_only=True)
df = con.execute("select * from sales_seq where sale_date >= '2014-01-01'").df()
df["sale_date"] = pd.to_datetime(df["sale_date"]); df["month"] = df["sale_date"].values.astype("datetime64[M]")
print("rows 2014+:", len(df))

# ---------- 1. price index known at valuation time ----------
TRAIN_END, VAL_END = pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")
idx_hist = fit_index(df[df.sale_date <= VAL_END])                        # in-sample for 2014-2024
rt = {}                                                                   # real-time index for 2025+
for m in pd.date_range("2025-01-01", df.month.max(), freq="MS"):
    cutoff = m - pd.DateOffset(months=2)                                  # ~2-month publication lag
    ix = fit_index(df[df.month <= cutoff])
    common = min(ix.index.max(), pd.Timestamp("2024-12-01"))             # chain-link to the historic index
    rt[m] = ix.iloc[-1] / ix.loc[common] * idx_hist.loc[common]
index_known = pd.concat([idx_hist, pd.Series(rt)]).sort_index()
df["log_idx"] = np.log(df["month"].map(index_known))
df["y"] = np.log(df["price"]); df["y_defl"] = df["y"] - df["log_idx"]

# ---------- 2. features (local price levels from earlier sales only) ----------
df = add_prior_levels(df)
df = df[df.sale_date >= "2015-01-01"].copy()
train, val, test = df[df.sale_date <= TRAIN_END], df[(df.sale_date > TRAIN_END) & (df.sale_date <= VAL_END)], df[df.sale_date > VAL_END]
print("train/val/test:", len(train), len(val), len(test))

def metrics(y_true_log, y_pred_log):
    p, a = np.exp(y_pred_log), np.exp(y_true_log)
    ape = np.abs(p - a) / a
    return dict(n=int(len(a)), mae=float(np.mean(np.abs(p - a))), mdape=float(np.median(ape)),
                within10=float(np.mean(ape <= .10)), within20=float(np.mean(ape <= .20)),
                r2_log=float(1 - np.sum((y_true_log - y_pred_log) ** 2) / np.sum((y_true_log - y_true_log.mean()) ** 2)))

# ---------- 3a. ridge hedonic baseline ----------
num_cols = NUM
ridge = make_pipeline(ColumnTransformer([
    ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), num_cols),
    ("cat", OneHotEncoder(handle_unknown="ignore"), ["property_type", "tenure", "new_build", "lsoa21"])]), Ridge(alpha=1.0))
ridge.fit(train[num_cols + ["property_type", "tenure", "new_build", "lsoa21"]], train["y_defl"])
def ridge_pred(d): return ridge.predict(d[num_cols + ["property_type", "tenure", "new_build", "lsoa21"]]) + d["log_idx"].values

# ---------- 3b. LightGBM ----------
params = dict(objective="regression_l1", learning_rate=0.03, num_leaves=63, min_data_in_leaf=30,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=42)
dtr = lgb.Dataset(matrix(train), train["y_defl"], categorical_feature=["property_type"])
dva = lgb.Dataset(matrix(val), val["y_defl"], reference=dtr)
gbm = lgb.train(params, dtr, 5000, valid_sets=[dva], callbacks=[lgb.early_stopping(200, verbose=False)])
best_iter = gbm.best_iteration; print("best iteration:", best_iter)
def gbm_pred(d): return gbm.predict(matrix(d), num_iteration=best_iter) + d["log_idx"].values

res = {}
for name, f in [("ridge", ridge_pred), ("lightgbm", gbm_pred)]:
    res[name] = {s: metrics(d["y"].values, f(d)) for s, d in [("validation_2024", val), ("test_2025_26", test)]}
print(json.dumps(res, indent=1))

# ---------- 4. conformal 80% interval from 2024 residuals, by predicted price band ----------
val_pred = gbm_pred(val); r = val["y"].values - val_pred
bands = [0, 100_000, 150_000, 200_000, 300_000, 10**9]
band_of = lambda p: np.digitize(p, bands[1:-1])
vb = band_of(np.exp(val_pred))
q = {int(b): (float(np.quantile(r[vb == b], .10)), float(np.quantile(r[vb == b], .90))) for b in np.unique(vb)}
tp = gbm_pred(test); tb = band_of(np.exp(tp))
lo = np.array([q[int(b)][0] for b in tb]); hi = np.array([q[int(b)][1] for b in tb])
cover = float(np.mean((test["y"].values >= tp + lo) & (test["y"].values <= tp + hi)))
print("test coverage of 80% interval:", round(cover, 3))
res["interval"] = dict(bands=bands, quantiles=q, test_coverage_80=cover)

# breakdowns on test (for the accuracy tab)
t = test.assign(pred=np.exp(tp), ape=np.abs(np.exp(tp) - test.price) / test.price)
res["by_type"] = t.groupby("property_type").agg(n=("ape", "size"), mdape=("ape", "median"), within10=("ape", lambda s: (s <= .1).mean())).reset_index().to_dict("records")
t["band"] = pd.cut(t.price, bands, labels=["<100k", "100-150k", "150-200k", "200-300k", "300k+"])
res["by_band"] = t.groupby("band", observed=True).agg(n=("ape", "size"), mdape=("ape", "median"), within10=("ape", lambda s: (s <= .1).mean())).reset_index().astype({"band": str}).to_dict("records")
res["by_district"] = t.groupby("district").agg(n=("ape", "size"), mdape=("ape", "median")).reset_index().query("n>=30").to_dict("records")
imp = pd.Series(gbm.feature_importance("gain"), index=gbm.feature_name()).sort_values(ascending=False)
res["feature_importance_gain_share"] = (imp / imp.sum()).round(4).to_dict()
json.dump(res, open(OUT / "metrics.json", "w"), indent=1, default=float)
t[["unique_id", "sale_date", "postcode", "property_type", "price", "pred", "ape"]].to_csv(OUT / "test_predictions.csv", index=False)
index_known.rename("index").to_csv(OUT / "price_index.csv")
gbm.save_model(str(OUT / "gbm_trainval.txt"), num_iteration=best_iter)
df.to_parquet(ROOT / "data/processed/model_frame.parquet")
print("saved")
