"""Neighbourhood amenity and risk features per postcode: flood risk, transport, schools, rural-urban class.

Sources (all Open Government Licence):
  - Environment Agency, Risk of Flooding from Rivers and Sea (NaFRA2), Postcodes in Areas at Risk
  - DfT NaPTAN access nodes (rail stations, bus stops)
  - DfE Get Information about Schools (all establishments, incl. closed, with open/close dates)
  - Ofsted state-funded schools inspections and outcomes as at 31 March 2026
  - ONS LSOA 2021 boundaries with 2021 rural-urban classification

Schools are matched in time: a sale only "sees" schools that were open in its year.
Flood risk, transport and Ofsted grades are current snapshots (see docs/DECISIONS.md)."""
import json, pathlib, numpy as np, pandas as pd
from sklearn.neighbors import BallTree
from pyproj import Transformer

ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; R = 6371.0
BBOX = dict(lat=(53.25, 53.85), lon=(-1.55, -0.65))   # Doncaster plus a margin, so border homes see neighbouring stations and stops

def flood_by_postcode() -> pd.DataFrame:
    f = pd.read_csv(RAW / "flood/rofrs/RoFRS_Postcodes_in_Areas_at_Risk/DATA/NaFRA2client.RoFRS_Postcodes_AtRisk.csv", encoding="utf-8-sig")
    f["postcode"] = f.PC.str.upper().str.strip()
    res = f.RES_cntpc.where(f.RES_cntpc > 0)
    hm, anyr = f.RES_CNT_High + f.RES_CNT_Medium, f.RES_CNT_High + f.RES_CNT_Medium + f.RES_CNT_Low + f.RES_CNT_VeryLow
    # postcodes with no residential count fall back to all properties
    f["flood_hm"] = (hm / res).fillna((f.TOT_CNT_High + f.TOT_CNT_Medium) / f.cntpc.where(f.cntpc > 0)).clip(0, 1)
    f["flood_any"] = (anyr / res).fillna((f.TOT_CNT_High + f.TOT_CNT_Medium + f.TOT_CNT_Low + f.TOT_CNT_VeryLow) / f.cntpc.where(f.cntpc > 0)).clip(0, 1)
    return f[["postcode", "flood_hm", "flood_any"]]

def stops() -> tuple[pd.DataFrame, pd.DataFrame]:
    n = pd.read_csv(RAW / "naptan/naptan_all.csv", low_memory=False, usecols=["ATCOCode", "CommonName", "StopType", "Status", "Latitude", "Longitude"])
    n = n[(n.Status == "active") & n.Latitude.between(*BBOX["lat"]) & n.Longitude.between(*BBOX["lon"])]
    rail = n[n.StopType == "RLY"].copy()
    rail["name"] = rail.CommonName.str.replace(r"\s+Rail Station$", "", regex=True)
    rail = rail.groupby("name", as_index=False)[["Latitude", "Longitude"]].mean()
    bus = n[n.StopType.isin(["BCT", "BCS"])]
    return rail, bus

def schools() -> pd.DataFrame:
    g = pd.read_csv(RAW / "schools/edubasealldata.csv", encoding="cp1252", low_memory=False)
    g = g[g["EstablishmentTypeGroup (name)"].isin(["Local authority maintained schools", "Academies", "Free Schools"])
          & g["PhaseOfEducation (name)"].isin(["Primary", "Secondary", "All-through", "Middle deemed primary", "Middle deemed secondary"])
          & g.Easting.notna() & (g.Easting > 0)].copy()
    lon, lat = Transformer.from_crs(27700, 4326, always_xy=True).transform(g.Easting.values, g.Northing.values)
    g["lat"], g["lon"] = lat, lon
    g = g[g.lat.between(*BBOX["lat"]) & g.lon.between(*BBOX["lon"])]
    ph = g["PhaseOfEducation (name)"]
    g["primary"] = ph.isin(["Primary", "All-through", "Middle deemed primary"])
    g["secondary"] = ph.isin(["Secondary", "All-through", "Middle deemed secondary"])
    g["open"] = pd.to_datetime(g.OpenDate, dayfirst=True, errors="coerce").fillna(pd.Timestamp("1900-01-01"))
    g["close"] = pd.to_datetime(g.CloseDate, dayfirst=True, errors="coerce").fillna(pd.Timestamp("2100-01-01"))
    o = pd.read_csv(RAW / "schools/ofsted_mar2026.csv", encoding="cp1252", low_memory=False)[["URN", "Latest OEIF overall effectiveness"]]
    o["grade"] = pd.to_numeric(o["Latest OEIF overall effectiveness"], errors="coerce")
    g = g.merge(o[["URN", "grade"]], on="URN", how="left")
    g["good"] = g.grade.isin([1, 2])
    return g[["URN", "EstablishmentName", "lat", "lon", "primary", "secondary", "open", "close", "grade", "good", "Postcode"]]

