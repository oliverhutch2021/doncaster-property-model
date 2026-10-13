"""Tenant-risk measures (v11).

1. Landlord possession claims (Ministry of Justice, mortgage and landlord possession statistics, to April-June 2026),
   per 1,000 privately rented households (Census 2021, TS054), over the last four quarters, for Doncaster, Yorkshire
   and The Humber and England, quarterly since 2019:
     standard   claims by private landlords through the standard procedure (includes rent-arrears cases)
     accelerated claims through the accelerated procedure (the paper route for no-fault Section 21 notices, which
                ended on 1 May 2026; it can include social landlords' cases)
     bailiff    repossessions by county court bailiffs after private-landlord and accelerated claims
   Plus where Doncaster ranks among English council areas on the latest four quarters.
2. Anti-social behaviour (police.uk street-level data, the last 12 months available): every report in Doncaster,
   placed in its LSOA by its map point, per 1,000 residents (Census 2021, TS001), for each LSOA and neighbourhood.
Outputs: outputs/dash2/possession.csv, columns asb_12m / asb_rate added to outputs/dash2/neighbourhoods.json and
outputs/dash2/lsoa_map.json, outputs/tenants_v11.json"""
import json, pathlib, time, urllib.request, urllib.parse, ssl, io, numpy as np, pandas as pd
from shapely.geometry import shape, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw"; D = ROOT / "outputs/dash2"; OUT = ROOT / "outputs"
LA = "E08000017"; CTX = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")

# ---------------- 1. possession claims ----------------
pc = pd.read_csv(RAW / "moj_possession/x/LA CSV.csv")
pc = pc[pc.la_code.astype(str).str.match(r"^E0[6-9]")]
ten = pd.read_csv(RAW / "census/ts054_tenure_la.csv")
prs = ten[ten.C2021_TENURE_9_NAME == "Private rented"].set_index("GEOGRAPHY_CODE").OBS_VALUE
pc = pc[pc.la_code.isin(prs.index)]
print(f"{pc.la_code.nunique()} English council areas matched to Census private renting; {pc.year.min()}-{pc.year.max()}")
pick = {"standard": (["Private_Landlord"], "Claims"), "accelerated": (["Accelerated_Landlord"], "Claims"), "bailiff": (["Private_Landlord", "Accelerated_Landlord"], "Repossessions")}
q = pc.assign(t=pc.year.astype(str) + "-" + pc.quarter); ALLQ = sorted(q.t.unique())     # every quarter, so none are skipped when there were no cases
rows, rank = [], {}
for m, (types, act) in pick.items():
    s = q[q.possession_type.isin(types) & (q.possession_action == act)].groupby(["la_code", "region", "t"]).value.sum().unstack("t").fillna(0)
    s = s.reindex(columns=ALLQ, fill_value=0)
    roll = s.T.rolling(4).sum().T                                   # last four quarters
    for name, mask in (("Doncaster", s.index.get_level_values(0) == LA), ("Yorkshire and The Humber", s.index.get_level_values(1) == "Yorkshire and The Humber"), ("England", np.ones(len(s), bool))):
        hh = prs.reindex(s.index.get_level_values(0)[mask]).sum()
        for t in roll.columns[3:]:
            if t < "2019-Q4": continue
            rows.append(dict(area=name, quarter=t, metric=m, rate=round(1000 * roll.loc[mask, t].sum() / hh, 3), count=int(roll.loc[mask, t].sum()), households=int(hh)))
    last = roll.columns[-1]; r = 1000 * roll[last].droplevel(1) / prs.reindex(roll.index.get_level_values(0)).values
    rank[m] = dict(quarter=last, doncaster=float(r[LA]), higher_than_pct=float((r < r[LA]).mean() * 100), median=float(r.median()), n=int(len(r)))
for m, v in rank.items(): rows.append(dict(area="Doncaster", quarter=v["quarter"], metric=m + "_rank", rate=round(v["higher_than_pct"], 1), count=v["n"], households=0))   # share of English areas with a lower rate
pos = pd.DataFrame(rows); pos.to_csv(D / "possession.csv", index=False)
print(pos[pos.quarter == pos.quarter.max()].to_string()); print(json.dumps(rank, indent=1))

