"""Street map for the comparables map: buildings, named roads, woods, parks, water, rail and school or hospital
grounds from OS OpenMap Local and OS Open Greenspace (src/fetch_data.sh), one file per postcode district the
comparables cover, so the page loads only the districts in view.

Each feature goes to the district of the nearest postcode (ONS centroids in outputs/dash2/postcodes.csv) and is kept
if that postcode is within KEEP_M. Shapes are simplified to about a metre and stored as Google encoded polylines
(latitude/longitude, 5 decimal places, about 1 m), outer rings only.

Output: outputs/dash2/map_<district>.csv with columns
  k  kind: g park or other green space, w woodland, s school or hospital grounds, a water, l stream or drain,
     b building, i important building (school, church, surgery...), t railway, r road
  c  class: for roads M motorway, P primary, A, B, m minor, l local, x restricted or private access; for green
     space its OS function; otherwise blank
  n  name (roads: street name and number; parks and sites: their name)
  p  shape, encoded polyline
Contains OS data © Crown copyright and database right 2026 (Open Government Licence)."""
import pathlib
import numpy as np, pandas as pd, pyogrio, shapely
from pyproj import Transformer
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; D = ROOT / "outputs/dash2"
BBOX = (425000, 375000, 495000, 445000)          # the Doncaster box (src/buildings.py) plus 5 km
KEEP_M = 1500
TOL = {"b": 0.5, "i": 0.5, "r": 1.5, "t": 2, "l": 2, "a": 1.5, "w": 2.5, "g": 1.5, "s": 1.5}
ROAD = {"Motorway": "M", "Primary Road": "P", "A Road": "A", "B Road": "B", "Minor Road": "m", "Local Road": "l", "Shared Use Carriageway": "l",
        "Guided Busway Carriageway": "x", "Local Access Road": "x", "Restricted Local Access Road": "x"}
to_ll = Transformer.from_crs(27700, 4326, always_xy=True); to_bng = Transformer.from_crs(4326, 27700, always_xy=True)


def enc(coords):
    """Google encoded polyline of (lat, lon) pairs."""
    out, plat, plon = [], 0, 0
    for lat, lon in coords:
        ilat, ilon = int(round(lat * 1e5)), int(round(lon * 1e5))
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63)); v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def parts(g):
    """Outer rings of polygons and the lines of line features, as BNG coordinate arrays."""
    if g is None or g.is_empty: return []
    if g.geom_type in ("Polygon", "LineString"): g = [g]
    else: g = list(g.geoms)
    return [np.asarray(x.exterior.coords if x.geom_type == "Polygon" else x.coords) for x in g]


def layer(t, name, cols=None):
    f = RAW / ("osmap" if not name.startswith("Greenspace") else f"greenspace/{t}") / f"{t}_{name}.shp"
    return pyogrio.read_dataframe(f, bbox=BBOX, columns=cols or [])


if __name__ == "__main__":
    comps = pd.read_csv(D / "comps.csv", usecols=["postcode"]); districts = sorted(set(comps.postcode.str.split().str[0]))
    pc = pd.read_csv(D / "postcodes.csv", usecols=["postcode", "lat", "lon"]); pc["d"] = pc.postcode.str.split().str[0]
    pc = pc[pc.d.isin(districts)].reset_index(drop=True)
    px, py = to_bng.transform(pc.lon.values, pc.lat.values); tree = cKDTree(np.c_[px, py])
    feats = []                                   # (kind, class, name, geometry)
    for t in ("SE", "SK"):
        r = layer(t, "Road", ["DISTNAME", "ROADNUMBER", "CLASSIFICA"])
        r["c"] = r.CLASSIFICA.str.split(",").str[0].map(ROAD).fillna("l")
        r["n"] = [", ".join(x for x in (a, b) if isinstance(x, str) and x) for a, b in zip(r.DISTNAME, r.ROADNUMBER)]
        feats += [("r", c, n, g) for c, n, g in zip(r.c, r.n, r.geometry)]
        feats += [("b", "", "", g) for g in layer(t, "Building").geometry]
        ib = layer(t, "ImportantBuilding", ["DISTNAME"]); feats += [("i", "", n or "", g) for n, g in zip(ib.DISTNAME, ib.geometry)]
        feats += [("w", "", "", g) for g in layer(t, "Woodland").geometry]
        feats += [("a", "", "", g) for g in layer(t, "SurfaceWater_Area").geometry]
        feats += [("l", "", "", g) for g in layer(t, "SurfaceWater_Line").geometry]
        feats += [("t", "", "", g) for g in layer(t, "RailwayTrack").geometry]
        fs = layer(t, "FunctionalSite", ["DISTNAME"]); feats += [("s", "", n or "", g) for n, g in zip(fs.DISTNAME, fs.geometry)]
        gs = layer(t, "GreenspaceSite", ["function", "distName1"]); feats += [("g", f, n or "", g) for f, n, g in zip(gs.function, gs.distName1, gs.geometry)]
    print(f"{len(feats):,} features in the box")
    geoms = np.array([f[3] for f in feats], dtype=object)
    rp = shapely.point_on_surface(geoms); dist, idx = tree.query(np.c_[shapely.get_x(rp), shapely.get_y(rp)])
    rows = {d: [] for d in districts}
    for (k, c, n, g), dd, i in zip(feats, dist, idx):
        if dd > KEEP_M: continue
        for xy in parts(shapely.simplify(g, TOL[k], preserve_topology=False)):
            if len(xy) < 2: continue
            lon, lat = to_ll.transform(xy[:, 0], xy[:, 1])
            rows[pc.d[i]].append((k, c, n, enc(zip(lat, lon))))
    order = {k: j for j, k in enumerate("gwsalbitr")}
    tot = 0
    for d, rr in rows.items():
        out = pd.DataFrame(rr, columns=["k", "c", "n", "p"]).sort_values("k", key=lambda s: s.map(order), kind="stable")
        out = out[out.p.str.len() > 0]; f = D / f"map_{d}.csv"; out.to_csv(f, index=False); tot += f.stat().st_size
        print(f"{d:5s} {len(out):7,d} shapes {f.stat().st_size / 1e6:5.2f} MB")
    print(f"total {tot / 1e6:.1f} MB")
