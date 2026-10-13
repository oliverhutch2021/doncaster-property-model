"""Value one Doncaster home from Python, exactly as the dashboard does.

Examples:
    python src/predict.py --postcode "DN4 0AH" --type T --address "<house number> <street>" --explain
    python src/predict.py --postcode "DN1 2EG" --type T --area 70 --prev-price 65000 --prev-month 2016-05 --condition dated
    python src/predict.py --postcode "DN4 7HA" --type S --area 85

Steps (one function each):
  1. postcode: coordinates, distance to the town centre, deprivation scores
  2. local price levels: postcode sector + type and neighbourhood (3 years); street + type and postcode (5 years)
  3. the 10 nearest recent sales of the same type, and price per m2 of the 15 nearest sales with a floor area
  4. the home itself: typed details, or its latest Energy Performance Certificate (size, age, energy, walls, loft,
     glazing, heating ...), its certificate history (why the latest one was done, lets, energy-score changes) and its
     Land Registry title plan (plot size)
  5. the last sale, adjusted to today's prices with the index (optional)
  6. the model predicts log(price / index); add the index back, plus the local correction (alpha x the model's median
     miss on the k nearest sales of the last 12 months)
  7. a confidence score: a small second model predicts the typical size of the error for this estimate, and the 80%
     range scales with it (calibrated on 2024 errors); the condition adjustment; optional SHAP explanation

Files are in model/ (gathered by src/assemble_model_dir.py from src/production_v18.py and the lookup exports). The
address lookup (model/epc_<district>.csv) carries every certificate's address, which the EPC licence doesn't let this
project republish, so it isn't in the shared copy: build it from your own EPC download with
`python pipeline.py --only lookups` and `python src/assemble_model_dir.py --with-addresses`.

Inputs are checked against the same limits as the dashboard, the postcode must be inside Doncaster, and an address must
match one home (word for word: "3 Main Street" doesn't match "103 Main Street").
tests/test_parity.py checks these features against the ones the model was trained on."""
import argparse, json, pathlib, re, numpy as np, pandas as pd, lightgbm as lgb

M = pathlib.Path(__file__).resolve().parents[1] / "model"
TYPE_CODE, FORM_DEFAULT = {"D": 0, "S": 1, "T": 2, "F": 3}, {"D": 0, "S": 1, "T": 3, "F": np.nan}
EPC_X = ["wall_type", "ceiling_m", "floor_level_n", "top_floor", "heated_rooms", "glazed_area_n", "fireplaces", "wall_insulated", "loft_mm", "glazing",
         "elec_heating", "heat_pump", "woodburner", "low_energy_light", "solar_pv"]
EPC_H = ["epc_reason", "epc_tenure_n", "epc_rental_5y", "epc_age_y", "epc_n", "sap_jump"]          # certificate history, as of the valuation month

def haversine_km(lat1, lon1, lat2, lon2):
    r = np.pi / 180
    a = np.sin((lat2 - lat1) * r / 2) ** 2 + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin((lon2 - lon1) * r / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))

def load():
    meta = {r["key"]: r["value"] for r in json.load(open(M / "model_meta.json"))}
    meta = {k: (json.loads(v) if k in ("features", "bands", "conformal", "groups", "conf_features", "conf_levels") else v) for k, v in meta.items()}
    conf = lgb.Booster(model_file=str(M / "confidence_v8.txt")) if (M / "confidence_v8.txt").exists() and "conf_features" in meta else None
    return dict(booster=lgb.Booster(model_file=str(M / "doncaster_lgbm_v7.txt")), conf=conf, meta=meta,
                postcodes=pd.read_csv(M / "postcodes.csv").set_index("postcode"), levels=pd.read_csv(M / "levels.csv"),
                comps=pd.read_csv(M / "comps.csv"), index=pd.read_csv(M / "price_index.csv").set_index("month").index_raw,
                condition=pd.read_csv(M / "condition.csv").set_index("condition"), streets=pd.read_csv(M / "street_levels.csv", keep_default_na=False))

