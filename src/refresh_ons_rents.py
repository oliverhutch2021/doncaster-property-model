"""Bring the ONS rents up to a new monthly release without rerunning the whole pipeline (which needs the raw EPC and
Land Registry files). Rewrites outputs/dash2/rents.csv from the Doncaster rows of data/raw/pipr.xlsx (the Price Index of
Private Rents, src/fetch_data.sh), recomputes the new-let premium rows of outputs/dash2/rent_newlet.csv with
src/rent_newlet.py's formula (the rented-mix rows, which need the EPC file, are kept), and prints the 10- and 5-year
growth for config/assumptions.csv, which is edited by hand. The rent model's anchors (outputs/dash2/rent_model.csv) are
left on the month they were fitted with, since they pair each rent with the house prices of the same period."""
import pathlib, sys
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]; D = ROOT / "outputs/dash2"
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/raw/pipr.xlsx"
COLS = {"all": "Rental price", "1 bed": "Rental price one bed", "2 bed": "Rental price two bed", "3 bed": "Rental price three bed", "4+ bed": "Rental price four or more bed",
        "Detached": "Rental price detached", "Semi-detached": "Rental price semidetached", "Terraced": "Rental price terraced", "Flat/maisonette": "Rental price flat maisonette"}

t = pd.read_excel(SRC, sheet_name="Table 1", header=2)
d = t[t["Area code"] == "E08000017"].copy(); d["m"] = pd.to_datetime(d["Time period"]).dt.strftime("%Y-%m")
for c in COLS.values(): d[c] = pd.to_numeric(d[c], errors="coerce")
out = pd.DataFrame([[r.m, k, int(r[v])] for _, r in d.iterrows() for k, v in COLS.items() if pd.notna(r[v])], columns=["month", "series", "monthly_rent"])
out.to_csv(D / "rents.csv", index=False)
a = out[out.series == "all"].set_index("month").monthly_rent; last = a.index.max()
ago = lambda y: str(pd.Period(last, "M") - 12 * y)
cagr = lambda y: (a[last] / a[ago(y)]) ** (1 / y) - 1
print(f"wrote rents.csv to {last}; Doncaster rent growth a year: 10y {cagr(10):.2%} ({ago(10)} to {last}), 5y {cagr(5):.2%}")

# new-let premium, as in src/rent_newlet.py: premium = (1 - (1 - p) / (1 + g)) / p - 1, g = growth over the last 2 years
nl = pd.read_csv(D / "rent_newlet.csv", dtype=str).set_index("key")
p, g = float(nl.loc["reprice_share", "value"]), cagr(2)
prem = (1 - (1 - p) / (1 + g)) / p - 1
nl.loc["rent_growth_2y", ["value", "label"]] = [str(round(g, 4)), f"Doncaster rent growth a year, {pd.Period(ago(2), 'M').strftime('%b %Y')} to {pd.Period(last, 'M').strftime('%b %Y')}"]
nl.loc["newlet_premium", "value"] = str(round(prem, 4)); nl.loc["as_of", "value"] = last
nl.reset_index().to_csv(D / "rent_newlet.csv", index=False)
print(f"rent_newlet.csv: growth {g:.2%} a year, new-let premium {prem:.2%}")
