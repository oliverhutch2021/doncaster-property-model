"""Building footprints per home from OS OpenMap Local (April 2026), to test whether footprints reveal extensions.

Each EPC home's UPRN point is matched to the building outline it sits in (or the nearest within 15 m, since address
points can fall just outside an outline). Terraces and semis are often one merged outline, so the footprint is shared
by the EPC homes inside it. Features:
  bld_m2            area of the outline
  bld_homes         EPC homes whose point falls in it
  bld_m2_per_home   area / homes
  garden_m2         plot area per home - footprint per home (from src/plots.py)
Contains OS data © Crown copyright and database right 2026."""
import pathlib, numpy as np, pandas as pd, pyogrio, shapely
from shapely import STRtree
ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; P_ = ROOT / "data/processed"
BBOX = (430000, 380000, 490000, 440000)

if __name__ == "__main__":
    parts = [pyogrio.read_dataframe(RAW / f"osmap/{t}_Building.shp", bbox=BBOX, columns=[]) for t in ("SE", "SK")]
    geoms = np.concatenate([p.geometry.values for p in parts]); areas = shapely.area(geoms)
    print(f"building outlines in the Doncaster box: {len(geoms):,}  median {np.median(areas):.0f} m2")
    up = pd.read_parquet(P_ / "uprn_plots.parquet")
    u = pd.read_csv(RAW / "uprn/uprn_doncaster_bbox.csv", encoding="utf-8-sig", usecols=["UPRN", "X_COORDINATE", "Y_COORDINATE"])
    u = u[u.UPRN.isin(set(up.uprn))].reset_index(drop=True)
    pts = shapely.points(u.X_COORDINATE.values, u.Y_COORDINATE.values)
    tree = STRtree(geoms)
    pi, gi = tree.query(pts, predicate="within")
    g = np.full(len(u), -1); g[pi] = gi
    miss = np.where(g < 0)[0]
    ni, nd = tree.query_nearest(pts[miss], max_distance=15, return_distance=True, all_matches=False)
    g[miss[ni[0]]] = ni[1]
    u["bld"] = g; u["bld_m2"] = np.where(g >= 0, areas[np.maximum(g, 0)], np.nan)
    homes = u[u.bld >= 0].groupby("bld").size(); u["bld_homes"] = u.bld.map(homes)
    u["bld_m2_per_home"] = u.bld_m2 / u.bld_homes
    # every address point (any use) inside each outline, a fuller count of the homes sharing a merged terrace outline
    allu = pd.read_csv(RAW / "uprn/uprn_doncaster_bbox.csv", encoding="utf-8-sig", usecols=["X_COORDINATE", "Y_COORDINATE"])
    _, ag = tree.query(shapely.points(allu.X_COORDINATE.values, allu.Y_COORDINATE.values), predicate="within")
    u["bld_uprns"] = u.bld.map(pd.Series(ag).value_counts()).fillna(u.bld_homes)
    u["bld_m2_per_uprn"] = u.bld_m2 / u.bld_uprns
    out = u.rename(columns={"UPRN": "uprn"})[["uprn", "bld_m2", "bld_homes", "bld_uprns", "bld_m2_per_home", "bld_m2_per_uprn"]].merge(up[["uprn", "plot_m2_per_home"]], on="uprn", how="left")
    out["garden_m2"] = (out.plot_m2_per_home - out.bld_m2_per_home).where(lambda v: v > -50)
    out.drop(columns="plot_m2_per_home").to_parquet(P_ / "uprn_buildings.parquet")
    print(f"homes matched to an outline: {np.mean(g >= 0):.1%} (inside {len(pi)/len(u):.1%}, nearest within 15 m {len(ni[0])/len(u):.1%})")
    print(out[["bld_m2", "bld_homes", "bld_uprns", "bld_m2_per_home", "bld_m2_per_uprn", "garden_m2"]].describe(percentiles=[.1, .5, .9]).round(1).to_string())
