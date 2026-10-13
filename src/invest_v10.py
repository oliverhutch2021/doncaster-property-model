"""Rent model and neighbourhood comparisons for the Invest tab (v10).

1. Rent model. No open data gives the rent of one home, so the estimate links rent to value:
     rent = Doncaster's ONS average rent for the type x (home's value / Doncaster's UK HPI average price for the type) ^ beta
   beta is how far rents follow prices: fitted across English and Welsh council areas on the latest ONS Price Index of
   Private Rents (by type) against the UK HPI average price by type (last 12 months), with region and type effects:
     log rent[area, type] = region + type + beta x log price[area, type]
   Tested by leaving each council area out in turn (all four types at once) and predicting its rents; compared with a
   baseline that knows only the region's average rent for the type. Checked inside Doncaster: rent against price
   across the four types. The likely range is the middle half of Doncaster rents for the bedroom count (ONS private
   rental market statistics, Oct 2022 to Sep 2023, the last with quartiles), as ratios to the median.
2. Neighbourhood comparisons, for each neighbourhood (and Doncaster) and type (and all types), from sales in the last
   3 years: the spread of price against model value (out-of-sample backtest residuals), of price per m2, and of gross
   yield at the modelled rent. Stored as log-scale mean, SD and percentiles, so the page can say how many SDs and what
   share of recent sales a home beats.
Outputs: outputs/dash2/rent_model.csv, outputs/dash2/nb_dist.csv, outputs/invest_v10.json"""
import json, pathlib, numpy as np, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; D = ROOT / "outputs/dash2"; OUT = ROOT / "outputs"
LA = "E08000017"; T4 = {"D": "detached", "S": "semidetached", "T": "terraced", "F": "flat maisonette"}
HPI = {"D": "DetachedPrice", "S": "SemiDetachedPrice", "T": "TerracedPrice", "F": "FlatPrice"}

# ---------------- 1. rents against prices across council areas ----------------
pipr = pd.read_excel(RAW / "pipr.xlsx", "Table 1", header=2)
last = pipr["Time period"].max(); p = pipr[(pipr["Time period"] == last) & pipr["Area code"].astype(str).str.match(r"^(E0[6-9]|W06)")].copy()
p["region"] = p["Region or country name"].astype(str)
hpi = pd.read_csv(RAW / "ukhpi/UK-HPI-full-file-2026-07.csv", usecols=["Date", "AreaCode"] + list(HPI.values()))
hpi["date"] = pd.to_datetime(hpi.Date, dayfirst=True); h_end = hpi.date.max()
h = hpi[hpi.date > h_end - pd.DateOffset(months=12)].groupby("AreaCode")[list(HPI.values())].apply(lambda g: np.exp(np.log(g).mean()))
rows = []
for _, r in p.iterrows():
    if r["Area code"] not in h.index: continue
    for t, col in T4.items():
        rent, price = pd.to_numeric(r[f"Rental price {col}"], errors="coerce"), h.loc[r["Area code"], HPI[t]]
        if pd.notna(rent) and pd.notna(price) and rent > 0 and price > 0: rows.append(dict(area=r["Area code"], name=r["Area name"], region=r.region, type=t, lr=np.log(rent), lp=np.log(price)))
X = pd.DataFrame(rows); print(f"{X.area.nunique()} council areas, {len(X)} area-type rents ({last.date():%b %Y} rents, UK HPI {h_end - pd.DateOffset(months=11):%b %Y}-{h_end:%b %Y} prices)")

def design(d, cols_r, cols_t, with_price=True):
    M = [np.ones(len(d))] + [(d.region == c).astype(float).values for c in cols_r[1:]] + [(d.type == c).astype(float).values for c in cols_t[1:]]
    if with_price: M.append(d.lp.values)
    return np.column_stack(M)
R_, T_ = sorted(X.region.unique()), ["S", "D", "T", "F"]
def fit(d, with_price=True):
    A = design(d, R_, T_, with_price); b, *_ = np.linalg.lstsq(A, d.lr.values, rcond=None); return b
