"""Fit and test a new-let rent model for Doncaster on the asking rents pulled by src/fetch_rents.py.

The question it answers: given what the valuation model says a home is worth, its type and its bedrooms, what do
homes like it list for today? Fitted on every live listing in the borough, tested by leaving each postcode district
out in turn, and compared with ONS's average of rents being paid (the dashboard's current basis).

  log(asking rent) = a[type] + b x log(local value) + c[bedrooms]

local value = the sale price level of the listing's neighbourhood for its type (£/m2 from 2024+ sales in its LSOA,
falling back to its MSOA and then the borough) x the typical floor area of that type and bedroom count (from EPCs).
It stands in for the valuation model's estimate, which the listings don't carry.

Outputs (private, git-ignored): outputs/private/rent_fit.csv (coefficients, errors, the asking-to-paid premium by
type) and outputs/private/rent_fit_log.txt (the full fit report).
  python src/rent_fit.py                 fit on data/private/rents/listings_all.csv
  python src/rent_fit.py --synthetic     fit on listings simulated from a known formula, to check the fit recovers it
"""
import argparse, csv, datetime as dt, io, json, pathlib, sys
import numpy as np, pandas as pd
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parents[1]
LISTINGS = ROOT / "data/private/rents/listings_all.csv"; OUT = ROOT / "outputs/private"
TYPE = {"flat": "F", "terraced_house": "T", "semi-detached_house": "S", "detached_house": "D"}
T4 = {"D": "detached", "S": "semidetached", "T": "terraced", "F": "flat maisonette"}
BUILT = {"Detached": "D", "Semi-Detached": "S", "Mid-Terrace": "T", "End-Terrace": "T", "Enclosed Mid-Terrace": "T", "Enclosed End-Terrace": "T"}
RENT_OK = (250, 3000); BEDS_OK = (1, 5); MAX_KM = 1.0
ROOMS_TO_BEDS = {1: 1, 2: 1, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4, 8: 5, 9: 5, 10: 5, 11: 5, 12: 5}


def log(lines, *a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)


def postcodes():
    pc = pd.read_csv(ROOT / "data/raw/postcodes.csv", dtype=str, usecols=["postcode", "latitude", "longitude", "lsoa21", "msoa21"]).dropna()
    pc["lat"] = pc.latitude.astype(float); pc["lon"] = pc.longitude.astype(float)
    return pc


def price_levels():
    """Median log £/m2 by LSOA x type, MSOA x type and borough x type, from 2024+ sales in the model frame."""
    mf = pd.read_parquet(ROOT / "data/processed/model_frame_v7.parquet", columns=["postcode", "sale_date", "price", "property_type", "floor_area"])
    mf = mf[(mf.sale_date >= "2024-01-01") & mf.floor_area.between(25, 400)].merge(postcodes()[["postcode", "lsoa21", "msoa21"]], on="postcode", how="left")
    mf["lpp"] = np.log(mf.price / mf.floor_area)
    lsoa = mf.groupby(["lsoa21", "property_type"]).lpp.agg(["median", "size"]); lsoa = lsoa[lsoa["size"] >= 3]["median"]
    msoa = mf.groupby(["msoa21", "property_type"]).lpp.agg(["median", "size"]); msoa = msoa[msoa["size"] >= 5]["median"]
    la = mf.groupby("property_type").lpp.median()
    return lsoa, msoa, la


def typical_area():
    """Typical floor area by type and bedrooms from Doncaster EPCs. EPCs count habitable rooms (bedrooms plus living
    and dining rooms), not bedrooms; the usual home has one or two of those, so rooms map to bedrooms as ROOMS_TO_BEDS."""
    e = pd.read_csv(ROOT / "data/raw/epc_doncaster.csv", dtype=str, usecols=["property_type", "built_form", "total_floor_area", "number_habitable_rooms", "tenure", "postcode"])
    e["area"] = pd.to_numeric(e.total_floor_area, errors="coerce"); e["rooms"] = pd.to_numeric(e.number_habitable_rooms, errors="coerce")
    e["t"] = np.where(e.property_type.isin(["Flat", "Maisonette"]), "F", e.built_form.map(BUILT))
    e = e[e.t.notna() & e.area.between(20, 400) & e.rooms.between(1, 12)]
    e["beds"] = e.rooms.map(ROOMS_TO_BEDS).fillna(5).astype(int)
    area = e.groupby(["t", "beds"]).area.median()
    return area, e


