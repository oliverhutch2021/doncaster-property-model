"""Neighbourhood investment figures for the Areas tab (v9).

Neighbourhoods are Doncaster's 39 middle-layer super output areas (MSOAs, 2021), named by the House of Commons Library
(MSOA Names 2.2, Open Parliament Licence). Each holds about five of the map's 199 LSOAs exactly.

  prices     the last 3 years of standard Land Registry sales (Sep 2023 to Aug 2026): median price overall and by type,
             type mix, new-build share, sales a year; price per m2 and floor area from the model's sales with a certificate; turnover = sales a year / homes
             (VOA council tax stock, March 2025)
  rents      the borough's ONS rents by property type (Price Index of Private Rents, Doncaster, latest month) for every
             neighbourhood: no open source gives rents below the borough. Gross yield by type = 12 x rent / median price;
             all types = the type-mix-weighted average of the type yields
  growth     a repeat-sales index (Bailey-Muth-Nourse, Case-Shiller weights) on every standard Land Registry sale since
             1995, in years ending August. Doncaster's index is fitted on all pairs; each neighbourhood's deviation from
             it is fitted on its own pairs with a random-walk penalty (lambda chosen by 5-fold cross-validation on held-out
             pairs), so thin years borrow from the years around them rather than jumping about. 80% ranges for growth
             from 200 bootstrap resamples of each neighbourhood's pairs.
  stock      Census 2021 tenure (TS054), homes-weighted LSOA figures for flood risk, EPC below C, deprivation and crime
             (from the map's LSOA data), council tax band A share, distance to a station
Outputs: outputs/dash2/neighbourhoods.json, outputs/dash2/nbhd_index.csv, outputs/areas_v9.json (checks)"""
import json, pathlib, numpy as np, pandas as pd
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; D = ROOT / "outputs/dash2"; OUT = ROOT / "outputs"
LA, NAME = "E08000017", "Doncaster"
rng = np.random.default_rng(9)

# ---------------- lookups ----------------
pc = pd.read_csv(RAW / "postcodes.csv", dtype=str)
LM = json.load(open(D / "lsoa_map.json")); lsoas = [r["lsoa21"] for r in LM]
nm = pd.read_csv(RAW / "msoanames/MSOA-Names-2.2.csv", encoding="utf-8-sig", dtype=str)
nm = nm[nm.localauthorityname == "Doncaster"].set_index("msoa21cd").msoa21hclnm
l2m = pc[pc.lsoa21.isin(lsoas)].groupby("lsoa21").msoa21.agg(lambda x: x.mode()[0])
assert set(l2m.index) == set(lsoas) and set(l2m) == set(nm.index), "every map LSOA sits in a named Doncaster MSOA"
MS = sorted(nm.index)

# ---------------- repeat-sales pairs ----------------
cols = ["price_paid", "deed_date", "postcode", "property_type", "new_build", "saon", "paon", "street", "transaction_category"]
p = pd.concat([pd.read_csv(RAW / f, usecols=cols, dtype=str, keep_default_na=False) for f in ("ppd_doncaster_1995_2014.csv", "ppd_doncaster.csv")])
p = p[(p.transaction_category == "A") & p.property_type.isin(list("DSTF"))].copy()
p["price"] = p.price_paid.astype(float); p["date"] = pd.to_datetime(p.deed_date)
p["postcode"] = p.postcode.str.upper().str.strip()
p["key"] = p.postcode + "|" + p.paon.str.upper().str.strip() + "|" + p.saon.str.upper().str.strip() + "|" + p.street.str.upper().str.strip()
p = p.merge(pc[["postcode", "msoa21"]], on="postcode", how="inner"); p = p[p.msoa21.isin(MS)]
p = p.sort_values(["key", "date"]).drop_duplicates(["key", "date"])
p["per"] = p.date.dt.year + (p.date.dt.month >= 9).astype(int)          # years ending August: Sep 2025 - Aug 2026 = 2026
LAST = int(p.per.max()); assert p[p.per == LAST].date.max() >= pd.Timestamp(f"{LAST}-08-01"), "latest year is complete"
g = p.groupby("key")
for c in ("price", "date", "per", "new_build", "property_type"): p["prev_" + c] = g[c].shift()
pr = p[p.prev_price.notna()].copy()
pr = pr[(pr.prev_new_build != "Y") & (pr.prev_property_type == pr.property_type) & ((pr.date - pr.prev_date).dt.days >= 183) & (pr.per > pr.prev_per)]
pr["r"] = np.log(pr.price / pr.prev_price); pr["gap"] = (pr.date - pr.prev_date).dt.days / 365.25
pr["t1"] = pr.prev_per.astype(int); pr["t2"] = pr.per.astype(int)
YEARS = list(range(int(p.per.min()), LAST + 1)); T = len(YEARS); yi = {y: i for i, y in enumerate(YEARS)}
print(f"standard sales {len(p):,}, repeat pairs {len(pr):,}, years {YEARS[0]}-{LAST}")

