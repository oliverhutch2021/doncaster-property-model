"""Pull live asking rents for Doncaster from the PropertyData API and keep a private, tidy copy.

Why: the dashboard's rent estimate is built on ONS's average of rents being paid, which lags what a new tenancy
goes for. This builds the dataset to measure that properly: every live long-let listing in Doncaster's postcode
districts, pulled repeatedly, so the rent model can be fitted and tested on local new-let rents (src/rent_fit.py).

Terms (propertydata.co.uk/api/terms, read before use): data may be used in your own analysis and app, may not be
redistributed, and may be stored for at most 60 days. So everything under data/private/ is git-ignored and
`--purge` deletes raw pulls and listing rows older than 60 days; only derived summaries (counts, medians, model
parameters) are kept for longer.

The key is read from the PROPERTYDATA_KEY environment variable; never put it in a file or a chat.
  PowerShell:  $env:PROPERTYDATA_KEY = "..."      then      python src/fetch_rents.py --test

  --test            two calls (2 credits): DN6 unfiltered, then DN6 3-bed semis; prints the response shape so we
                    know whether each listing carries bedrooms, type and coordinates before spending more
  --pull            one unfiltered call per district (13 credits); add --split to also call each bedrooms x type
                    cell (260 more), only needed if the unfiltered reply doesn't carry per-listing attributes
  --summarise       derived tables from everything pulled so far (kept indefinitely)
  --purge           delete raw replies and listing rows older than 60 days
"""
import argparse, csv, datetime as dt, json, os, pathlib, sys, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRIV = ROOT / "data/private/rents"; RAW = PRIV / "raw"; LISTINGS = PRIV / "listings_all.csv"
SUMMARY_DIR = ROOT / "outputs/private"; SUMMARY = SUMMARY_DIR / "rents_summary.csv"
API = "https://api.propertydata.co.uk/rents"
DISTRICTS = ["DN1", "DN2", "DN3", "DN4", "DN5", "DN6", "DN7", "DN8", "DN9", "DN10", "DN11", "DN12", "S64"]
BEDS = [1, 2, 3, 4, 5]
TYPES = ["flat", "terraced_house", "semi-detached_house", "detached_house"]
KEEP_DAYS = 60
PAUSE = 0.6            # seconds between calls
FIELDS = ["pull_date", "pulled_at", "district", "query_beds", "query_type", "price_pw", "price_pcm", "bedrooms", "type",
          "lat", "lng", "distance", "extra"]


def key():
    k = os.environ.get("PROPERTYDATA_KEY", "").strip()
    if not k: sys.exit("Set the PROPERTYDATA_KEY environment variable first (never paste the key into a file or chat).")
    return k


def call(params, label):
    """One GET; saves the reply under data/private/rents/raw/ and returns it parsed. Stops on any API error."""
    RAW.mkdir(parents=True, exist_ok=True)
    q = {"key": key(), **params}
    url = API + "?" + urllib.parse.urlencode(q)
    t0 = time.time()
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "doncaster-property-model rent study"}), timeout=60) as r:
        body = r.read()
    reply = json.loads(body)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (RAW / f"{stamp}_{label}.json").write_bytes(body)
    if reply.get("status") != "success":
        sys.exit(f"API error for {label}: {reply.get('message') or reply}")
    print(f"  {label}: ok in {time.time() - t0:.1f}s")
    time.sleep(PAUSE)
    return reply


def points(reply):
    """The per-listing rows in a reply, wherever the API puts them (data.raw_data or data.long_let.raw_data)."""
    d = reply.get("data") or {}
    if isinstance(d, dict) and isinstance(d.get("raw_data"), list): return d["raw_data"], d
    for v in (d.values() if isinstance(d, dict) else []):
        if isinstance(v, dict) and isinstance(v.get("raw_data"), list): return v["raw_data"], v
    return [], d


def rows_from(reply, district, qbeds, qtype, pull_date, pulled_at):
    out = []
    pts, _ = points(reply)
    for p in pts:
        if not isinstance(p, dict): continue
        pw = p.get("price")
        try: pw = float(pw)
        except (TypeError, ValueError): continue
        known = {"price", "bedrooms", "type", "lat", "lng", "distance"}
        extra = {k: v for k, v in p.items() if k not in known}
        out.append(dict(pull_date=pull_date, pulled_at=pulled_at, district=district, query_beds=qbeds, query_type=qtype,
                        price_pw=pw, price_pcm=round(pw * 52 / 12, 2), bedrooms=p.get("bedrooms", ""), type=p.get("type", ""),
                        lat=p.get("lat", ""), lng=p.get("lng", ""), distance=p.get("distance", ""), extra=json.dumps(extra) if extra else ""))
    return out


