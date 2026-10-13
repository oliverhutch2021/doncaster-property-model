"""Look up every Doncaster sale postcode on postcodes.io (open ONS-derived data).
Output: data/raw/postcodes.csv with lat/long, LSOA/MSOA codes, ward, and status for each postcode."""
import csv, json, sys, time, urllib.request, urllib.parse, duckdb, pathlib
RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
pcs = [r[0] for r in duckdb.sql(f"""
    select distinct postcode from read_csv_auto(['{RAW}/ppd_doncaster.csv','{RAW}/ppd_doncaster_1995_2014.csv'], union_by_name=true)
    where postcode is not null and postcode <> ''""").fetchall()]
print(len(pcs), "postcodes")
fields = ["postcode","latitude","longitude","lsoa21","msoa21","lsoa_name","ward","parish","bua","terminated"]
rows = []
def post(batch, url):
    req = urllib.request.Request(url, data=json.dumps({"postcodes": batch}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["result"]
missing = []
for i in range(0, len(pcs), 100):
    batch = pcs[i:i+100]
    for item in post(batch, "https://api.postcodes.io/postcodes"):
        r = item["result"]
        if r is None:
            missing.append(item["query"]); continue
        c = r.get("codes", {})
        rows.append([r["postcode"], r["latitude"], r["longitude"], c.get("lsoa21") or c.get("lsoa"), c.get("msoa21") or c.get("msoa"),
                     r.get("lsoa21") or r.get("lsoa"), r.get("admin_ward"), r.get("parish"), r.get("built_up_area"), 0])
    time.sleep(0.1)
# terminated (retired) postcodes still have a location
for pc in missing:
    try:
        with urllib.request.urlopen("https://api.postcodes.io/terminated_postcodes/" + urllib.parse.quote(pc), timeout=30) as r:
            t = json.load(r)["result"]
        rows.append([t["postcode"], t["latitude"], t["longitude"], None, None, None, None, None, None, 1])
    except Exception:
        rows.append([pc, None, None, None, None, None, None, None, None, 1])
with open(RAW / "postcodes.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(fields); w.writerows(rows)
print("written", len(rows), "missing from live API:", len(missing))