def design(d):
    X = np.zeros((len(d), T)); i = np.arange(len(d))
    X[i, d.t2.map(yi).values] += 1; X[i, d.t1.map(yi).values] -= 1
    return X[:, :-1]                                                    # the latest year is the base (0)

def bmn(d, w=None):
    X = design(d); w = np.ones(len(d)) if w is None else w
    b = np.linalg.solve(X.T @ (X * w[:, None]) + 1e-9 * np.eye(T - 1), X.T @ (w * d.r.values))
    return np.append(b, 0.0)

# stage 1: OLS, trim the 1% tails of residuals (refurbishments, odd records); stage 2: variance grows with the gap
b0 = bmn(pr); e = pr.r.values - (b0[pr.t2.map(yi)] - b0[pr.t1.map(yi)])
lo, hi = np.quantile(e, [.01, .99]); keep = (e > lo) & (e < hi); pr = pr[keep].copy(); e = e[keep]
A = np.c_[np.ones(len(pr)), pr.gap.values]; a, bb = np.linalg.lstsq(A, e ** 2, rcond=None)[0]
pr["w"] = 1 / np.clip(a + bb * pr.gap.values, 0.005, None)
print(f"pairs after trimming {len(pr):,}; error variance = {a:.4f} + {bb:.4f} x years apart")
Dx = bmn(pr, pr.w.values)

P = np.diff(np.eye(T), axis=0)                                           # first differences of all T years
def deviation(d, Dvec, lam):
    X = design(d); w = d.w.values; y = d.r.values - (Dvec[d.t2.map(yi)] - Dvec[d.t1.map(yi)])
    Pr = P[:, :-1]                                                       # base year pinned at 0
    b = np.linalg.solve(X.T @ (X * w[:, None]) + lam * Pr.T @ Pr + 1e-9 * np.eye(T - 1), X.T @ (w * y))
    return np.append(b, 0.0)

# lambda by 5-fold CV on held-out pairs (Doncaster's index refitted inside each fold)
fold = rng.integers(0, 5, len(pr)); LAMS = [3, 10, 30, 100, 300, 1000, 3000, 1e9]; cv = {}
for lam in LAMS:
    se = 0.0; ws = 0.0
    for k in range(5):
        tr, te = pr[fold != k], pr[fold == k]; Dk = bmn(tr, tr.w.values)
        for m in MS:
            a_, b_ = tr[tr.msoa21 == m], te[te.msoa21 == m]
            if not len(b_): continue
            dm = deviation(a_, Dk, lam) if len(a_) else np.zeros(T); L = Dk + dm
            res = b_.r.values - (L[b_.t2.map(yi)] - L[b_.t1.map(yi)]); se += np.sum(b_.w.values * res ** 2); ws += b_.w.sum()
    cv[lam] = se / ws
LAM = min(cv, key=cv.get)
print("CV weighted MSE by lambda:", {k: round(v, 5) for k, v in cv.items()}, "-> lambda", LAM)

idx = {m: Dx + deviation(pr[pr.msoa21 == m], Dx, LAM) for m in MS}; idx[LA] = Dx
def growth(L, n): return float(np.exp((L[-1] - L[-1 - n]) / n) - 1)
boot = {}
for m in MS:
    d = pr[pr.msoa21 == m]; gs = []
    for _ in range(200):
        s = d.iloc[rng.integers(0, len(d), len(d))]; L = Dx + deviation(s, Dx, LAM); gs.append([growth(L, 5), growth(L, 10)])
    boot[m] = np.quantile(np.array(gs), [.1, .9], axis=0)