def locate(df, pc):
    """Nearest Doncaster postcode centroid to each listing; drops listings more than MAX_KM from any."""
    R = 6371.0
    def xyz(lat, lon):
        la, lo = np.radians(lat), np.radians(lon); return np.c_[np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)] * R
    tree = cKDTree(xyz(pc.lat.values, pc.lon.values))
    d, i = tree.query(xyz(df.lat.values, df.lng.values))
    df = df.assign(km=d, postcode=pc.postcode.values[i], lsoa21=pc.lsoa21.values[i], msoa21=pc.msoa21.values[i])
    return df[df.km <= MAX_KM].copy(), int((d > MAX_KM).sum())


def prepare(listings, lines):
    df = listings.copy()
    df = df[(df.query_beds.fillna("").astype(str) == "") & (df.query_type.fillna("").astype(str) == "")]      # unfiltered calls: each listing once per pull
    df["t"] = df["type"].map(TYPE); df["beds"] = pd.to_numeric(df.bedrooms, errors="coerce"); df["rent"] = pd.to_numeric(df.price_pcm, errors="coerce")
    df["lat"] = pd.to_numeric(df.lat, errors="coerce"); df["lng"] = pd.to_numeric(df.lng, errors="coerce")
    n0 = len(df)
    df = df.dropna(subset=["t", "beds", "rent", "lat", "lng"])
    df = df[df.rent.between(*RENT_OK) & df.beds.between(*BEDS_OK)]
    df = df.drop_duplicates(["lat", "lng", "beds", "t", "rent"])                      # the same listing seen in several pulls counts once
    df["beds"] = df.beds.astype(int)
    log(lines, f"listings: {n0} rows -> {len(df)} distinct, usable (type, bedrooms, rent £{RENT_OK[0]}-{RENT_OK[1]}, coordinates)")
    pc = postcodes(); df, far = locate(df, pc); log(lines, f"  {far} dropped as more than {MAX_KM} km from any Doncaster postcode; {len(df)} kept")
    lsoa, msoa, la = price_levels(); area, _ = typical_area()
    lv = [lsoa.get((r.lsoa21, r.t), msoa.get((r.msoa21, r.t), la.get(r.t))) for r in df.itertuples()]
    df["lpp"] = lv; df["area"] = [area.get((r.t, r.beds), np.nan) for r in df.itertuples()]
    df = df.dropna(subset=["lpp", "area"]); df["lval"] = df.lpp + np.log(df.area)
    log(lines, f"  with a local value: {len(df)}; by type: {df.t.value_counts().to_dict()}; by bedrooms: {df.beds.value_counts().sort_index().to_dict()}")
    return df


def design(df, types, beds):
    """Columns: one intercept per type, log value, bedroom dummies (2..5 against 1)."""
    X = [np.column_stack([(df.t == t).astype(float) for t in types]), df.lval.values[:, None]]
    X.append(np.column_stack([(df.beds == b).astype(float) for b in beds[1:]]))
    return np.hstack(X)