# the dashboard's limits (outputs/dash2/app.js, LIMITS); an input outside them is refused, not used
LIMITS = dict(area=(10, 1500, "floor area (m2)"), rooms=(1, 30, "bedrooms and living rooms"), plot=(0, 1_000_000, "plot size (m2)"),
              prev_price=(1000, 20_000_000, "last sale price"), rating=(1, 100, "EPC score"), age=(1600, 2030, "build year"), form=(0, 5, "built form"))

def check_inputs(a, d):
    """Refuse what the model can't value, the way the dashboard does. Returns a list of problems (empty if none)."""
    bad = []
    for k, (lo, hi, name) in LIMITS.items():
        v = getattr(a, k, None)
        if v is not None and not (lo <= v <= hi): bad.append(f"{name} must be between {lo:,} and {hi:,} (got {v:g})")
    if a.rooms is not None and float(a.rooms) != int(a.rooms): bad.append("bedrooms and living rooms must be a whole number")
    if a.prev_price is not None or a.prev_month is not None:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", str(a.prev_month or ""))
        if a.prev_price is None or not m: bad.append("give the last sale's price and its month as YYYY-MM")
        else:
            a.prev_month = f"{m.group(1)}-{int(m.group(2)):02d}"
            if a.prev_month not in d["index"].index: bad.append(f"the last sale month must be between {d['index'].index.min()} and {d['index'].index.max()}")
    return bad

def find_epc(postcode, text):
    """The certificate for the one home at this postcode whose address contains `text` as whole words (case-insensitive).
    Raises SystemExit if no lookup is built, or if the text fits no home or more than one."""
    f = M / f"epc_{postcode.split(' ')[0]}.csv"
    if not f.exists():
        raise SystemExit(f"No address lookup for {postcode.split(' ')[0]} in model/: it isn't shared (EPC address licence). Build it from your own "
                         "EPC download (python pipeline.py --only lookups; python src/assemble_model_dir.py --with-addresses), or give the details instead.")
    e = pd.read_csv(f); e = e[e.postcode == postcode]
    norm = lambda x: " ".join(str(x).upper().replace(",", " ").split())           # "12, Main Street" and "12 Main Street" alike
    q, addr = norm(text), e.address.map(norm)
    hit = e[addr.str.contains(r"(?<![A-Z0-9])" + re.escape(q) + r"(?![A-Z0-9])", regex=True)]
    if len(hit) > 1:
        starts = hit[addr[hit.index].str.startswith(q)]
        if len(starts) == 1: return starts.iloc[0].to_dict()
        raise SystemExit(f"'{text}' fits {len(hit)} homes at {postcode}: " + "; ".join(hit.address.head(8)) + (" ..." if len(hit) > 8 else "") + ". Give more of the address.")
    if not len(hit):
        raise SystemExit(f"No home at {postcode} matches '{text}'. Addresses there: " + "; ".join(e.address.head(8)) + (" ..." if len(e) > 8 else "")
                         + ". Or leave out --address and give the details.")
    return hit.iloc[0].to_dict()

def last_sale(epc, before=None):
    """The home's last Land Registry sale from its lookup row ("date|price|Y or N for new build", ';'-separated), or the
    last one before a date (YYYY-MM-DD). None if there isn't one."""
    s = epc.get("sales") if epc else None
    if not isinstance(s, str) or not s: return None
    rows = sorted(x.split("|") for x in s.split(";") if x)
    if before is not None: rows = [r for r in rows if r[0] < before]
    if not rows: return None
    r = rows[-1]; return dict(price=float(r[1]), month=r[0][:7], new_build=len(r) > 2 and r[2] == "Y")

