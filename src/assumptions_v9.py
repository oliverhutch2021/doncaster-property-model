"""Add the opportunity-cost rates to config/assumptions.csv if they aren't there (it never overwrites: the current rates
are kept in that file, so rerunning this can't put back an old value).
Both checked 9 Oct 2026: the 10-year gilt is the default comparison for area returns (a long hold, matched to the 10-year
growth figures); Bank Rate is the cash alternative."""
import csv, pathlib
F = pathlib.Path(__file__).resolve().parents[1] / "config/assumptions.csv"     # the one assumptions file (src/apply_assumptions.py copies it to the dashboard)
NEW = [("opp_gilt_10y", "Opportunity cost: 10-year gilt yield", 5.48, "pct", "UK 10-year government bond yield at the close on 8 Oct 2026 (YCharts); it touched 5.53% that day, its highest since 2007 (Reuters, via Vantage Markets)"),
       ("hold_years", "Holding period (spreads buying and selling costs in area returns)", 10, "years", "Assumption - edit"),
       ("risk_tenant_pct", "Risk allowance: rent arrears, voids and damage in a typical area", 3.75, "pct of rent",
        "Rent guarantee insurance typically costs 2.5% to 5% of annual rent (August, March 2026): the midpoint. Scaled by Doncaster's landlord court claims against England's and by each area's anti-social behaviour and deprivation (assumption - edit)"),
       ("risk_flood_extra", "Risk allowance: extra landlord insurance for a home at flood risk", 445, "GBP per year",
        "Scenario, not a price: get a landlord insurance quote. A typical let falls outside Flood Re, whose criteria need the policyholder or their family to live in the home some of the time or it to be empty (eligibility criterion 2), so its cover is priced on the open market. Before Flood Re (2016), homes in high flood-risk areas with no claims were quoted 148% above the market average (£524 against £211, Flood Re), applied here to the £300 landlord insurance; previously flooded homes cost far more, medium-risk homes usually less (assumption - edit)"),
       ("risk_downturn_years", "Risk allowance: one house-price downturn every", 30, "years",
        "Doncaster's prices fell once in the 31 years of Land Registry data since 1995 (2008 to 2013); each area loses its own 2008 fall once in this many years (assumption - edit)"),
       ("opp_bank_rate", "Opportunity cost: Bank Rate (cash)", 3.75, "pct", "Bank of England Bank Rate, held at 3.75% on 17 Sep 2026; next decision 5 Nov 2026")]
rows = list(csv.DictReader(open(F, newline="", encoding="utf-8"))); keys = {r["key"]: r for r in rows}
for k, l, v, u, s in NEW:                     # adds what's missing, never overwrites: rates are kept up to date in config/assumptions.csv itself
    if k not in keys: rows.append(dict(key=k, label=l, value=str(float(v)), unit=u, source=s))
with open(F, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["key", "label", "value", "unit", "source"], lineterminator="\n"); w.writeheader(); w.writerows(rows)
print(len(rows), "assumptions")