gsD = []
for _ in range(200):
    s = pr.iloc[rng.integers(0, len(pr), len(pr))]; L = bmn(s, s.w.values); gsD.append([growth(L, 5), growth(L, 10)])
boot[LA] = np.quantile(np.array(gsD), [.1, .9], axis=0)

# ---------------- checks against the official UK HPI and the model's own index ----------------
hpi = pd.read_csv(RAW / "ukhpi/UK-HPI-full-file-2026-07.csv", usecols=["Date", "AreaCode", "Index"]); hpi = hpi[hpi.AreaCode == LA].copy()
hpi["date"] = pd.to_datetime(hpi.Date, dayfirst=True); hpi["per"] = hpi.date.dt.year + (hpi.date.dt.month >= 9).astype(int)
hy = hpi.groupby("per").Index.apply(lambda v: np.log(v).mean())
mi = pd.read_csv(D / "price_index.csv"); mi["date"] = pd.to_datetime(mi.month); mi["per"] = mi.date.dt.year + (mi.date.dt.month >= 9).astype(int)
my = mi.groupby("per").index_raw.apply(lambda v: np.log(v).mean())
ours = pd.Series(Dx, index=YEARS); common = [y for y in YEARS[1:] if y in hy.index and y - 1 in hy.index and y < LAST]
ch = pd.DataFrame({"repeat_sales": ours.diff(), "ukhpi": hy.diff(), "model_index": my.diff()}).loc[common]
check = dict(lambda_cv={str(k): v for k, v in cv.items()}, lambda_used=LAM, pairs=len(pr), years=[YEARS[0], LAST],
             annual_change_corr_ukhpi=float(ch.repeat_sales.corr(ch.ukhpi)), annual_change_corr_model=float(ch.repeat_sales.corr(ch.model_index)),
             mean_abs_gap_vs_ukhpi_pts=float(100 * (ch.repeat_sales - ch.ukhpi).abs().mean()),
             growth_10y=dict(repeat_sales=growth(Dx, 10), ukhpi_to_2025=float(np.exp((hy[LAST - 1] - hy[LAST - 11]) / 10) - 1),
                             repeat_sales_to_2025=float(np.exp((ours[LAST - 1] - ours[LAST - 11]) / 10) - 1), model_index=float(np.exp((my[LAST] - my[LAST - 10]) / 10) - 1)))
print(json.dumps(check, indent=1))

# ---------------- last 3 years of sales ----------------
s = pd.read_parquet(ROOT / "data/processed/model_frame_v7.parquet", columns=["price", "sale_date", "property_type", "new_build", "floor_area", "msoa21", "lsoa21"])
END = p.date.max(); s = s[s.sale_date > END - pd.DateOffset(years=3)]
q3 = p[p.date > END - pd.DateOffset(years=3)][["price", "date", "property_type", "new_build", "msoa21"]]      # all standard sales
print("3-year window", q3.date.min().date(), "to", END.date(), f"{len(q3):,} standard sales; {len(s):,} in the model's cleaned sales ({s.floor_area.notna().sum():,} with floor area)")
rent = pd.read_csv(RAW / "pipr_doncaster.csv", parse_dates=["Time period"]).sort_values("Time period").iloc[-1]
RENT = {"D": float(rent["Rental price detached"]), "S": float(rent["Rental price semidetached"]), "T": float(rent["Rental price terraced"]), "F": float(rent["Rental price flat maisonette"])}
print("ONS rents", rent["Time period"].date(), RENT)