def local_levels(d, postcode, ptype, lsoa):
    lv = d["levels"]; st = lv[(lv.kind == "sector_type") & (lv.key == f"{postcode[:-2]}|{ptype}")]; ls = lv[(lv.kind == "lsoa") & (lv.key == lsoa)]
    n = int(st.n.iloc[0]) if len(st) else 0
    return (float(st.level.iloc[0]) if n >= 5 else np.nan), (float(ls.level.iloc[0]) if len(ls) else np.nan), n

def street_levels(d, postcode, ptype, epc):
    s = d["streets"][d["streets"].postcode == postcode]
    pc = s[s.type == "*"]; st = s[s.type != "*"]; names = sorted(set(st.street) - {""})
    pick = None
    if epc is not None:
        hits = [n for n in names if n in str(epc.get("address", "")).upper()]
        pick = max(hits, key=len) if hits else None
    if pick is None and len(names) == 1: pick = names[0]
    if pick is None and names: pick = st.groupby("street").n.sum().reindex(names).idxmax()
    sv = st[(st.street == pick) & (st.type == ptype)] if pick else st.iloc[0:0]
    num = lambda v: float(v) if v not in ("", None) else np.nan
    return dict(lvl_street_type=num(sv.level.iloc[0]) if len(sv) and int(sv.n.iloc[0]) >= 2 else np.nan, n_street_type=int(sv.n.iloc[0]) if len(sv) else 0,
                lvl_postcode=num(pc.level.iloc[0]) if len(pc) and int(pc.n.iloc[0]) >= 2 else np.nan, n_postcode=int(pc.n.iloc[0]) if len(pc) else 0)

def neighbours(d, lat, lon, ptype):
    c = d["comps"]; dist = haversine_km(lat, lon, c.lat.values, c.lon.values)
    same = np.argsort(np.where(c.type.values == ptype, dist, np.inf))[:10]; same = same[c.type.values[same] == ptype]
    has_area = c.floor_area.notna().values & (c.floor_area.values > 0)
    area = np.argsort(np.where(has_area, dist, np.inf))[:15]; area = area[has_area[area]]
    return dict(knn_lvl=float(np.median(c.y_defl.values[same])) if len(same) >= 3 else np.nan, knn_dist=float(dist[same].mean()) if len(same) >= 3 else np.nan,
                knn_ppsqm=float(np.median(c.y_defl.values[area] - np.log(c.floor_area.values[area]))) if len(area) >= 5 else np.nan)

def features(d, a, epc=None):
    meta, pc = d["meta"], d["postcodes"].loc[a.postcode]
    e = epc or {}
    def pick(typed, key):
        if typed is not None: return float(typed)
        v = e.get(key); return float(v) if v is not None and v != "" and pd.notna(v) else np.nan
    lvl_st, lvl_l, n_st = local_levels(d, a.postcode, a.type, pc.lsoa21)
    prev_defl = years = np.nan
    if a.prev_price and a.prev_month:
        prev_defl = np.log(a.prev_price) - np.log(d["index"][a.prev_month])          # checked to be in the index (check_inputs)
        years = (pd.Timestamp(meta["valuation_month"]) - pd.Timestamp(a.prev_month)).days / 365.25
    sap, sap_pot = pick(a.rating, "sap_current"), pick(None, "sap_potential")
    plot = dict(plot_m2=a.plot, plot_epc_homes=1.0, plot_uprns=np.nan, plot_m2_per_home=a.plot) if a.plot else {k: pick(None, k) for k in ["plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home"]}
    form = float(a.form) if a.form is not None else pick(None, "built_form_code")
    feat = dict(lat=pc.lat, lon=pc.lon, dist_centre_km=pc.dist_centre_km, **{k: pc[k] for k in ["imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime", "imd_barriers", "imd_living_env"]},
                lvl_sector_type=lvl_st, lvl_lsoa=lvl_l, n_sector_type=n_st, property_type=TYPE_CODE[a.type], tenure=1 if a.tenure == "L" else 0, new_build=int(a.new_build),
                floor_area=pick(a.area, "floor_area"), rooms=pick(a.rooms, "rooms"), age_year=pick(a.age, "age_year"),
                bungalow=1 if (a.bungalow or e.get("epc_type") == "Bungalow") else 0, built_form_code=form if np.isfinite(form) else FORM_DEFAULT[a.type],
                extensions=pick(None, "extensions"), sap_current=sap, sap_potential=sap_pot, sap_gap=sap_pot - sap, mains_gas={"Y": 1.0, "N": 0.0}.get(e.get("mains_gas"), np.nan),
                **neighbours(d, pc.lat, pc.lon, a.type), prev_defl=prev_defl, years_since_prev=years, prev_nb=(1.0 if getattr(a, "prev_new_build", False) else 0.0) if np.isfinite(prev_defl) else np.nan,
                **plot, **street_levels(d, a.postcode, a.type, epc), **{k: pick(None, k) for k in EPC_X + EPC_H})
    return pc, feat

