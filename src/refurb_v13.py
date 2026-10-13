"""Refurbishment costs (v13). Replaces v12's rows. Prices: less.co.uk cost guides (all updated April 2026) at their
Yorkshire prices, plus the Federation of Master Builders' 10% contingency.

What changed from v12, and why:
  1. The guides price by house ("a 3-bed semi"), so their 3-bed figures now apply at the size of a typical Doncaster
     3-bed semi: the median floor area of semis whose certificates show 4 or 5 bedrooms and living rooms (84 m2),
     not at the 72.5 m2 the site assumes. Per-m2 rates fall by about 14%.
  2. A kitchen grows weakly with the home: cost x (floor area / 84)^0.5. In the London Plan's housing standards
     (Housing Design Standards LPG 2023) the kitchen fitments grow at 0.58 of the home's floor area across sizes
     (NDSS floor areas) and the whole living-kitchen-dining space at 0.42.
  3. A rewire grows weakly too, by the same square root: the site gives 8-10 circuits for a 3-bed semi and 15-20 for
     a 5-bed detached, at £150-£300 for each extra circuit, which puts a 5-bed detached (139 m2 in Doncaster: the
     median detached house with 7 bedrooms and living rooms) about 30% above a 3-bed: a power of about 0.5.
  4. Central heating: the boiler is a fixed amount (Yorkshire £1,950); the rest of the 3-bed system (radiators,
     pipes) goes by floor area.
  5. Finish follows the home's value (cheaper homes get cheaper kitchens and bathrooms): the bottom of the guides'
     budget range at Doncaster's 10th-percentile price, the budget average at the median, the mid-range average at
     the 90th percentile, in between by log price. That mapping is an assumption; budget or mid-range can be chosen.
Decorating, plastering and flooring still go by floor area (they follow the walls and floors).
Idempotent: removes the earlier refurb_* and rf_* rows of config/assumptions.csv and writes these in their place."""
import csv, glob, pathlib, numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[1]; D = ROOT / "outputs/dash2"; F = ROOT / "config/assumptions.csv"   # the one assumptions file (src/apply_assumptions.py copies it to the dashboard)
L = "less.co.uk cost guides (Apr 2026)"

# Doncaster sizes from the energy certificates
e = pd.concat([pd.read_csv(f, usecols=["epc_type", "built_form_code", "floor_area", "rooms"]) for f in glob.glob(str(D / "epc_*.csv"))])
h = e[e.epc_type == "House"]
A3 = float(h[(h.built_form_code == 1) & h.rooms.isin([4, 5])].floor_area.median())
A5 = float(h[(h.built_form_code == 0) & (h.rooms == 7)].floor_area.median())
# Doncaster prices, last 12 months of sales
mf = pd.read_parquet(ROOT / "data/processed/model_frame_v7.parquet", columns=["price", "sale_date"])
END = mf.sale_date.max(); p = mf[mf.sale_date > END - pd.DateOffset(months=12)].price
P10, P50, P90 = [float(round(p.quantile(q), -3)) for q in (0.1, 0.5, 0.9)]
# rewire scaling from the circuit counts
rw3 = 6250 * 0.95; rw5 = rw3 + (17.5 - 9) * 225 * 0.95; rw_pow = np.log(rw5 / rw3) / np.log(A5 / A3)
# kitchen scaling from the London Plan standards (fitment lengths against NDSS floor areas, 1p-6p)
gia = [39, 50, 61, 70, 86, 99]; fit = [3730, 4330, 4730, 4730, 5630, 6730]; ldk = [21, 23, 25, 27, 29, 31]
k_fit = np.polyfit(np.log(gia), np.log(fit), 1)[0]; k_ldk = np.polyfit(np.log(gia), np.log(ldk), 1)[0]
print(f"3-bed semi {A3} m2, 5-bed detached {A5} m2; rewire power {rw_pow:.2f}; kitchen fitments {k_fit:.2f}, LDK {k_ldk:.2f}; prices P10 {P10:,.0f} P50 {P50:,.0f} P90 {P90:,.0f} ({END:%b %Y})")

