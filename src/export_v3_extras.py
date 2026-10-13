"""Dashboard datasets for the 'around this home' card and the neighbourhood map.

places.csv     stations, schools (with Ofsted grade), supermarkets, GPs, parks, motorway junctions near Doncaster
pc_extras.csv  per postcode: flood risk shares, bus stops, food and drink places nearby, distance to a major road, rural flag
lsoa_map.json  per 2021 neighbourhood (LSOA): boundary + price, price per m2, deprivation, flood, rented, EPC shares"""
import json, pathlib, numpy as np, pandas as pd, duckdb, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from amenities import stops, schools
ROOT = pathlib.Path(__file__).resolve().parents[1]; P_ = ROOT / "data/processed"; RAW = ROOT / "data/raw"; D = ROOT / "outputs/dash2"
WIN = dict(lat=(53.30, 53.80), lon=(-1.50, -0.70))
inwin = lambda d, la="lat", lo="lon": d[d[la].between(*WIN["lat"]) & d[lo].between(*WIN["lon"])]

# ---------- places ----------
rail, _ = stops(); rail = inwin(rail.rename(columns={"Latitude": "lat", "Longitude": "lon"}))
pl = [pd.DataFrame({"kind": "station", "name": rail.name, "lat": rail.lat, "lon": rail.lon, "info": ""})]
sc = schools(); sc = inwin(sc[sc.close > pd.Timestamp("2026-10-01")])
g = pd.read_csv(RAW / "schools/ofsted_mar2026.csv", encoding="cp1252", low_memory=False)[["URN", "Inspection start date of latest OEIF graded inspection", "Latest OEIF quality of education", "Achievement", "Inspection start date"]]
sc = sc.merge(g, on="URN", how="left")
GRADE = {1: "Outstanding", 2: "Good", 3: "Requires improvement", 4: "Inadequate"}
def info(r):
    yr = str(r["Inspection start date of latest OEIF graded inspection"])[-4:]
    if r.grade in GRADE: return f"Ofsted {GRADE[int(r.grade)]} ({yr})"
    qoe = pd.to_numeric(r["Latest OEIF quality of education"], errors="coerce")
    if qoe in GRADE: return f"Ofsted quality of education {GRADE[int(qoe)]} ({yr})"   # Sept 2024 - Nov 2025: no overall grade given
    if isinstance(r.Achievement, str): return f"Ofsted report card ({str(r['Inspection start date'])[-4:]}): achievement {r.Achievement.lower()}"
    return "No graded Ofsted judgement in the March 2026 data"
sc["info"] = [info(r) for _, r in sc.iterrows()]
sc["kind"] = np.where(sc.primary & sc.secondary, "allthrough", np.where(sc.primary, "primary", "secondary"))
pl.append(sc[["kind", "EstablishmentName", "lat", "lon", "info"]].rename(columns={"EstablishmentName": "name"}))
po = inwin(pd.read_parquet(P_ / "osm_pois.parquet")); po = po[po.kind.isin(["supermarket", "gp", "park", "junction"])].copy()
po.loc[(po.kind == "park") & (po.name == ""), "name"] = "Park or green space"
po.loc[(po.kind == "junction") & (po.name == ""), "name"] = "Unnamed junction"
po.loc[(po.kind == "junction") & po.name.str.fullmatch(r"\d+[a-zA-Z]?"), "name"] = "Junction " + po.loc[(po.kind == "junction") & po.name.str.fullmatch(r"\d+[a-zA-Z]?"), "name"]
po.loc[(po.kind == "gp") & (po.name == ""), "name"] = "GP surgery"
pl.append(po.assign(info="")[["kind", "name", "lat", "lon", "info"]])
places = pd.concat(pl, ignore_index=True); places["lat"] = places.lat.round(5); places["lon"] = places.lon.round(5)
places.to_csv(D / "places.csv", index=False)
print("places:", places.kind.value_counts().to_dict())

# ---------- per-postcode extras ----------
pcs = pd.read_csv(D / "postcodes.csv")
st, osm = pd.read_parquet(P_ / "amenities_static.parquet"), pd.read_parquet(P_ / "amenities_osm.parquet")
ex = pcs[["postcode"]].merge(st, on="postcode", how="left").merge(osm[["postcode", "food_drink_800m", "dist_major_road_m"]], on="postcode", how="left")
ex = ex[["postcode", "flood_hm", "flood_any", "bus_stops_500m", "food_drink_800m", "dist_major_road_m", "rural"]]
ex["flood_hm"] = ex.flood_hm.round(3); ex["flood_any"] = ex.flood_any.round(3); ex["dist_major_road_m"] = ex.dist_major_road_m.round(-1)
ex.to_csv(D / "pc_extras.csv", index=False, float_format="%g")
print("pc_extras rows:", len(ex), "| any flood risk:", f"{(ex.flood_any > 0).mean():.1%}")