# ---------------- 2. anti-social behaviour ----------------
LM = json.load(open(D / "lsoa_map.json")); NB = json.load(open(D / "neighbourhoods.json"))
geo = {r["lsoa21"]: shape({"type": "MultiPolygon", "coordinates": json.loads(r["geom"])}).buffer(0) for r in LM}
boro = unary_union(list(geo.values())).buffer(0.003).simplify(0.004)
ring = list(boro.exterior.coords) if boro.geom_type == "Polygon" else list(max(boro.geoms, key=lambda g: g.area).exterior.coords)
poly = ":".join(f"{y:.4f},{x:.4f}" for x, y in ring)
dates = json.loads(urllib.request.urlopen("https://data.police.uk/api/crimes-street-dates", context=CTX, timeout=60).read())
months = sorted(d["date"] for d in dates)[-12:]
print("police.uk months:", months[0], "to", months[-1], "| polygon points:", len(ring))
pts = []
for mth in months:
    body = urllib.parse.urlencode({"poly": poly, "date": mth}).encode()
    for attempt in range(4):
        try:
            res = json.loads(urllib.request.urlopen(urllib.request.Request("https://data.police.uk/api/crimes-street/anti-social-behaviour", data=body), context=CTX, timeout=120).read()); break
        except Exception as e:
            print("  retry", mth, e); time.sleep(3 * (attempt + 1))
    else: raise SystemExit(f"no data for {mth}")
    pts += [(mth, float(c["location"]["latitude"]), float(c["location"]["longitude"])) for c in res]
    print(f"  {mth}: {len(res):,} reports"); time.sleep(0.5)
names = list(geo); tree = STRtree([geo[k] for k in names]); per = {k: 0 for k in names}; outside = 0
for _, la_, lo_ in pts:
    p = Point(lo_, la_); hit = [names[i] for i in tree.query(p) if geo[names[i]].contains(p)]
    if hit: per[hit[0]] += 1
    else: outside += 1
print(f"{len(pts):,} reports in the area fetched; {len(pts) - outside:,} inside Doncaster's LSOAs")
url = "https://www.nomisweb.co.uk/api/v01/dataset/NM_2021_1.data.csv?date=latest&geography=" + ",".join(names) + "&c2021_restype_3=0&measures=20100&select=geography_code,obs_value"
popd = pd.read_csv(io.StringIO(urllib.request.urlopen(url, context=CTX, timeout=90).read().decode())).set_index("GEOGRAPHY_CODE").OBS_VALUE
pd.DataFrame({"lsoa21": names, "asb_12m": [per[k] for k in names], "residents": [int(popd.get(k, 0)) for k in names]}).to_csv(RAW / "census/asb_lsoa_12m.csv", index=False)
for r in LM: r["asb_12m"] = per[r["lsoa21"]]; r["asb_rate"] = round(1000 * per[r["lsoa21"]] / popd[r["lsoa21"]], 1)
for r in NB:
    ls = names if r["msoa21"] == LA else [x for x in str(r["lsoas"]).split(" ") if x]
    n, res_ = sum(per[x] for x in ls), sum(int(popd[x]) for x in ls)
    r["asb_12m"] = int(n); r["asb_rate"] = round(1000 * n / res_, 1); r["residents"] = int(res_); r["asb_from"], r["asb_to"] = months[0], months[-1]
json.dump(LM, open(D / "lsoa_map.json", "w"), separators=(",", ":")); json.dump(NB, open(D / "neighbourhoods.json", "w"), separators=(",", ":"))
nb = pd.DataFrame(NB).set_index("name")[["asb_12m", "residents", "asb_rate"]].sort_values("asb_rate")
print(nb.to_string())
json.dump(dict(possession_rank=rank, asb=dict(months=[months[0], months[-1]], reports=len(pts), inside=len(pts) - outside,
               doncaster_rate=float(nb.loc["Doncaster", "asb_rate"]))), open(OUT / "tenants_v11.json", "w"), indent=1)