src_area = f"spread over {A3:.0f} m2, the median Doncaster semi with 4-5 bedrooms and living rooms (EPC)"
NEW = [
    ("rf_ref_area", "Refurbishment: floor area the guides' 3-bed prices apply to", A3, "m2",
     f"Median floor area of Doncaster semis whose energy certificates show 4 or 5 bedrooms and living rooms (a typical 3-bed semi; {L} assume 65-80 m2)"),
    ("rf_kitchen_low", "Refurbishment: new kitchen, bottom of budget range", round(5000 * 0.91, -1), "GBP",
     f"{L}: budget kitchen from £5,000, Yorkshire 9% below average"),
    ("rf_kitchen_budget", "Refurbishment: new kitchen, budget", round(6500 * 0.91, -2), "GBP",
     f"{L}: budget kitchen £5,000-£8,000 supplied and fitted (units, worktops, sink, connections); Yorkshire 9% below average"),
    ("rf_kitchen_mid", "Refurbishment: new kitchen, mid-range", 10000, "GBP", f"{L}: Yorkshire mid-range kitchen, 10-12 units, £10,000"),
    ("rf_kitchen_pow", "Refurbishment: kitchen cost grows with floor area to the power", 0.5, "power",
     f"London Plan Housing Design Standards (2023): kitchen fitments grow at {k_fit:.2f} of floor area and living-kitchen-dining space at {k_ldk:.2f} (NDSS sizes); 0.5 between"),
    ("rf_bath_low", "Refurbishment: new bathroom, bottom of budget range", round(2500 * 0.92, -1), "GBP",
     f"{L}: budget bathroom from £2,500, Yorkshire 8% below average"),
    ("rf_bath_budget", "Refurbishment: new bathroom, budget (each)", round(3500 * 0.92, -2), "GBP",
     f"{L}: budget bathroom £2,500-£4,500 (average £3,500), strip-out, suite, tiling, plumbing; Yorkshire 8% below average"),
    ("rf_bath_mid", "Refurbishment: new bathroom, mid-range (each)", 5800, "GBP", f"{L}: Yorkshire mid-range bathroom £5,800"),
    ("rf_finish_p10", "Refurbishment finish: price at which the bottom of the budget range applies", P10, "GBP",
     f"Doncaster 10th-percentile sale price, 12 months to {END:%b %Y} (assumption: finish follows value)"),
    ("rf_finish_p50", "Refurbishment finish: price at which the budget average applies", P50, "GBP",
     f"Doncaster median sale price, 12 months to {END:%b %Y} (assumption)"),
    ("rf_finish_p90", "Refurbishment finish: price at which the mid-range average applies", P90, "GBP",
     f"Doncaster 90th-percentile sale price, 12 months to {END:%b %Y} (assumption)"),
    ("rf_decor", "Refurbishment: decorating", round(3500 * 0.88 / A3), "GBP per m2 of floor",
     f"{L}: 3-bed semi interior £3,500 (£2,500-£4,500), Yorkshire 12% below average, {src_area}"),
    ("rf_floor", "Refurbishment: flooring, fitted", 32, "GBP per m2 of floor",
     f"{L}: Yorkshire mid-range fitted flooring £32/m2 (carpet £20-£45, laminate £15-£40, vinyl £20-£50 nationally)"),
    ("rf_rewire", "Full renovation: rewire, typical 3-bed semi", round(rw3, -1), "GBP",
     f"{L}: 3-bed rewire £4,500-£8,000 (midpoint £6,250), Yorkshire electricians 5% below average"),
    ("rf_rewire_pow", "Full renovation: rewire cost grows with floor area to the power", round(float(rw_pow), 1), "power",
     f"{L}: 8-10 circuits in a 3-bed semi, 15-20 in a 5-bed detached, £150-£300 per extra circuit; 5-bed detached {A5:.0f} m2 in Doncaster (EPC, 7 bedrooms and living rooms)"),
    ("rf_boiler", "Full renovation: new combi boiler (fixed part of the heating)", 1950, "GBP", f"{L}: Yorkshire boiler replacement £1,950"),
    ("rf_heating", "Full renovation: radiators and pipes", round((4100 - 1950) / A3), "GBP per m2 of floor",
     f"{L}: Yorkshire full system, new boiler and 10 radiators, 3-bed, £4,100, less the boiler, {src_area}"),
    ("rf_plaster", "Full renovation: re-skim walls and ceilings", round(2800 * 0.89 / A3), "GBP per m2 of floor",
     f"{L}: 3-bed semi skim incl. ceilings, hall and stairs £2,800 average (£2,000-£4,000), Yorkshire 11% below, {src_area}"),
    ("rf_contingency", "Refurbishment: contingency", 10, "pct of works",
     "Federation of Master Builders (Feb 2026): set aside 10% of the project cost; 15% or more for older homes"),
]
rows = list(csv.DictReader(open(F, newline="", encoding="utf-8")))
drop = lambda k: k.startswith("rf_") or k in {"refurb_light", "refurb_medium", "refurb_full"}
at = next((i for i, r in enumerate(rows) if drop(r["key"])), len(rows))
rows = [r for r in rows if not drop(r["key"])]
rows[at:at] = [dict(key=k, label=l, value=str(float(v)), unit=u, source=s) for k, l, v, u, s in NEW]
with open(F, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["key", "label", "value", "unit", "source"], lineterminator="\n"); w.writeheader(); w.writerows(rows)
for k, l, v, u, s in NEW: print(f"{k:18} {v:>10} {u}")
print(len(rows), "assumptions")