b = fit(X); beta = float(b[-1]); res = X.lr.values - design(X, R_, T_) @ b
A = design(X, R_, T_); cov = np.linalg.inv(A.T @ A) * (res @ res) / (len(X) - A.shape[1])
# standard error clustered by area (the four types of one area share its errors)
meat = np.zeros_like(cov)
for _, g in X.assign(e=res).groupby("area"): s = design(g, R_, T_).T @ g.e.values; meat += np.outer(s, s)
bread = np.linalg.inv(A.T @ A); se_cl = float(np.sqrt((bread @ meat @ bread)[-1, -1]))
r2 = 1 - res.var() / X.lr.var()
# leave one area out
err, err0 = [], []
for a in X.area.unique():
    tr, te = X[X.area != a], X[X.area == a]
    # absolute percentage error with the ACTUAL rent as the base: |predicted / actual - 1| (v18; was divided by the prediction)
    err += list(np.abs(np.exp(design(te, R_, T_) @ fit(tr) - te.lr.values) - 1))
    err0 += list(np.abs(np.exp(design(te, R_, T_, False) @ fit(tr, False) - te.lr.values) - 1))
by_type = {t: float(np.polyfit(g.lp - g.groupby("region").lp.transform("mean"), g.lr - g.groupby("region").lr.transform("mean"), 1)[0]) for t, g in X.groupby("type")}
print(f"beta = {beta:.3f} (clustered SE {se_cl:.3f}), R2 {r2:.3f}; leave-one-area-out median error {np.median(err):.1%} vs {np.median(err0):.1%} without prices")
print("beta by type (within regions):", {k: round(v, 3) for k, v in by_type.items()})
dn = X[X.area == LA].set_index("type"); slope_dn = float(np.polyfit(dn.lp, dn.lr, 1)[0])
print("inside Doncaster, rent against price across the 4 types: slope", round(slope_dn, 3), dn.assign(rent=np.exp(dn.lr).round(), price=np.exp(dn.lp).round(-3))[["rent", "price"]].to_dict("index"))

# ---------------- rent quartiles, Doncaster (ONS PRMS, Oct 2022 - Sep 2023) ----------------
prms = {}
for k, sheet in (("1", "Table2.3"), ("2", "Table2.4"), ("3", "Table2.5"), ("4", "Table2.6"), ("all", "Table2.7")):
    t = pd.read_excel(RAW / "prms/prms_2022_23.xls", sheet, header=None)
    row = t[t.iloc[:, 2] == LA].iloc[0]; cnt, mean, lq, med, uq = [pd.to_numeric(row.iloc[i], errors="coerce") for i in (4, 5, 6, 7, 8)]
    prms[k] = dict(count=int(cnt), mean=float(mean), lq=float(lq), median=float(med), uq=float(uq))
print("PRMS Doncaster:", prms)

rent_now = {t: float(np.exp(dn.loc[t, "lr"])) for t in "DSTF"}; ref = {t: float(np.exp(dn.loc[t, "lp"])) for t in "DSTF"}
mm = f"{last:%b %Y}"; hp = f"{h_end - pd.DateOffset(months=11):%b %Y} to {h_end:%b %Y}"
RM = [("beta", round(beta, 4), "How far rents follow prices: % change in rent for each 1% of value", f"Fitted across {X.area.nunique()} council areas in England and Wales, ONS rents ({mm}) against UK HPI prices ({hp}), with region and type effects"),
      ("beta_se", round(se_cl, 4), "Standard error of beta (clustered by area)", "Same fit"),
      ("loo_error", round(float(np.median(err)) * 100, 2), "Median error predicting an area's rents it hadn't seen (% of the actual rent)", "Leave one council area out"),
      ("loo_error_base", round(float(np.median(err0)) * 100, 2), "Same, knowing only the region's average rent for the type (%)", "Leave one council area out, no prices"),
      ("r2", round(float(r2), 4), "Share of variation in area rents explained", "Same fit"),
      ("n_areas", int(X.area.nunique()), "Council areas in the fit", "ONS PIPR and UK HPI"),
      ("slope_doncaster", round(slope_dn, 4), "Inside Doncaster: rent against price across the four types", f"ONS rents ({mm}) and UK HPI prices for Doncaster")]
