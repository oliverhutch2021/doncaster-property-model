"""Candidate features for version 5. Every feature uses only information available before the sale.

  exact   : OS Open UPRN coordinates (EPC-matched homes), and neighbour prices recomputed from exact positions
  plot    : HM Land Registry title polygon area, homes per title (src/plots.py)
  street  : median index-adjusted price on the same street (same type) and in the same postcode, previous 5 years
  size_nn : median price of the nearest earlier sales of the same type and similar floor area (+/-20%)
  epc_x   : more EPC fields - wall type and insulation, loft insulation, glazing, heating, fireplaces,
            wood burner, lighting, solar PV, ceiling height, floor level, glazed area
  voa     : the neighbourhood's council tax band mix and build-period mix (VOA, March 2025)
"""
import re, pathlib, numpy as np, pandas as pd, duckdb, sys
from sklearn.neighbors import BallTree
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from epc_match import load_epc
ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; P_ = ROOT / "data/processed"; R = 6371.0

s = pd.read_parquet(P_ / "model_frame_v2.parquet").sort_values(["sale_date", "unique_id"]).reset_index(drop=True)
n0 = len(s)
full = pd.read_parquet(P_ / "sales_epc.parquet")[["unique_id", "dwelling", "sale_date", "price", "property_type", "postcode", "street", "town", "floor_area"]]

# ---------- exact location + plot ----------
up = pd.read_parquet(P_ / "uprn_plots.parquet")
s["uprn"] = pd.to_numeric(s.dwelling.where(s.dwelling.astype(str).str.fullmatch(r"\d+")), errors="coerce")
s = s.merge(up, on="uprn", how="left"); assert len(s) == n0
s["xlat"] = s.ulat.fillna(s.lat); s["xlon"] = s.ulon.fillna(s.lon); s["exact_loc"] = s.ulat.notna().astype(float)
print(f"exact location: {s.exact_loc.mean():.1%} of sales; plot found: {s.plot_m2.notna().mean():.1%}")

# ---------- neighbour features on exact coordinates (same rules as v2: previous 36 months) ----------
# the pool is every earlier sale since 2012 from the frame (y_defl known), using exact positions where available
rad = np.radians(s[["xlat", "xlon"]].values)
for c in ["xknn_lvl", "xknn_dist", "xknn_ppsqm", "size_nn_lvl", "size_nn_n", "size_nn_ppsqm"]: s[c] = np.nan
lfa = np.log(s.floor_area.values); ppsqm = s.y_defl.values - lfa
for m in pd.date_range("2015-01-01", s.month.max(), freq="MS"):
    q = (s.month == m).values
    if not q.any(): continue
    pool = ((s.month >= m - pd.DateOffset(months=36)) & (s.month < m)).values
    for t in "DSTF":
        qt, pt = q & (s.property_type == t).values, pool & (s.property_type == t).values
        if qt.sum() == 0 or pt.sum() < 3: continue
        tree = BallTree(rad[pt], metric="haversine"); kk = min(60, pt.sum())
        dist, ind = tree.query(rad[qt], k=kk)
        vals = s.y_defl.values[pt][ind]
        s.loc[qt, "xknn_lvl"] = np.median(vals[:, :10], axis=1); s.loc[qt, "xknn_dist"] = dist[:, :10].mean(axis=1) * R
        # similar size: among the 60 nearest of the same type, those within +/-20% floor area; up to 10 nearest
        qfa, pfa = lfa[qt], lfa[pt][ind]
        ok = np.abs(pfa - qfa[:, None]) <= np.log(1.2)
        rank = np.cumsum(ok, axis=1); ok &= rank <= 10
        cnt = ok.sum(1).astype(float)
        with np.errstate(all="ignore"):
            lv = np.where(cnt >= 3, np.nanmedian(np.where(ok, vals, np.nan), axis=1), np.nan)
            pp = np.where(cnt >= 3, np.nanmedian(np.where(ok, ppsqm[pt][ind], np.nan), axis=1), np.nan)
        s.loc[qt, "size_nn_lvl"] = lv; s.loc[qt, "size_nn_n"] = cnt; s.loc[qt, "size_nn_ppsqm"] = pp
    pa = pool & np.isfinite(lfa)
    if pa.sum() >= 5:
        tree = BallTree(rad[pa], metric="haversine"); _, ind = tree.query(rad[q], k=min(15, pa.sum()))
        s.loc[q, "xknn_ppsqm"] = np.median(ppsqm[pa][ind], axis=1)