def condition_effect(d, a):
    """The condition adjustment (%) for this estimate and which calibration it comes from, as the dashboard does
    (src/condition_calibration.py): without a last sale, the calibration on a model without last-sale features; with
    one, the full model's purchase discount for a worse condition, and its resale premium for a better one when the last
    sale was within 18 months (a quick resale already shows most of the works). Works since an older last sale the
    model can't see and the data can't measure, so that case keeps the no-last-sale premium."""
    r = d["condition"].loc[a.condition]; base = float(r.adjustment_pct); prev = r.get("adjustment_prev_pct", np.nan)
    if not (a.prev_price and a.prev_month) or base == 0 or pd.isna(prev): return base, "no last sale"
    if base < 0: return float(prev), "last sale known"
    months = (pd.Timestamp(d["meta"]["valuation_month"]) - pd.Timestamp(a.prev_month)).days / 30.44
    return (float(prev), "recent last sale") if months <= 18 else (base, "older last sale (not measured separately)")

def value(d, a, epc=None, explain=False):
    meta = d["meta"]; pc, feat = features(d, a, epc)
    x = pd.DataFrame([[feat[f] for f in meta["features"]]], columns=meta["features"], dtype=float)
    c = d["comps"][d["comps"].resid.notna()]; k, alpha = int(meta["local_k"]), float(meta["local_alpha"])
    near = np.argsort(haversine_km(pc.lat, pc.lon, c.lat.values, c.lon.values))[:k]
    local, spread = 0.0, np.nan
    if len(c) >= k:
        rs = c.resid.values[near]; md = float(np.median(rs)); local = alpha * md; spread = float(np.median(np.abs(rs - md)))
    est = float(np.exp(d["booster"].predict(x)[0] + np.log(float(meta["index_latest"])) + local))
    band = int(np.searchsorted(meta["bands"], est, side="right")); lo, hi = meta["conformal"][band + (5 if np.isfinite(feat["prev_defl"]) else 0)]
    sigma, level = np.nan, None
    if d["conf"] is not None:
        cx = dict(feat, pred_log=np.log(est), corr_abs=abs(local), local_spread=spread)
        sigma = float(d["conf"].predict(pd.DataFrame([[cx[f] for f in meta["conf_features"]]], columns=meta["conf_features"], dtype=float))[0])
        typed = epc is None and "conf_typed_scale" in meta          # typed in by hand: rescaled (src/model_v8_typed.py)
        if typed: sigma *= float(meta["conf_typed_scale"])
        level = next((n for h, n in meta["conf_levels"] if sigma < h), meta["conf_levels"][-1][1])
        q10, q90 = (float(meta["conf_typed_q10"]), float(meta["conf_typed_q90"])) if typed else (float(meta["conf_q10"]), float(meta["conf_q90"]))
        if meta.get("conf_adaptive") == "true": lo, hi = sigma * q10, sigma * q90
    adj_pct, cond_basis = condition_effect(d, a); adj = adj_pct / 100
    out = dict(estimate=est, low=est * np.exp(lo), high=est * np.exp(hi), local_pct=100 * (np.exp(local) - 1), with_condition=est * (1 + adj), features=feat,
               typical_error_pct=100 * (np.exp(sigma) - 1) if np.isfinite(sigma) else np.nan, confidence=level, condition_pct=adj_pct, condition_basis=cond_basis)
    if explain:
        phi = d["booster"].predict(x, pred_contrib=True)[0]; fi = {f: i for i, f in enumerate(meta["features"])}
        out["base"] = float(np.exp(phi[-1] + np.log(float(meta["index_latest"]))))
        out["groups"] = sorted(((g, 100 * (np.exp(sum(phi[fi[f]] for f in fs)) - 1)) for g, fs in meta["groups"].items()), key=lambda t: -abs(t[1]))
    return out

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--postcode", required=True); p.add_argument("--type", choices=list("DSTF"), required=True)
    p.add_argument("--address", help="part of the address text, to pull the home's EPC and plot (e.g. '12 Ellers')")
    p.add_argument("--tenure", choices=["F", "L"], default="F"); p.add_argument("--new-build", action="store_true"); p.add_argument("--bungalow", action="store_true")
    p.add_argument("--area", type=float, help="floor area in m2"); p.add_argument("--rooms", type=float); p.add_argument("--age", type=float, help="build year, e.g. 1939.5")
    p.add_argument("--form", type=int, help="0 detached, 1 semi, 2 end-terrace, 3 mid-terrace"); p.add_argument("--rating", type=float, help="EPC score 1-100")
    p.add_argument("--plot", type=float, help="plot size in m2"); p.add_argument("--prev-price", type=float); p.add_argument("--prev-month", help="YYYY-MM")
    p.add_argument("--prev-new-build", action="store_true", help="the last sale was of the home as a new build")
    p.add_argument("--condition", default="average", choices=["needs_full_renovation", "dated", "average", "good", "recently_refurbished"])
    p.add_argument("--explain", action="store_true", help="show what moved the estimate (SHAP)")
    a = p.parse_args(); a.postcode = a.postcode.upper().replace(" ", ""); a.postcode = a.postcode[:-3] + " " + a.postcode[-3:]
    d = load()
    if a.postcode not in d["postcodes"].index: raise SystemExit(f"{a.postcode} is not in the Doncaster postcode list")
    if str(d["postcodes"].loc[a.postcode].get("in_doncaster", "1")) in ("0", "0.0"):
        raise SystemExit(f"{a.postcode} is outside Doncaster ({d['postcodes'].loc[a.postcode].ward} ward), so the model can't value it")
    epc = find_epc(a.postcode, a.address) if a.address else None
    if epc: print("EPC:", epc["address"])
    ls = last_sale(epc) if epc and not a.prev_price else None          # the home's own last Land Registry sale
    if ls:
        a.prev_price, a.prev_month, a.prev_new_build = ls["price"], ls["month"], ls["new_build"]
        print(f"Last sale from Land Registry: £{int(a.prev_price):,} in {a.prev_month}{' (new build)' if a.prev_new_build else ''}")
    problems = check_inputs(a, d)
    if problems: raise SystemExit("Can't value this: " + "; ".join(problems) + ".")
    r = value(d, a, epc, a.explain)
    print(f"Estimate {r['estimate']:,.0f}  (80% range {r['low']:,.0f} to {r['high']:,.0f}; local correction {r['local_pct']:+.1f}%)")
    if r["confidence"]: print(f"Confidence: {r['confidence']} (typical error for a home like this about ±{r['typical_error_pct']:.0f}%)")
    if a.condition != "average": print(f"If {a.condition.replace('_', ' ')}: {r['with_condition']:,.0f} ({r['condition_pct']:+.1f}%, calibration: {r['condition_basis']})")
    if a.explain:
        print(f"Starts from {r['base']:,.0f} (typical Doncaster sale today)")
        for g, v in r["groups"]: print(f"  {g:38s} {v:+.1f}%")