voa = pd.read_csv(RAW / "voa/CTSOP1.1/CTSOP1.1/CTSOP1_1_2025_03_31.csv", encoding="utf-8-sig", dtype=str)
voa = voa[voa.ecode.isin(lsoas)].set_index("ecode")
homes = pd.to_numeric(voa.all_properties, errors="coerce"); band_a = pd.to_numeric(voa.band_a, errors="coerce").fillna(0)   # ".." / "-" = suppressed or none
cen = pd.read_csv(RAW / "census/ts054_tenure_lsoa.csv").pivot(index="GEOGRAPHY_CODE", columns="C2021_TENURE_9_NAME", values="OBS_VALUE")
lsd = pd.DataFrame(LM).set_index("lsoa21")
for c in ("flood_pct", "epc_below_c_pct", "imd_score", "dist_rail_km"): lsd[c] = pd.to_numeric(lsd[c], errors="coerce")
crime = pd.read_csv(D / "postcodes.csv", dtype=str).groupby("lsoa21").imd_crime.first().astype(float)
lsd["crime"] = crime.reindex(lsd.index); lsd["homes"] = homes.reindex(lsd.index); lsd["band_a"] = band_a.reindex(lsd.index); lsd["msoa21"] = l2m.reindex(lsd.index)
pcm = pc[pc.msoa21.isin(MS) & (pc.terminated.fillna("0") == "0")].copy(); pcm["sector"] = pcm.postcode.str[:-2]

def wavg(d, c):
    k = d[c].notna() & d.homes.notna(); return float(np.average(d.loc[k, c], weights=d.loc[k, "homes"])) if k.any() else None

def stats(code, ss, ms, ls, pcs):   # ss: all standard sales, ms: the model's cleaned sales (floor area)
    r = dict(msoa21=code)
    r["sales_3y"] = int(len(ss)); r["sales_per_year"] = round(len(ss) / 3, 1); r["median_price"] = int(ss.price.median())
    fa = ms[ms.floor_area.notna()]
    r["price_per_m2"] = int(np.exp(np.median(np.log(fa.price / fa.floor_area)))) if len(fa) >= 10 else None
    r["floor_area"] = int(round(fa.floor_area.median())) if len(fa) >= 10 else None
    r["new_build_pct"] = round(100 * (ss.new_build == "Y").mean(), 1)
    sh, yl = {}, {}
    for t in "DSTF":
        st = ss[ss.property_type == t]; r[f"n_{t}"] = int(len(st)); r[f"share_{t}"] = round(100 * len(st) / len(ss), 1)
        r[f"median_{t}"] = int(st.price.median()) if len(st) >= 5 else None
        r[f"yield_{t}"] = round(1200 * RENT[t] / r[f"median_{t}"], 2) if r[f"median_{t}"] else None
        if r[f"yield_{t}"]: sh[t] = len(st); yl[t] = r[f"yield_{t}"]
    r["yield_all"] = round(sum(sh[t] * yl[t] for t in sh) / sum(sh.values()), 2) if sh else None
    r["homes"] = int(ls.homes.sum()); r["turnover_pct"] = round(100 * r["sales_per_year"] / r["homes"], 2)
    r["band_a_pct"] = round(100 * ls.band_a.sum() / ls.homes.sum(), 1)
    c = cen.reindex(ls.index).sum()
    r["private_rented_pct"] = round(100 * c["Private rented"] / c["Total: All households"], 1); r["social_rented_pct"] = round(100 * c["Social rented"] / c["Total: All households"], 1)
    r["owned_outright_pct"] = round(100 * c["Owned: Owns outright"] / c["Total: All households"], 1)
    for c_, k in (("flood_pct", "flood_pct"), ("epc_below_c_pct", "epc_below_c_pct"), ("imd_score", "imd_score"), ("crime", "crime_score"), ("dist_rail_km", "dist_rail_km")):
        v = wavg(ls, c_); r[k] = round(v, 2 if k == "crime_score" else 1) if v is not None else None
    L = idx[code]; r["growth_1y"] = round(100 * (np.exp(L[-1] - L[-2]) - 1), 1)
    for n in (5, 10, 20): r[f"growth_{n}y"] = round(100 * growth(L, n), 2)
    r["growth_5y_lo"], r["growth_10y_lo"] = [round(100 * v, 2) for v in boot[code][0]]; r["growth_5y_hi"], r["growth_10y_hi"] = [round(100 * v, 2) for v in boot[code][1]]
    yrs = np.array(YEARS); pk = int(np.argmax(np.where((yrs >= 2005) & (yrs <= 2010), L, -np.inf)))
    tr_ = pk + int(np.argmin(L[pk:np.searchsorted(yrs, 2015) + 1]))
    r["peak_year"] = int(yrs[pk]); r["trough_year"] = int(yrs[tr_]); r["peak_fall_pct"] = round(100 * (np.exp(L[tr_] - L[pk]) - 1), 1)
    back = [int(yrs[i]) for i in range(tr_, T) if L[i] >= L[pk]]; r["recovered_year"] = back[0] if back else None
    q = pr if code == LA else pr[pr.msoa21 == code]
    r["pairs"] = int(len(q)); r["pairs_10y"] = int((q.t2 > LAST - 10).sum())
    r["wards"] = "; ".join(ls.ward.value_counts().index); sc = pcs.sector.value_counts(normalize=True)
    r["sectors"] = "; ".join(sorted(sc[sc >= 0.1].index)) if code != LA else ""
    places = pd.concat([pcs.bua.dropna(), pcs.parish.dropna()]); places = places[~places.str.contains("unparished|Doncaster", case=False)]
    pv = places.value_counts(normalize=True); r["places"] = "; ".join(pv[pv >= 0.15].index[:4]) if code != LA else ""
    r["lsoas"] = " ".join(sorted(ls.index)) if code != LA else ""
    return r

