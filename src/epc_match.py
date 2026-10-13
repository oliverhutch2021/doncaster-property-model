"""Match Energy Performance Certificates (EPC) to Land Registry sales.

Neither dataset shares an ID, so we match on postcode + address:
  1. Within the same postcode, the set of numbers in the address must be identical
     (flat number + house number, e.g. {"8","45","47"} for "Flat 8, 45-47 Main Street").
     Using the whole set stops "1" matching "11" or "Flat 1, 12" matching "12".
  2. Named houses with no numbers match when the house name appears in the EPC address.
  3. If several EPC dwellings still match, keep those whose address contains the sale's street.

Each dwelling can have several certificates over time. For each sale:
  - physical attributes (floor area, rooms, built form, age band, bungalow) come from the latest certificate
    lodged up to 90 days after the sale, else the earliest one after (size rarely changes);
  - energy-efficiency attributes only come from a certificate lodged ON OR BEFORE the sale date,
    so a post-sale renovation can't leak into the price we're predicting."""
import re, pathlib, numpy as np, pandas as pd, duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
NUM = re.compile(r"\b\d+[A-Z]?\b")
norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", str(s or "").upper())).strip()

def age_mid(band: str):
    """'England and Wales: 1930-1949' -> 1939.5 ; '2021' -> 2021 ; 'before 1900' -> 1890."""
    if band is None or pd.isna(band): return np.nan
    b = str(band)
    if "before 1900" in b: return 1890.0
    yrs = [int(y) for y in re.findall(r"(1[89]\d\d|20\d\d)", b)]
    return float(np.mean(yrs)) if yrs else np.nan

def load_epc() -> pd.DataFrame:
    e = duckdb.sql(f"""select certificate_number, address1, address2, address3, upper(trim(postcode)) postcode, uprn,
            cast(lodgement_date as date) lodgement_date, property_type epc_type, built_form, construction_age_band,
            try_cast(total_floor_area as double) floor_area, try_cast(number_habitable_rooms as double) rooms,
            try_cast(current_energy_efficiency as double) sap_current, try_cast(potential_energy_efficiency as double) sap_potential,
            current_energy_rating, try_cast(extension_count as double) AS "extensions", mains_gas_flag, tenure AS epc_tenure, transaction_type
        from read_csv_auto('{ROOT}/data/raw/epc_doncaster.csv', all_varchar=true, sample_size=-1)""").df()
    e["addr"] = (e.address1.fillna("") + " " + e.address2.fillna("") + " " + e.address3.fillna("")).map(norm)
    e["nums"] = e.addr.map(lambda a: frozenset(NUM.findall(a)))
    e["dwelling"] = e.uprn.where(e.uprn.notna() & (e.uprn != ""), e.postcode + "|" + e.addr)
    e["age_year"] = e.construction_age_band.map(age_mid)
    e.loc[(e.floor_area < 15) | (e.floor_area > 1000), "floor_area"] = np.nan
    e.loc[(e.rooms < 1) | (e.rooms > 20), "rooms"] = np.nan
    e["lodgement_date"] = pd.to_datetime(e.lodgement_date)
    return e

def match(sales: pd.DataFrame, e: pd.DataFrame) -> pd.DataFrame:
    """Return a table address_key -> dwelling (EPC) for sales whose address matches uniquely."""
    d = sales.drop_duplicates("address_key")[["address_key", "postcode", "saon", "paon", "street"]].copy()
    d["nums"] = (d.saon.fillna("") + " " + d.paon.fillna("")).map(lambda a: frozenset(NUM.findall(norm(a))))
    d["name"] = d.paon.map(norm)
    d["street_n"] = d.street.map(norm)
    dw = e.drop_duplicates("dwelling")[["dwelling", "postcode", "addr", "nums"]]
    by_pc = {pc: g for pc, g in dw.groupby("postcode")}
    out = []
    for r in d.itertuples(index=False):
        g = by_pc.get(r.postcode)
        if g is None: continue
        if r.nums:
            cand = g[g.nums == r.nums]
        else:
            cand = g[(g.nums.map(len) == 0) & g.addr.str.contains(re.escape(r.name), regex=True)] if r.name else g.iloc[0:0]
        if len(cand) > 1 and r.street_n:
            first = r.street_n.split(" ")[0]
            cand = cand[cand.addr.str.contains(r"\b" + re.escape(first) + r"\b", regex=True)]
        if cand.dwelling.nunique() == 1:
            out.append((r.address_key, cand.dwelling.iloc[0]))
    return pd.DataFrame(out, columns=["address_key", "dwelling"])