# ---------- neighbourhood (LSOA) map ----------
s = pd.read_parquet(P_ / "model_frame_v2.parquet"); latest = s.sale_date.max(); w3 = s[s.sale_date > latest - pd.Timedelta(days=1095)]
el = pd.read_parquet(P_ / "epc_latest.parquet")
ten = duckdb.sql(f"""select upper(trim(postcode)) postcode, coalesce(uprn, address1||'|'||coalesce(address2,'')||'|'||postcode) dw, lodgement_date, lower(tenure) tenure,
        try_cast(current_energy_efficiency as double) sap from read_csv_auto('{RAW}/epc_doncaster.csv', all_varchar=true, sample_size=-1)""").df()
ten = ten.sort_values("lodgement_date").groupby("dw").tail(1).merge(pcs[["postcode", "lsoa21"]], on="postcode", how="inner")
homes = ten.groupby("postcode").size().rename("homes").reset_index().merge(ex[["postcode", "flood_hm"]], on="postcode").merge(pcs[["postcode", "lsoa21"]], on="postcode")
pcx = pcs.merge(st[["postcode", "dist_rail_km"]], on="postcode", how="left")
geo = json.load(open(RAW / "boundaries/lsoa21_doncaster_bsc.geojson"))
rows = []
for f in geo["features"]:
    c = f["properties"]["LSOA21CD"]; g3 = w3[w3.lsoa21 == c]; t = ten[ten.lsoa21 == c]
    known = t[t.tenure.isin(["owner-occupied", "rented (private)", "rented (social)"])]; h = homes[homes.lsoa21 == c]; px = pcx[pcx.lsoa21 == c]
    fa = g3[g3.floor_area.notna()]
    gm = f["geometry"]; polys = gm["coordinates"] if gm["type"] == "MultiPolygon" else [gm["coordinates"]]
    polys = [[[[round(x, 4), round(y, 4)] for x, y in ring] for ring in poly] for poly in polys]
    rows.append(dict(lsoa21=c, ward=(px.ward.mode().iloc[0] if len(px) else ""), area_type=f["properties"]["RUC21NM"],
                     sales_3y=len(g3), median_price=int(g3.price.median()) if len(g3) >= 10 else "",
                     price_per_m2=int(np.exp(np.median(np.log(fa.price / fa.floor_area)))) if len(fa) >= 10 else "",
                     imd_score=round(float(px.imd_score.mean()), 1) if len(px) else "",
                     flood_pct=round(100 * float(np.average(h.flood_hm, weights=h.homes)), 1) if h.homes.sum() >= 30 else "",
                     private_rented_pct=round(100 * (known.tenure == "rented (private)").mean(), 1) if len(known) >= 30 else "",
                     epc_below_c_pct=round(100 * (t.sap.dropna() < 69).mean(), 1) if t.sap.notna().sum() >= 30 else "",
                     dist_rail_km=round(float(px.dist_rail_km.median()), 1) if len(px) else "",
                     geom=json.dumps(polys, separators=(",", ":"))))
json.dump(rows, open(D / "lsoa_map.json", "w"), separators=(",", ":"))
lm = pd.DataFrame(rows).drop(columns="geom")
print("lsoa rows:", len(lm), "| size KB:", round((D / "lsoa_map.json").stat().st_size / 1024))
print(lm.replace("", np.nan).describe().T[["count", "min", "50%", "max"]].round(1))

# ---------- other data layers tested (from model_v3.py) ----------
m3 = json.load(open(ROOT / "outputs/metrics_v3_layers.json"))["summary"]
LBL = {"v2_full": "Current model (v2)", "flood": "+ flood risk (Environment Agency)", "transport": "+ station distance and bus stops (NaPTAN)",
       "schools": "+ distance to schools and to a Good or Outstanding primary (DfE, Ofsted)",
       "osm": "+ supermarkets, parks, GPs, pubs and cafés, motorway junctions, main roads (OpenStreetMap)",
       "rural": "+ urban or rural neighbourhood (ONS)", "all": "+ all of the above"}
pd.DataFrame([dict(layer=k, label=LBL[k], mdape_mean=round(v["mdape_mean"], 5), gain_pts=round(v["gain_pts"], 3), gain_sd=round(v["gain_sd"], 3))
              for k, v in m3.items()]).to_csv(D / "layer_tests.csv", index=False)
print(open(D / "layer_tests.csv").read())