# ---------- street and postcode levels, previous 5 years ----------
s["street_key"] = s.street.fillna("") + "|" + s.town.fillna("") + "|" + s.district.fillna("")
for c in ["lvl_street_type", "n_street_type", "lvl_postcode", "n_postcode"]: s[c] = np.nan
for m in pd.date_range("2015-01-01", s.month.max(), freq="MS"):
    q = (s.month == m).values
    if not q.any(): continue
    pw = s[((s.month >= m - pd.DateOffset(months=60)) & (s.month < m)).values]
    st = pw.groupby(["street_key", "property_type"]).y_defl.agg(["median", "count"]); pc = pw.groupby("postcode").y_defl.agg(["median", "count"])
    sub = s.loc[q, ["street_key", "property_type", "postcode"]]
    a = st.reindex(pd.MultiIndex.from_frame(sub[["street_key", "property_type"]])); b = pc.reindex(sub.postcode)
    s.loc[q, "lvl_street_type"] = np.where(a["count"].values >= 2, a["median"].values, np.nan); s.loc[q, "n_street_type"] = a["count"].fillna(0).values
    s.loc[q, "lvl_postcode"] = np.where(b["count"].values >= 2, b["median"].values, np.nan); s.loc[q, "n_postcode"] = b["count"].fillna(0).values

# ---------- more EPC fields, with the same timing rules as epc_match.py ----------
e = load_epc()[["certificate_number", "dwelling", "lodgement_date"]]
x = duckdb.sql(f"""select certificate_number, walls_description, roof_description, windows_description, main_fuel, mainheat_description,
        secondheat_description, number_open_fireplaces, low_energy_lighting, photo_supply, floor_height, floor_level, flat_top_storey,
        number_heated_rooms, glazed_area from read_csv_auto('{RAW}/epc_doncaster.csv', all_varchar=true, sample_size=-1)""").df()
e = e.merge(x, on="certificate_number", how="left")
w = e.walls_description.fillna("").str.lower(); r_ = e.roof_description.fillna("").str.lower(); win = e.windows_description.fillna("").str.lower()
e["wall_type"] = np.select([w.str.contains("cavity"), w.str.contains("solid brick"), w.str.contains("system"), w.str.contains("timber"),
                            w.str.contains("stone|granite|sandstone")], [0, 1, 2, 3, 4], np.nan)
e["wall_insulated"] = np.select([w.str.contains("no insulation"), w.str.contains("partial"), w.str.contains("filled|insulated|insulation")], [0, 0.5, 1], np.nan)
loft = r_.str.extract(r"(\d+)\+?\s*mm")[0].astype(float)
e["loft_mm"] = np.where(r_.str.contains("no insulation"), 0, loft)
e["glazing"] = np.select([win.str.contains("single"), win.str.contains("some"), win.str.contains("partial"), win.str.contains("mostly"),
                          win.str.contains("triple"), win.str.contains("high performance"), win.str.contains("fully|double")], [0, .3, .5, .8, 1.3, 1.2, 1], np.nan)
mh = e.mainheat_description.fillna("").str.lower()
e["elec_heating"] = np.where(mh == "", np.nan, (mh.str.contains("electric") & ~mh.str.contains("boiler|heat pump")).astype(float))
e["heat_pump"] = np.where(mh == "", np.nan, mh.str.contains("heat pump").astype(float))
e["woodburner"] = e.secondheat_description.fillna("").str.lower().str.contains("wood|dual fuel|multi-fuel|smokeless").astype(float).where(e.secondheat_description.notna())
e["fireplaces"] = pd.to_numeric(e.number_open_fireplaces, errors="coerce"); e["low_energy_light"] = pd.to_numeric(e.low_energy_lighting, errors="coerce")
e["solar_pv"] = (pd.to_numeric(e.photo_supply, errors="coerce") > 0).astype(float).where(e.photo_supply.notna())
e["ceiling_m"] = pd.to_numeric(e.floor_height, errors="coerce").where(lambda v: v.between(1.8, 5))
fl = e.floor_level.fillna("").str.lower()
e["floor_level_n"] = np.select([fl.str.contains("basement"), fl.str.contains("ground"), fl.str.contains("mid"), fl.str.contains("top")], [-1, 0, 1.5, 3],
                               pd.to_numeric(fl.str.extract(r"(\d+)")[0], errors="coerce"))