PHYS = ["floor_area", "rooms", "epc_type", "built_form", "age_year", "extensions"]
ENER = ["sap_current", "sap_potential", "mains_gas_flag"]

def attach(sales: pd.DataFrame, e: pd.DataFrame, m: pd.DataFrame) -> pd.DataFrame:
    s = sales.merge(m, on="address_key", how="left")
    certs = e.sort_values("lodgement_date")
    certs_by = {k: g for k, g in certs.groupby("dwelling")}
    phys, ener = [], []
    for r in s[["dwelling", "sale_date"]].itertuples(index=False):
        g = certs_by.get(r.dwelling) if isinstance(r.dwelling, str) else None
        if g is None:
            phys.append([np.nan] * len(PHYS) + [np.nan]); ener.append([np.nan] * len(ENER)); continue
        before = g[g.lodgement_date <= r.sale_date + pd.Timedelta(days=90)]
        p = before.iloc[-1] if len(before) else g.iloc[0]
        phys.append([p[c] for c in PHYS] + [(r.sale_date - p.lodgement_date).days])
        eb = g[g.lodgement_date <= r.sale_date]
        ener.append([eb.iloc[-1][c] for c in ENER] if len(eb) else [np.nan] * len(ENER))
    s[PHYS + ["epc_days_before_sale"]] = pd.DataFrame(phys, index=s.index)
    s[ENER] = pd.DataFrame(ener, index=s.index)
    s["sap_gap"] = s.sap_potential - s.sap_current
    s["bungalow"] = (s.epc_type == "Bungalow").astype(float).where(s.epc_type.notna())
    s["built_form_code"] = s.built_form.map({"Detached": 0, "Semi-Detached": 1, "End-Terrace": 2, "Mid-Terrace": 3,
                                             "Enclosed End-Terrace": 4, "Enclosed Mid-Terrace": 5})
    s["mains_gas"] = s.mains_gas_flag.map({"Y": 1.0, "N": 0.0})
    return s

if __name__ == "__main__":
    con = duckdb.connect(str(ROOT / "data/processed/doncaster.duckdb"))
    sales = con.execute("select * from sales_seq").df()
    sales["sale_date"] = pd.to_datetime(sales.sale_date)
    e = load_epc()
    m = match(sales, e)
    s = attach(sales, e, m)
    recent = s[s.sale_date >= "2015-01-01"]
    print(f"EPC certificates: {len(e):,}  dwellings: {e.dwelling.nunique():,}")
    print(f"sale dwellings matched: {len(m):,} of {sales.address_key.nunique():,}")
    print(f"2015+ sales with floor area: {recent.floor_area.notna().mean():.1%}  with pre-sale energy rating: {recent.sap_current.notna().mean():.1%}")
    print("rows check (must equal sales):", len(s), len(sales))
    s.drop(columns=["epc_type", "built_form", "mains_gas_flag"]).to_parquet(ROOT / "data/processed/sales_epc.parquet")
    # latest certificate per dwelling, for the dashboard's address lookup
    last = e.sort_values("lodgement_date").groupby("dwelling").tail(1)
    last[["postcode", "address1", "address2", "lodgement_date", "epc_type", "built_form", "age_year", "floor_area", "rooms",
          "sap_current", "sap_potential", "current_energy_rating", "mains_gas_flag", "extensions"]].to_parquet(ROOT / "data/processed/epc_latest.parquet")