def nearest_km(src_lat, src_lon, dst_lat, dst_lon):
    if len(dst_lat) == 0: return np.full(len(src_lat), np.nan)
    t = BallTree(np.radians(np.c_[dst_lat, dst_lon]), metric="haversine")
    d, _ = t.query(np.radians(np.c_[src_lat, src_lon]), k=1)
    return d[:, 0] * R

def static_features(pc: pd.DataFrame) -> pd.DataFrame:
    """pc: postcode, lat, lon, lsoa21 -> flood, rail, bus, rural-urban (no time dimension)."""
    out = pc[["postcode", "lat", "lon", "lsoa21"]].copy()
    out = out.merge(flood_by_postcode(), on="postcode", how="left")
    out[["flood_hm", "flood_any"]] = out[["flood_hm", "flood_any"]].fillna(0.0)   # not listed = no properties in an area at risk
    rail, bus = stops()
    out["dist_rail_km"] = nearest_km(out.lat, out.lon, rail.Latitude, rail.Longitude)
    bt = BallTree(np.radians(bus[["Latitude", "Longitude"]].values), metric="haversine")
    out["bus_stops_500m"] = bt.query_radius(np.radians(out[["lat", "lon"]].values), r=0.5 / R, count_only=True).astype(float)
    lz = json.load(open(RAW / "boundaries/lsoa21_doncaster_bsc.geojson"))
    ruc = {f["properties"]["LSOA21CD"]: f["properties"]["RUC21CD"] for f in lz["features"]}
    out["rural"] = out.lsoa21.map(lambda c: np.nan if c not in ruc else (0.0 if ruc[c].startswith("U") else 1.0))
    return out.drop(columns=["lat", "lon", "lsoa21"])

def school_features(pc: pd.DataFrame, years) -> pd.DataFrame:
    """Distance to the nearest state primary, secondary and good-or-outstanding primary open on 1 July of each year."""
    sc = schools(); rows = []
    for y in years:
        day = pd.Timestamp(f"{y}-07-01"); s = sc[(sc.open <= day) & (sc.close > day)]
        p, sec, gp = s[s.primary], s[s.secondary], s[s.primary & s.good]
        rows.append(pd.DataFrame({"postcode": pc.postcode.values, "year": y,
                                  "dist_primary_km": nearest_km(pc.lat, pc.lon, p.lat, p.lon),
                                  "dist_secondary_km": nearest_km(pc.lat, pc.lon, sec.lat, sec.lon),
                                  "dist_good_primary_km": nearest_km(pc.lat, pc.lon, gp.lat, gp.lon)}))
    return pd.concat(rows, ignore_index=True)

if __name__ == "__main__":
    import duckdb
    pc = duckdb.connect(str(ROOT / "data/processed/doncaster.duckdb"), read_only=True).execute("select postcode, lat, lon, lsoa21 from postcodes where lat is not null").df()
    st = static_features(pc)
    yrs = list(range(2014, 2027)); sch = school_features(pc, yrs)
    st.to_parquet(ROOT / "data/processed/amenities_static.parquet"); sch.to_parquet(ROOT / "data/processed/amenities_schools.parquet")
    print(st.describe().T[["count", "mean", "50%", "max"]].round(3))
    print(sch[sch.year == 2026].describe().T[["count", "mean", "50%", "max"]].round(3))
    print("postcodes with any flood risk:", f"{(st.flood_any > 0).mean():.1%}", "high/medium:", f"{(st.flood_hm > 0).mean():.1%}")