e["floor_level_n"] = np.where(fl == "", np.nan, e.floor_level_n)
e["top_floor"] = e.flat_top_storey.map({"Y": 1.0, "N": 0.0}); e["heated_rooms"] = pd.to_numeric(e.number_heated_rooms, errors="coerce")
e["glazed_area_n"] = e.glazed_area.fillna("").str.lower().map({"much less than typical": -2, "less than typical": -1, "normal": 0, "more than typical": 1, "much more than typical": 2})
PHYS_X = ["wall_type", "ceiling_m", "floor_level_n", "top_floor", "heated_rooms", "glazed_area_n", "fireplaces"]
ENER_X = ["wall_insulated", "loft_mm", "glazing", "elec_heating", "heat_pump", "woodburner", "low_energy_light", "solar_pv"]
e = e.sort_values("lodgement_date")
sd = s[["unique_id", "dwelling", "sale_date"]].copy()
sd = sd[sd.dwelling.notna()]
# physical: latest certificate up to 90 days after the sale, else the earliest one
a = pd.merge_asof(sd.assign(t=sd.sale_date + pd.Timedelta(days=90)).sort_values("t"), e[["dwelling", "lodgement_date"] + PHYS_X].rename(columns={"lodgement_date": "t"}),
                  on="t", by="dwelling", direction="backward")
first = e.groupby("dwelling")[PHYS_X].first()
miss = a[PHYS_X].isna().all(axis=1)
a.loc[miss, PHYS_X] = first.reindex(a.loc[miss, "dwelling"]).values
# energy/condition: only certificates lodged on or before the sale
b = pd.merge_asof(sd.sort_values("sale_date"), e[["dwelling", "lodgement_date"] + ENER_X].rename(columns={"lodgement_date": "sale_date"}),
                  on="sale_date", by="dwelling", direction="backward")
s = s.merge(a[["unique_id"] + PHYS_X], on="unique_id", how="left").merge(b[["unique_id"] + ENER_X], on="unique_id", how="left"); assert len(s) == n0
print("EPC extra coverage:", {c: f"{s[c].notna().mean():.0%}" for c in PHYS_X + ENER_X})

# ---------- VOA council tax band and build-period mix by LSOA ----------
v1 = pd.read_csv(RAW / "voa/CTSOP1.1/CTSOP1.1/CTSOP1_1_2025_03_31.csv", encoding="utf-8-sig", low_memory=False)
v1 = v1[v1.geography == "LSOA"].set_index("ecode")
bands = ["band_a", "band_b", "band_c", "band_d", "band_e", "band_f", "band_g", "band_h"]
cnt = v1[bands].apply(pd.to_numeric, errors="coerce").fillna(0)
tot = cnt.sum(1).where(lambda v: v > 0)
voa = pd.DataFrame({"ct_band_mean": (cnt.values * np.arange(1, 9)).sum(1) / tot, "ct_share_a": cnt.band_a / tot, "ct_share_d_plus": cnt[bands[3:]].sum(1) / tot}, index=v1.index)
v4 = pd.read_csv(RAW / "voa/CTSOP4.1/CTSOP4.1/CTSOP4_1_2025_03_31.csv", encoding="utf-8-sig", low_memory=False)
v4 = v4[(v4.geography == "LSOA") & (v4.band == "All")].set_index("ecode")
bp = v4[[c for c in v4.columns if c.startswith("bp_")]].apply(pd.to_numeric, errors="coerce").fillna(0)
old = bp[["bp_pre_1900", "bp_1900_1918"]].sum(1); new = bp[[c for c in bp.columns if c[3:7].isdigit() and int(c[3:7]) >= 2000]].sum(1)
voa["ct_share_pre1919"] = old / bp.sum(1).where(lambda v: v > 0); voa["ct_share_post2000"] = new / bp.sum(1).where(lambda v: v > 0)
s = s.merge(voa, left_on="lsoa21", right_index=True, how="left"); assert len(s) == n0
print("VOA coverage:", f"{s.ct_band_mean.notna().mean():.1%}")
s.to_parquet(P_ / "model_frame_v5.parquet")
voa.to_parquet(P_ / "voa_lsoa.parquet")
print("saved", s.shape)