def append(rows):
    LISTINGS.parent.mkdir(parents=True, exist_ok=True)
    new = not LISTINGS.exists()
    with open(LISTINGS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new: w.writeheader()
        w.writerows(rows)


def describe(reply, label):
    pts, d = points(reply)
    print(f"\n== {label}")
    print("top-level keys:", sorted(k for k in reply if k != "data"))
    print("data keys:", sorted(d.keys()) if isinstance(d, dict) else type(d).__name__)
    for k in ("points_analysed", "average", "radius", "70pc_range", "80pc_range", "90pc_range", "100pc_range"):
        if isinstance(d, dict) and k in d: print(f"  {k}: {d[k]}")
    print(f"listings returned: {len(pts)}")
    if pts:
        print("  per-listing keys:", sorted(pts[0].keys()) if isinstance(pts[0], dict) else type(pts[0]).__name__)
        for p in pts[:3]: print("  e.g.", p)
        have = lambda k: sum(1 for p in pts if isinstance(p, dict) and p.get(k) not in (None, ""))
        print(f"  with bedrooms: {have('bedrooms')}/{len(pts)}, with type: {have('type')}/{len(pts)}, with lat/lng: {have('lat')}/{len(pts)}")


def test():
    a = call({"postcode": "DN6"}, "DN6_test"); describe(a, "DN6, no filters (1 credit)")
    b = call({"postcode": "DN6", "bedrooms": 3, "type": "semi-detached_house"}, "DN6_3bed_semi_test"); describe(b, "DN6, 3-bed semis (1 credit)")
    pts, _ = points(a)
    if pts and all(isinstance(p, dict) and p.get("bedrooms") not in (None, "") and p.get("type") for p in pts[:20]):
        print("\nEach listing carries bedrooms and type: a full pull is 13 calls (one per district). Run: python src/fetch_rents.py --pull")
    else:
        print("\nListings don't carry bedrooms and type: a full pull needs the bedrooms x type grid. Run: python src/fetch_rents.py --pull --split")


def pull(split):
    pull_date = dt.date.today().isoformat(); pulled_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows, calls = [], 0
    for dist in DISTRICTS:
        r = call({"postcode": dist}, dist); calls += 1
        rows += rows_from(r, dist, "", "", pull_date, pulled_at)
        if split:
            for b in BEDS:
                for t in TYPES:
                    r = call({"postcode": dist, "bedrooms": b, "type": t}, f"{dist}_{b}_{t}"); calls += 1
                    rows += rows_from(r, dist, b, t, pull_date, pulled_at)
    append(rows)
    print(f"\n{calls} calls, {len(rows)} listing rows added to {LISTINGS.relative_to(ROOT)}")


def load_listings():
    if not LISTINGS.exists(): sys.exit("No listings yet: run --pull first.")
    with open(LISTINGS, newline="", encoding="utf-8") as f: return list(csv.DictReader(f))


def dedupe(rows):
    """One row per distinct listing (same place, size, type and price), with first and last pull dates."""
    seen = {}
    for r in rows:
        k = (r["lat"], r["lng"], r["bedrooms"], r["type"], r["price_pcm"], r["district"])
        if k not in seen: seen[k] = {**r, "first_seen": r["pull_date"], "last_seen": r["pull_date"], "pulls": 0}
        s = seen[k]; s["first_seen"] = min(s["first_seen"], r["pull_date"]); s["last_seen"] = max(s["last_seen"], r["pull_date"]); s["pulls"] += 1
    return list(seen.values())


def quantile(xs, q):
    xs = sorted(xs); n = len(xs)
    if not n: return ""
    pos = (n - 1) * q; lo = int(pos); hi = min(lo + 1, n - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def summarise():
    """Derived tables, kept beyond the 60 days: per pull date and district x bedrooms x type, the count and quartiles
    of asking rents (unfiltered calls only, so each listing counts once per pull)."""
    rows = [r for r in load_listings() if r["query_beds"] == "" and r["query_type"] == ""]
    groups = {}
    for r in rows:
        for keyset in ((r["pull_date"], r["district"], r["bedrooms"], r["type"]), (r["pull_date"], r["district"], "all", "all"), (r["pull_date"], "all", r["bedrooms"], r["type"]), (r["pull_date"], "all", "all", "all")):
            groups.setdefault(keyset, []).append(float(r["price_pcm"]))
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["pull_date", "district", "bedrooms", "type", "n", "q25_pcm", "median_pcm", "q75_pcm", "source"])
        for (d, dist, b, t), xs in sorted(groups.items()):
            w.writerow([d, dist, b, t, len(xs), quantile(xs, .25), quantile(xs, .5), quantile(xs, .75), "PropertyData live asking rents (Rightmove, Zoopla, OnTheMarket listings)"])
    print(f"wrote {SUMMARY.relative_to(ROOT)}: {len(groups)} rows from {len(rows)} listing rows over {len({r['pull_date'] for r in rows})} pull dates")


def purge():
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    gone = 0
    for p in RAW.glob("*.json"):
        if p.name[:8] < cutoff.replace("-", ""): p.unlink(); gone += 1
    kept = [r for r in load_listings() if r["pull_date"] >= cutoff] if LISTINGS.exists() else []
    if LISTINGS.exists():
        with open(LISTINGS, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(kept)
    print(f"purged {gone} raw replies older than {cutoff}; {len(kept)} listing rows kept")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true"); ap.add_argument("--pull", action="store_true"); ap.add_argument("--split", action="store_true")
    ap.add_argument("--summarise", action="store_true"); ap.add_argument("--purge", action="store_true")
    a = ap.parse_args()
    if a.test: test()
    elif a.pull: pull(a.split)
    elif a.summarise: summarise()
    elif a.purge: purge()
    else: ap.print_help()