for t in "DSTF":
    RM.append((f"rent_{t}", round(rent_now[t]), f"Doncaster average rent, {T4[t]} (£ a month)", f"ONS Price Index of Private Rents, {mm}"))
    RM.append((f"ref_price_{t}", round(ref[t]), f"Doncaster average price, {T4[t]} (£)", f"UK HPI, geometric mean of {hp}"))
for k, v in prms.items():
    RM.append((f"rq_lq_{k}", round(v["lq"] / v["median"], 4), f"Lower quartile ÷ median rent, {'all homes' if k == 'all' else k + (' bedroom' if k == '1' else '+ bedrooms' if k == '4' else ' bedrooms')}", f"ONS private rental market statistics, Doncaster, Oct 2022 to Sep 2023 ({v['count']} rents)"))
    RM.append((f"rq_uq_{k}", round(v["uq"] / v["median"], 4), f"Upper quartile ÷ median rent, {'all homes' if k == 'all' else k + (' bedroom' if k == '1' else '+ bedrooms' if k == '4' else ' bedrooms')}", f"ONS private rental market statistics, Doncaster, Oct 2022 to Sep 2023 ({v['count']} rents)"))
pd.DataFrame(RM, columns=["key", "value", "label", "source"]).to_csv(D / "rent_model.csv", index=False)

# ---------------- 2. neighbourhood spreads ----------------
mf = pd.read_parquet(ROOT / "data/processed/model_frame_v7.parquet", columns=["unique_id", "price", "sale_date", "property_type", "floor_area", "msoa21"])
END = mf.sale_date.max(); s = mf[mf.sale_date > END - pd.DateOffset(years=3)].copy()
bt = pd.read_parquet(ROOT / "data/processed/backtest_residuals.parquet", columns=["unique_id", "sale_date", "resid"])
s = s.merge(bt[["unique_id", "resid"]], on="unique_id", how="left")
s["l_ppsqm"] = np.log(s.price / s.floor_area)
s["l_yield"] = np.log(1200 * s.property_type.map(rent_now) * (s.price / s.property_type.map(ref)) ** beta / s.price)
print(f"3-year sales {len(s):,}: with out-of-sample residual {s.resid.notna().mean():.0%}, with floor area {s.floor_area.notna().mean():.0%}")
Q = [5, 10, 25, 50, 75, 90, 95]; out = []
def add(code, t, g):
    for m, col in (("deal", "resid"), ("ppsqm", "l_ppsqm"), ("yield", "l_yield")):
        v = g[col].dropna().values
        if len(v) < 15: continue
        lo, hi = np.percentile(v, [1, 99]); w = v[(v >= lo) & (v <= hi)]       # trim the 1% tails for the mean and SD
        out.append(dict(msoa21=code, type=t, metric=m, n=len(v), mean=round(float(w.mean()), 5), sd=round(float(w.std(ddof=1)), 5), **{f"p{q}": round(float(np.percentile(v, q)), 5) for q in Q}))
for code, g in list(s.groupby("msoa21")) + [(LA, s)]:
    add(code, "A", g)
    for t, gt in g.groupby("property_type"): add(code, t, gt)
nd = pd.DataFrame(out); nd.to_csv(D / "nb_dist.csv", index=False)
print("nb_dist rows", len(nd), "| neighbourhoods with all metrics, all types:", nd[(nd.type == "A")].groupby("msoa21").metric.nunique().eq(3).sum())
print(nd[(nd.msoa21 == LA)].to_string())
json.dump(dict(beta=beta, beta_se=se_cl, r2=r2, loo_mdape=float(np.median(err)), loo_mdape_base=float(np.median(err0)), beta_by_type=by_type, slope_doncaster=slope_dn,
               n_areas=int(X.area.nunique()), prms=prms, rents=rent_now, ref_prices=ref), open(OUT / "invest_v10.json", "w"), indent=1)
