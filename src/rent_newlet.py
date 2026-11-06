"""Provisional new-let rent adjustment (dashboard version 32). Turns the ONS-based rent, an average of rents being
paid, into an estimate of what a new tenancy would go for, in two measured or reasoned steps. Provisional until it is
tested on observed lettings (src/rent_fit.py, on HMRC Valuation Office or listings data).

1. Mix: the formula anchors ONS's average rent for a type to the average price of that type in Doncaster. Homes that
   are privately rented are cheaper than the average home of their type, so the anchor sets every rent too low. For
   each type, the value of the latest certificate per address since 2016 is estimated as the 2024+ median £/m2 of its
   type in its LSOA x its floor area; privately rented homes (EPC tenure) are compared with all homes, and the gap is
   carried into rent through the formula's slope: mix = (value of all / value of rented) ^ beta.
2. New-let premium: ONS includes sitting tenants, whose rents are reset to the market less often than they change. If a
   share p of tenancies reprice to market each year and market rents grow at g a year, rents paid settle at
   new-let / (1 + premium) with premium = (1 - (1 - p) / (1 + g)) / p - 1. g is Doncaster's ONS growth over the last
   two years; p = 0.30 is an assumption (English Housing Survey 2023-24: 20% of private renters moved in within the
   last year; some sitting tenants are also moved to market rents). The premium falls as rent growth slows.
Check, not used in the figure: Zoopla's new-let rent for Doncaster (Sep 2025) against the formula run to Zoopla's
typical buy-to-let price, with the terraced anchor.

Output: outputs/dash2/rent_newlet.csv"""
import pathlib
import numpy as np, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]; D = ROOT / "outputs/dash2"
P_REPRICE = 0.30
BUILT = {"Detached": "D", "Semi-Detached": "S", "Mid-Terrace": "T", "End-Terrace": "T", "Enclosed Mid-Terrace": "T", "Enclosed End-Terrace": "T"}
NAME = {"D": "detached", "S": "semi-detached", "T": "terraced", "F": "flats and maisonettes"}

rm = pd.read_csv(D / "rent_model.csv").set_index("key").value.astype(float); beta = rm["beta"]

# ---- 1. mix: privately rented homes against all homes of the type ----
pc = pd.read_csv(ROOT / "data/raw/postcodes.csv", dtype=str, usecols=["postcode", "lsoa21"]).drop_duplicates("postcode")
e = pd.read_csv(ROOT / "data/raw/epc_doncaster.csv", dtype=str, usecols=["postcode", "address1", "lodgement_date", "tenure", "property_type", "built_form", "total_floor_area"])
e["ld"] = pd.to_datetime(e.lodgement_date, errors="coerce"); e["area"] = pd.to_numeric(e.total_floor_area, errors="coerce")
e = e.sort_values("ld").drop_duplicates(["postcode", "address1"], keep="last")
e = e[(e.ld >= "2016-01-01") & e.area.between(20, 400)].merge(pc, on="postcode", how="left")
e["t"] = np.where(e.property_type.isin(["Flat", "Maisonette"]), "F", e.built_form.map(BUILT))
e["rented"] = e.tenure.str.lower().str.contains("private", na=False)
mf = pd.read_parquet(ROOT / "data/processed/model_frame_v7.parquet", columns=["postcode", "sale_date", "price", "property_type", "floor_area"])
mf = mf[(mf.sale_date >= "2024-01-01") & mf.floor_area.between(20, 400)].merge(pc, on="postcode", how="left")
mf["lpp"] = np.log(mf.price / mf.floor_area)
rows = []
for t in "DSTF":
    lv = mf[mf.property_type == t].groupby("lsoa21").lpp.agg(["median", "size"]); lv = lv[lv["size"] >= 3]["median"]
    s = e[e.t == t].merge(lv.rename("lpp"), left_on="lsoa21", right_index=True, how="inner")
    lval = s.lpp + np.log(s.area)
    v_all, v_rent = float(np.exp(lval.mean())), float(np.exp(lval[s.rented].mean()))
    mix = (v_all / v_rent) ** beta
    rows.append((f"mix_{t}", round(mix, 4), f"Rent adjustment for the rented mix, {NAME[t]}: (value of all ÷ value of privately rented)^{beta:.3f}",
                 f"EPC tenure, latest certificate per address 2016+ (n={len(s):,}, {int(s.rented.sum()):,} privately rented); values from 2024+ LSOA £/m² x floor area"))
    print(f"{t}: n {len(s):6d} rented {int(s.rented.sum()):5d}  value all {v_all:,.0f} rented {v_rent:,.0f}  ratio {v_rent / v_all:.3f}  mix x{mix:.3f}")

# ---- 2. new-let premium from Doncaster's own rent growth ----
r = pd.read_csv(D / "rents.csv"); a = r[r.series == "all"].set_index("month").monthly_rent
last = a.index.max(); ago = str(pd.Period(last, "M") - 24)
g = (a[last] / a[ago]) ** 0.5 - 1
prem = (1 - (1 - P_REPRICE) / (1 + g)) / P_REPRICE - 1
print(f"growth {ago} to {last}: {g:.2%} a year; premium at p={P_REPRICE}: {prem:.2%}")
rows += [("reprice_share", P_REPRICE, "Share of private tenancies whose rent is reset to the market each year (assumption)",
          "English Housing Survey 2023-24: 20% of private renters moved in within the last year, plus sitting tenants moved to market rents"),
         ("rent_growth_2y", round(g, 4), f"Doncaster rent growth a year, {pd.Period(ago, 'M').strftime('%b %Y')} to {pd.Period(last, 'M').strftime('%b %Y')}", "ONS Price Index of Private Rents, all homes"),
         ("newlet_premium", round(prem, 4), "New-let rent over rent being paid: (1 - (1 - p) / (1 + g)) / p - 1", "Same"),
         ("as_of", last, "Month of the ONS rents used", "ONS Price Index of Private Rents")]

# ---- check (not used): Zoopla's Doncaster new-let rent against the formula at Zoopla's typical buy-to-let price ----
Z_RENT, Z_PRICE = 738, 123134                  # Zoopla, best buy-to-let locations, data to September 2025
h = pd.read_csv(ROOT / "data/raw/ukhpi/UK-HPI-full-file-2026-07.csv", usecols=["Date", "RegionName", "TerracedPrice"])
h = h[h.RegionName == "Doncaster"]; h["m"] = pd.to_datetime(h.Date, dayfirst=True).dt.strftime("%Y-%m")
ons_t = r[(r.series == "Terraced") & (r.month == "2025-09")].monthly_rent.iloc[0]; hp_t = h[h.m == "2025-09"].TerracedPrice.iloc[0]
zcheck = Z_RENT / (ons_t * (Z_PRICE / hp_t) ** beta)
rows.append(("check_zoopla_terraced", round(zcheck, 4), "Check only: Zoopla's Doncaster new-let rent ÷ the formula at Zoopla's buy-to-let price, terraced anchor (Sep 2025)",
             "Zoopla, highest-yielding buy-to-let areas, data to Sep 2025; ONS and UK HPI Doncaster terraced, Sep 2025"))
print(f"check: Zoopla Doncaster / formula (terraced anchor) = {zcheck:.3f}; this script's terraced factor = {rows[2][1] * (1 + prem):.3f}")
pd.DataFrame(rows, columns=["key", "value", "label", "source"]).to_csv(D / "rent_newlet.csv", index=False)
print("wrote", D / "rent_newlet.csv")