rows = [dict(name=nm[m], **stats(m, q3[q3.msoa21 == m], s[s.msoa21 == m], lsd[lsd.msoa21 == m], pcm[pcm.msoa21 == m])) for m in MS]
rows.append(dict(name=NAME, **stats(LA, q3, s, lsd, pcm)))
for r in rows: r["rent_D"], r["rent_S"], r["rent_T"], r["rent_F"] = RENT["D"], RENT["S"], RENT["T"], RENT["F"]
for r in rows:   # Doncaster Council's selective licensing (rules.csv): Hexthorpe, from 1 March 2022 for up to 5 years
    r["licensing"] = "Hexthorpe selective licensing covers part of this area" if r["msoa21"] == "E02001561" else ""
    if r["msoa21"] == LA: r["wards"] = ""

# ---------------- outlines: dissolve the map's LSOA shapes into neighbourhoods ----------------
by = {}                                                                 # the map's own LSOA shapes, so outlines sit on the fills
for f in LM: by.setdefault(l2m[f["lsoa21"]], []).append(shape({"type": "MultiPolygon", "coordinates": json.loads(f["geom"])}).buffer(0))
def rnd(o): return [rnd(x) for x in o] if isinstance(o, (list, tuple)) and o and isinstance(o[0], (list, tuple)) else [round(o[0], 4), round(o[1], 4)]
for r in rows:
    if r["msoa21"] == LA: r["geom"] = ""; continue
    u = unary_union(by[r["msoa21"]]).buffer(0.00015).buffer(-0.00015).simplify(0.00005, preserve_topology=True)
    gm = mapping(u); coords = [gm["coordinates"]] if gm["type"] == "Polygon" else list(gm["coordinates"])
    r["geom"] = json.dumps(rnd(coords), separators=(",", ":")); c = u.representative_point(); r["lat"], r["lon"] = round(c.y, 4), round(c.x, 4)

json.dump(rows, open(D / "neighbourhoods.json", "w"), separators=(",", ":"))
ix = pd.DataFrame([dict(msoa21=k, year=y, index=round(100 * float(np.exp(v[i] - v[-1])), 2)) for k, v in idx.items() for i, y in enumerate(YEARS)])
ix.to_csv(D / "nbhd_index.csv", index=False)
check["rents"] = dict(month=str(rent["Time period"].date()), **RENT)
json.dump(check, open(OUT / "areas_v9.json", "w"), indent=1)
print("neighbourhoods.json", round((D / "neighbourhoods.json").stat().st_size / 1e3), "KB; nbhd_index.csv", len(ix), "rows")
df = pd.DataFrame(rows).set_index("name")
print(df[["sales_3y", "median_price", "yield_all", "growth_1y", "growth_5y", "growth_10y", "growth_10y_lo", "growth_10y_hi", "peak_fall_pct", "recovered_year", "pairs_10y", "private_rented_pct", "turnover_pct"]].sort_values("growth_10y").to_string())
