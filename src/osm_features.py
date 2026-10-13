"""Points of interest from OpenStreetMap (Geofabrik South Yorkshire extract, ODbL) and distance features per postcode.

Ways (parks, supermarket buildings) are reduced to the mean of their node locations.
OSM is a current snapshot, and the extract stops at the county boundary, so homes near the
Lincolnshire / Yorkshire / Nottinghamshire borders may see a feature as further away than it is."""
import pathlib, numpy as np, pandas as pd, osmium
from sklearn.neighbors import BallTree

ROOT = pathlib.Path(__file__).resolve().parents[1]; R = 6371.0
PBF = ROOT / "data/raw/osm/south-yorkshire-261008.osm.pbf"

def kind(tags):
    shop, am, le, hw = tags.get("shop"), tags.get("amenity"), tags.get("leisure"), tags.get("highway")
    if shop == "supermarket": return "supermarket"
    if am in ("pub", "cafe", "restaurant", "bar"): return "food_drink"
    if am in ("doctors", "clinic") or tags.get("healthcare") == "doctor": return "gp"
    if le in ("park", "nature_reserve") or tags.get("landuse") == "recreation_ground": return "park"
    if hw == "motorway_junction": return "junction"
    return None

class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.pois = []; self.roads = []
    def node(self, n):
        k = kind(n.tags)
        if k and n.location.valid(): self.pois.append((k, n.location.lat, n.location.lon, n.tags.get("name") or n.tags.get("brand") or n.tags.get("ref") or ""))
    def way(self, w):
        k = kind(w.tags); hw = w.tags.get("highway")
        pts = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
        if not pts: return
        if k and k != "junction":
            a = np.array(pts); self.pois.append((k, a[:, 0].mean(), a[:, 1].mean(), w.tags.get("name") or w.tags.get("brand") or ""))
        if hw in ("motorway", "trunk"):
            self.roads.extend(pts)

def extract():
    h = H(); h.apply_file(str(PBF), locations=True)
    pois = pd.DataFrame(h.pois, columns=["kind", "lat", "lon", "name"])
    roads = pd.DataFrame(h.roads, columns=["lat", "lon"]).drop_duplicates()
    return pois, roads

def features(pc: pd.DataFrame, pois: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    q = np.radians(pc[["lat", "lon"]].values); out = pc[["postcode"]].copy()
    def near(df):
        t = BallTree(np.radians(df[["lat", "lon"]].values), metric="haversine"); d, _ = t.query(q, k=1); return d[:, 0] * R
    for k, col in [("supermarket", "dist_supermarket_km"), ("park", "dist_park_km"), ("gp", "dist_gp_km"), ("junction", "dist_junction_km")]:
        out[col] = near(pois[pois.kind == k])
    t = BallTree(np.radians(pois.loc[pois.kind == "food_drink", ["lat", "lon"]].values), metric="haversine")
    out["food_drink_800m"] = t.query_radius(q, r=0.8 / R, count_only=True).astype(float)
    out["dist_major_road_m"] = near(roads) * 1000
    return out

if __name__ == "__main__":
    import duckdb
    pc = duckdb.connect(str(ROOT / "data/processed/doncaster.duckdb"), read_only=True).execute("select postcode, lat, lon from postcodes where lat is not null").df()
    pois, roads = extract()
    print(pois.kind.value_counts().to_dict(), "major-road nodes:", len(roads))
    f = features(pc, pois, roads)
    f.to_parquet(ROOT / "data/processed/amenities_osm.parquet"); pois.to_parquet(ROOT / "data/processed/osm_pois.parquet")
    print(f.describe().T[["mean", "50%", "max"]].round(2))