def fit(df, lines):
    types = [t for t in "FTSD" if (df.t == t).sum() >= 10]; beds = [b for b in range(1, 6) if (df.beds == b).sum() >= 10]
    d = df[df.t.isin(types) & df.beds.isin(beds)].copy(); y = np.log(d.rent.values); X = design(d, types, beds)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None); pred = X @ coef; resid = y - pred
    r2 = 1 - resid.var() / y.var(); mdape = np.median(np.abs(np.exp(resid) - 1))
    names = [f"a_{t}" for t in types] + ["b_value"] + [f"c_beds{b}" for b in beds[1:]]
    log(lines, f"\nfit on {len(d)} listings: R2 {r2:.3f}, median abs error {mdape:.1%}")
    for n, c in zip(names, coef): log(lines, f"  {n:10s} {c:+.4f}" + (f"   (x{np.exp(c):.3f})" if n.startswith(("c_", "a_")) is False else f"   (rent x{np.exp(c):.3f})" if n.startswith("c_") else ""))
    # leave one district out
    errs = {}
    for dist in sorted(d.district.unique()):
        tr, te = d[d.district != dist], d[d.district == dist]
        if len(te) < 5 or len(tr) < 50: continue
        c2, *_ = np.linalg.lstsq(design(tr, types, beds), np.log(tr.rent.values), rcond=None)
        p2 = design(te, types, beds) @ c2; errs[dist] = (np.median(np.abs(np.exp(np.log(te.rent.values) - p2) - 1)), len(te))
    if errs:
        pooled = np.median(np.concatenate([[e] * n for e, n in errs.values()])) if False else np.average([e for e, n in errs.values()], weights=[n for e, n in errs.values()])
        log(lines, f"leave one district out: weighted median abs error {pooled:.1%}; by district " + ", ".join(f"{k} {e:.1%} (n={n})" for k, (e, n) in errs.items()))
    # the alternatives it should beat: bedrooms only, and the dashboard's slope fixed at 0.596
    Xb = design(d, types, beds); Xb[:, len(types)] = 0
    cb, *_ = np.linalg.lstsq(Xb, y, rcond=None); log(lines, f"bedrooms and type only (no value): median abs error {np.median(np.abs(np.exp(y - Xb @ cb) - 1)):.1%}")
    return dict(types=types, beds=beds, coef=dict(zip(names, coef)), n=len(d), r2=r2, mdape=mdape, lodo=errs, d=d)


def premium(res, lines, asof):
    """Composition-matched comparison with ONS: the fitted asking rent for Doncaster's privately rented stock (EPC
    tenure 'rented (private)', its types, sizes and neighbourhoods) against ONS's average rent paid, by type."""
    area, e = typical_area(); pc = postcodes(); lsoa, msoa, la = price_levels()
    stock = e[e.tenure.str.lower().str.contains("private", na=False)].merge(pc[["postcode", "lsoa21", "msoa21"]], on="postcode", how="left")
    stock = stock[stock.t.isin(res["types"]) & stock.beds.isin(res["beds"])].copy()
    stock["lpp"] = [lsoa.get((r.lsoa21, r.t), msoa.get((r.msoa21, r.t), la.get(r.t))) for r in stock.itertuples()]
    stock = stock.dropna(subset=["lpp"]); stock["lval"] = stock.lpp + np.log(stock.area)
    c = res["coef"]; X = design(stock, res["types"], res["beds"]); coef = np.array([c[f"a_{t}"] for t in res["types"]] + [c["b_value"]] + [c[f"c_beds{b}"] for b in res["beds"][1:]])
    stock["asking"] = np.exp(X @ coef)
    rm = pd.read_csv(ROOT / "outputs/dash2/rent_model.csv").set_index("key")
    ons_date = rm.loc["rent_S", "source"]
    out = {}
    log(lines, f"\nasking rent of the rented stock (fitted) against ONS rent paid ({ons_date}):")
    for t in res["types"]:
        s = stock[stock.t == t]; ons = float(rm.loc[f"rent_{t}", "value"]); ask = float(np.exp(np.log(s.asking).mean()))
        out[t] = dict(n_stock=len(s), asking=ask, ons=ons, premium=ask / ons)
        log(lines, f"  {T4[t]:16s} stock n={len(s):5d}  fitted asking £{ask:,.0f}  ONS paid £{ons:,.0f}  premium x{ask / ons:.3f}")
    return out


