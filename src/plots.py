"""Exact location and plot size for each EPC dwelling.

  - OS Open UPRN (Sept 2026): coordinates of every UPRN; EPC certificates carry the home's UPRN.
  - HM Land Registry INSPIRE Index Polygons (Doncaster, Oct 2026): the extent of each registered freehold title.
A home's plot is the title polygon its UPRN point falls in. A block of flats shares one polygon, so the number of
EPC homes inside each polygon is kept too, and plot area per home = area / homes.

Contains HM Land Registry data © Crown copyright and database right 2026, licensed under the OGL v3.0.
Contains OS data © Crown copyright and database right 2026."""
import re, pathlib, numpy as np, pandas as pd, duckdb
import shapely
from shapely import STRtree

ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; P_ = ROOT / "data/processed"
MEMBER = re.compile(r"<wfs:member>(.*?)</wfs:member>", re.S)
EXT = re.compile(r"<gml:exterior>.*?<gml:posList>(.*?)</gml:posList>", re.S)
INT = re.compile(r"<gml:interior>.*?<gml:posList>(.*?)</gml:posList>", re.S)
PID = re.compile(r"<LR:INSPIREID>(\d+)</LR:INSPIREID>")

def ring(s):
    a = np.fromstring(s, sep=" "); return a.reshape(-1, 2)

def load_polygons():
    text = open(RAW / "inspire/Land_Registry_Cadastral_Parcels.gml", encoding="utf-8").read()
    ids, geoms = [], []
    for m in MEMBER.finditer(text):
        b = m.group(1); ex = EXT.search(b)
        if not ex: continue
        holes = [ring(h) for h in INT.findall(b)]
        g = shapely.Polygon(ring(ex.group(1)), holes)
        if not g.is_valid: g = shapely.make_valid(g)
        ids.append(int(PID.search(b).group(1))); geoms.append(g)
    return pd.DataFrame({"inspire_id": ids, "area_m2": [g.area for g in geoms]}), np.array(geoms, dtype=object)

if __name__ == "__main__":
    polys, geoms = load_polygons()
    print(f"title polygons: {len(polys):,}  median area {polys.area_m2.median():.0f} m2")
    epc_uprn = duckdb.sql(f"""select distinct try_cast(uprn as bigint) uprn from read_csv_auto('{RAW}/epc_doncaster.csv', all_varchar=true, sample_size=-1)
                              where uprn is not null and uprn <> ''""").df().dropna()
    u = pd.read_csv(RAW / "uprn/uprn_doncaster_bbox.csv", encoding="utf-8-sig")
    u = u[u.UPRN.isin(set(epc_uprn.uprn.astype("int64")))].reset_index(drop=True)
    print(f"EPC UPRNs: {len(epc_uprn):,}  found in OS Open UPRN: {len(u):,}")
    tree = STRtree(geoms)
    pts = shapely.points(u.X_COORDINATE.values, u.Y_COORDINATE.values)
    pi, gi = tree.query(pts, predicate="within")
    hit = pd.DataFrame({"i": pi, "g": gi})
    hit["area"] = polys.area_m2.values[hit.g]
    hit = hit.sort_values("area").drop_duplicates("i")          # overlapping titles: take the smallest that contains the point
    u["inspire_id"] = np.nan; u["plot_m2"] = np.nan
    u.loc[hit.i.values, "inspire_id"] = polys.inspire_id.values[hit.g.values]; u.loc[hit.i.values, "plot_m2"] = hit.area.values
    homes = u.groupby("inspire_id").size().rename("plot_epc_homes")
    # all addressable points (any use) in each title, as a second count of how many homes share it
    allu = pd.read_csv(RAW / "uprn/uprn_doncaster_bbox.csv", encoding="utf-8-sig", usecols=["X_COORDINATE", "Y_COORDINATE"])
    ai, ag = tree.query(shapely.points(allu.X_COORDINATE.values, allu.Y_COORDINATE.values), predicate="within")
    allc = pd.Series(polys.inspire_id.values[ag]).value_counts().rename("plot_uprns")
    u = u.merge(homes, left_on="inspire_id", right_index=True, how="left")
    u = u.merge(allc, left_on="inspire_id", right_index=True, how="left")
    u["plot_m2_per_home"] = u.plot_m2 / u.plot_epc_homes
    out = u.rename(columns={"UPRN": "uprn", "LATITUDE": "ulat", "LONGITUDE": "ulon"})[["uprn", "ulat", "ulon", "inspire_id", "plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home"]]
    out.to_parquet(P_ / "uprn_plots.parquet")
    print(f"UPRNs inside a title polygon: {out.plot_m2.notna().mean():.1%}")
    print(out[["plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home"]].describe(percentiles=[.1, .5, .9]).round(1).to_string())
