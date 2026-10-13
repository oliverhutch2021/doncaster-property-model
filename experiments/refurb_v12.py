"""Refurbishment costs (v12): replaces the three unsourced per-m2 guesses (cosmetic £300, kitchen/bathroom £700, full £1,200)
with item costs from less.co.uk's cost guides (all updated April 2026), at their Yorkshire prices.

How each item scales:
  kitchen, bathroom          a fixed amount each (by finish), whatever the size of the home; bathrooms are counted
  decorating, flooring       per m2 of floor (more rooms means more walls and floor)
  rewire, heating, plaster   per m2 of floor, from less.co.uk's 3-bed figures spread over 72.5 m2 (the middle of the
                             65-80 m2 the same site gives for a 3-bed semi)
  contingency                10% of the works (Federation of Master Builders, Feb 2026: 15%+ for older homes)
Yorkshire prices: the site's Yorkshire figure where it gives one for that item; otherwise its national figure less its
stated Yorkshire difference. The site doesn't say whether prices include VAT; the page lets you add it.
Idempotent: removes the old refurb_* rows and writes these in their place."""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "src"))   # kept for the record; imports the pipeline modules from src/
import csv, pathlib
D = pathlib.Path(__file__).resolve().parents[1] / "outputs/dash2"; F = D / "assumptions.csv"
REF = 72.5   # m2, 3-bed semi
L = "less.co.uk cost guides (Apr 2026)"
NEW = [
    ("rf_kitchen_budget", "Refurbishment: new kitchen, budget (each)", round(6500 * 0.91, -2), "GBP",
     f"{L}: budget kitchen £5,000-£8,000 supplied and fitted (units, worktops, sink, connections); Yorkshire 9% below average"),
    ("rf_kitchen_mid", "Refurbishment: new kitchen, mid-range (each)", 10000, "GBP",
     f"{L}: Yorkshire mid-range kitchen, 10-12 units, £10,000"),
    ("rf_bath_budget", "Refurbishment: new bathroom, budget (each)", round(3500 * 0.92, -2), "GBP",
     f"{L}: budget bathroom £2,500-£4,500 (average £3,500), strip-out, suite, tiling, plumbing; Yorkshire 8% below average"),
    ("rf_bath_mid", "Refurbishment: new bathroom, mid-range (each)", 5800, "GBP",
     f"{L}: Yorkshire mid-range bathroom £5,800"),
    ("rf_decor", "Refurbishment: decorating", round(3500 * 0.88 / REF), "GBP per m2 of floor",
     f"{L}: 3-bed semi interior £3,500 (£2,500-£4,500), Yorkshire 12% below average, over {REF} m2"),
    ("rf_floor", "Refurbishment: flooring, fitted", 32, "GBP per m2 of floor",
     f"{L}: Yorkshire mid-range fitted flooring £32/m2 (carpet £20-£45, laminate £15-£40, vinyl £20-£50 nationally)"),
    ("rf_rewire", "Full renovation: rewire", round(6250 * 0.95 / REF), "GBP per m2 of floor",
     f"{L}: 3-bed rewire £4,500-£8,000 (midpoint £6,250), Yorkshire electricians 5% below average, over {REF} m2"),
    ("rf_heating", "Full renovation: central heating (boiler, radiators, pipes)", round(4100 / REF), "GBP per m2 of floor",
     f"{L}: Yorkshire full system, new boiler and 10 radiators, 3-bed, £4,100, over {REF} m2"),
    ("rf_plaster", "Full renovation: re-skim walls and ceilings", round(2800 * 0.89 / REF), "GBP per m2 of floor",
     f"{L}: 3-bed semi skim incl. ceilings, hall and stairs £2,800 average (£2,000-£4,000), Yorkshire 11% below, over {REF} m2"),
    ("rf_contingency", "Refurbishment: contingency", 10, "pct of works",
     "Federation of Master Builders (Feb 2026): set aside 10% of the project cost; 15% or more for older homes"),
]
OLD = {"refurb_light", "refurb_medium", "refurb_full"}
rows = list(csv.DictReader(open(F, newline="", encoding="utf-8")))
new_keys = {k for k, *_ in NEW}
at = next((i for i, r in enumerate(rows) if r["key"] in OLD | new_keys), len(rows))
rows = [r for r in rows if r["key"] not in OLD | new_keys]
rows[at:at] = [dict(key=k, label=l, value=str(float(v)), unit=u, source=s) for k, l, v, u, s in NEW]
with open(F, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["key", "label", "value", "unit", "source"], lineterminator="\n"); w.writeheader(); w.writerows(rows)
for k, l, v, u, s in NEW: print(f"{k:18} {v:>8} {u}")
# worked example: 85 m2, one bathroom, budget finish
A = {k: v for k, _, v, *_ in NEW}; a = 85; c = 1 + A["rf_contingency"] / 100
cos = (A["rf_decor"] + A["rf_floor"]) * a; kb = A["rf_kitchen_budget"] + A["rf_bath_budget"]; full = (A["rf_rewire"] + A["rf_heating"] + A["rf_plaster"]) * a
print(f"85 m2, budget, 1 bathroom, with contingency: cosmetic £{cos*c:,.0f} | kitchen+bathroom £{kb*c:,.0f} | both £{(cos+kb)*c:,.0f} | full £{(cos+kb+full)*c:,.0f}")
print(len(rows), "assumptions")