def write(res, prem, lines, asof, source):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [("fitted_on", asof, "Date the listings were fitted", source), ("n_listings", res["n"], "Distinct listings in the fit", source),
            ("r2", round(res["r2"], 4), "Share of variation in log asking rent explained", "Same fit"),
            ("mdape", round(res["mdape"], 4), "Median absolute error of the fit (share of the rent)", "Same fit"),
            ("lodo_mdape", round(float(np.average([e for e, n in res["lodo"].values()], weights=[n for e, n in res["lodo"].values()])), 4) if res["lodo"] else "", "Same, predicting each postcode district from the others", "Leave one district out")]
    for k, v in res["coef"].items():
        rows.append((k, round(v, 4), {"b_value": "Slope of log rent on log local value"}.get(k, "Intercept for the type" if k.startswith("a_") else "Bedroom effect on log rent, against 1 bedroom"), "Same fit"))
    for t, p in prem.items():
        rows.append((f"premium_{t}", round(p["premium"], 4), f"Fitted asking rent of the rented {T4[t]} stock ÷ ONS rent paid", f"ONS PIPR Doncaster vs {source}; stock from EPC tenure, n={p['n_stock']}"))
    with open(OUT / "rent_fit.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["key", "value", "label", "source"]); w.writerows(rows)
    (OUT / "rent_fit_log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}/rent_fit.csv and rent_fit_log.txt")


def synthetic(n=1500, seed=7):
    """Listings simulated from a known formula over real Doncaster postcodes, to check the fit recovers it:
    log rent = a[type] + 0.35 log value + bedroom effects + noise (sd 0.12)."""
    rng = np.random.default_rng(seed); pc = postcodes(); area, _ = typical_area(); lsoa, msoa, la = price_levels()
    a = {"F": 2.35, "T": 2.20, "S": 2.25, "D": 2.30}; cb = {1: 0, 2: 0.18, 3: 0.32, 4: 0.50, 5: 0.65}; b = 0.35
    rows = []
    for _ in range(n):
        p = pc.iloc[rng.integers(len(pc))]; t = rng.choice(list("FTSD"), p=[.2, .4, .3, .1]); beds = int(rng.choice([1, 2, 3, 4, 5], p=[.1, .35, .4, .12, .03]))
        if t == "F" and beds > 3: beds = 2
        lpp = lsoa.get((p.lsoa21, t), msoa.get((p.msoa21, t), la.get(t))); ar = area.get((t, beds), np.nan)
        if lpp is None or np.isnan(ar): continue
        rent = np.exp(a[t] + b * (lpp + np.log(ar)) + cb[beds] + rng.normal(0, 0.12))
        rows.append(dict(pull_date="2026-11-06", district=p.postcode.split()[0], query_beds="", query_type="", price_pcm=round(rent, 2), bedrooms=beds,
                         type={v: k for k, v in TYPE.items()}[t], lat=p.lat + rng.normal(0, 0.0005), lng=p.lon + rng.normal(0, 0.0005)))
    return pd.DataFrame(rows), dict(a=a, b=b, cb=cb)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--synthetic", action="store_true"); args = ap.parse_args()
    lines = []
    if args.synthetic:
        listings, truth = synthetic(); source = "synthetic listings (test)"; log(lines, "SYNTHETIC CHECK: true b = 0.35, true bedroom effects", truth["cb"])
    else:
        if not LISTINGS.exists(): sys.exit(f"No listings at {LISTINGS}: run src/fetch_rents.py --pull first.")
        listings = pd.read_csv(LISTINGS, dtype=str); source = "PropertyData live asking rents"
    asof = dt.date.today().isoformat()
    df = prepare(listings, lines); res = fit(df, lines); prem = premium(res, lines, asof)
    if args.synthetic:
        c = res["coef"]; ok = abs(c["b_value"] - 0.35) < 0.05 and all(abs(c[f"c_beds{b}"] - truth["cb"][b]) < 0.05 for b in res["beds"][1:])
        log(lines, f"\nrecovered b = {c['b_value']:.3f} (true 0.35); bedroom effects " + ", ".join(f"{b}: {c[f'c_beds{b}']:.3f}" for b in res["beds"][1:]) + f" -> {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)
    write(res, prem, lines, asof, source)
