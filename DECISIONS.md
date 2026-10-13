# Decision log

Each decision: what I chose, what I rejected, and why. These are the questions an interviewer is likely to ask.

## Data

1. **Standard sales only (category A); 'Other' property type removed.**
   Rejected: keeping category B. Category B includes repossessions, transfers to companies and bulk sales,
   whose prices don't reflect open-market value. With the price bounds and missing postcodes, cleaning removed
   13,140 of 156,349 rows (8%).

2. **Price bounds £10k to £2m.** Removes obvious errors and non-residential deals without trimming real
   Doncaster sales.

3. **One address key per dwelling** (flat number + house number + street + postcode) to link repeat sales.
   Rejected: matching on postcode only, which would merge different homes.

4. **Deduplicate the postcode lookup before joining.** A retired postcode can appear twice (live + terminated),
   which first inflated the joined table by 93 rows. The pipeline now checks that the row count after every join
   equals the clean sales count.

5. **IMD 2025 instead of crime API data.** The deprivation index already contains a crime domain per
   neighbourhood, so police.uk data would mostly duplicate it.

## Time

6. **Quality-adjusted index (hedonic time-dummy)** instead of monthly medians. Medians move when the mix of
   sales changes (more detached homes one month); the index holds type, tenure and neighbourhood fixed.

7. **Index known at valuation time.** For each 2025-26 test month, the index is re-estimated on sales up to
   two months earlier, mimicking publication lag. Rejected: one index fitted on all data, which leaks test-period prices.

8. **Model the index-adjusted price** (log price minus log index). Tree models can't extrapolate a time trend
   beyond the training years; adjusting for the index first lets them focus on location and property effects.

## Features

9. **Local price level from earlier sales only.** Median adjusted price of the same type in the same postcode
   sector over the previous 3 years (and the same LSOA), using a closed-left time window so the sale being
   valued never contributes. NaN when fewer than 5 earlier sales.

10. **Previous sale price IS a feature (changed in v2), but optional.** v1 left it out because a buyer often
    doesn't know it. v2 adds it index-adjusted (last price divided by the index in that month), with years since
    that sale. 28% of test sales have no earlier sale, so the model learns both cases; the dashboard treats it as
    an optional input. It cut median error from 9.6% to 8.7%.

## Models and validation

11. **Train 2015-2023, validate 2024, test Jan 2025 - Aug 2026.** Random splits overstate accuracy for housing
    because neighbouring sales in the same month leak information.

12. **Ridge baseline vs LightGBM.** Ridge with neighbourhood dummies is the interpretable benchmark (a classic
    hedonic model); LightGBM captures interactions (e.g. flats behave differently by area).
    LightGBM won on every metric.

13. **L1 (absolute error) objective.** Median-type loss is less sensitive to the few very large or very small sales.

14. **Early stopping on 2024**, then the same number of trees for the final model.

15. **Smaller model for the dashboard** (31 leaves, learning rate 0.08, 1,496 trees). It runs in the browser and
    loses about 0.25 points of median error (8.9% vs 8.6%). Its JavaScript evaluation matches LightGBM to 5e-8 on
    400 rows, including rows with missing EPC, neighbour, last-sale and local-level values.

## Uncertainty

16. **Split conformal intervals by price band and last-sale status.** The 10th and 90th percentile errors on 2024,
    in five price bands x (last sale known or not), give an 80% range. Homes with no previous sale get a wider
    range because they are harder to value. Checked on the test period: 79.8% coverage.

## Condition

17. **Repeat sales within 3-18 months as refurbishment flips.** Out-of-fold residuals at purchase
    (median -8.5%) and at resale (median +8.0%) set the "needs renovation" and "refurbished" adjustments
    (n = 1,007). Long-hold pairs (5+ years) act as a control: their first-sale residual is +0.8%.
    The residuals come from a model WITHOUT the last-sale features, otherwise the resale price would be
    explained by the purchase price and the condition effect would vanish.
    Limitation: some short resales are not flips (e.g. relocations), which shrinks the estimates towards zero.

## Investment

18. **Doncaster-wide ONS rents** by bedrooms and type. No open street-level rent data exists; area yields are
    labelled indicative and overstate yields in the cheapest areas.

19. **Every cost assumption is visible and editable** in the dashboard, with its source.

## Version 2 additions

20. **EPC matching on postcode + the exact set of address numbers.** "Flat 8, 45-47 Main Street" must
    match {8, 45, 47} exactly, so "1" can't match "11" and "Flat 1, 12" can't match "12". Named houses match on
    the name; ties are broken by street. 57,368 of 80,609 sale dwellings matched; 94% of 2015+ sales have a
    floor area. Rejected: fuzzy string matching, which produced confident wrong matches between neighbours.

21. **Two timing rules for EPC data.** Size, rooms, built form and age come from the latest certificate up to
    90 days after the sale (size rarely changes, and a certificate is often lodged for the sale itself).
    Energy scores only come from certificates lodged on or before the sale date, so a post-sale renovation
    can't leak into the price being predicted.

22. **Nearest-neighbour prices from earlier sales only.** Median index-adjusted price of the 10 nearest
    same-type sales and median price per m² of the 15 nearest sales with a floor area, from the previous
    36 months. Captures street-level effects that postcode sectors average away.

23. **Ablation, one layer at a time.** Every layer was tested on the same test set, so each claimed gain is
    measured, not assumed: EPC gave by far the largest gain (13.2% to 9.7%).

24. **Training clean-up from out-of-fold residuals.** Sales more than 0.8 log points (about 2.2x) away from a
    5-fold out-of-fold prediction were dropped from training only (224 sales, 0.5%; 179 far below). Most look
    like non-market transfers. The test set is untouched, so the reported accuracy is not flattered.

25. **Missing values and thresholds handled exactly as LightGBM does.** The browser evaluator follows each split's
    missing-value rule (None, Zero or NaN) and default direction, because many homes have no EPC, no last sale or
    too few nearby sales. Split thresholds are kept at full precision: rounding them to 6 decimals caused
    differences of up to 0.0023 log points.

26. **Listings are pasted, not scraped.** Rightmove and Zoopla block automated access, and scraping breaks their
    terms. The dashboard reads pasted listing text in the browser (price, rent, bedrooms, type, size, EPC letter,
    postcode, or street + district to suggest postcodes).

27. **EPC address lookup split by postcode district.** The latest certificate per home (90,356 homes) is split
    into 15 district files that load only when needed, so the page doesn't download 7 MB up front.

28. **Buy-to-let tax modelled by owner type.** Personal: tax on rent less costs, with a 20% credit on interest
    (Section 24), and the April 2027 property-income rates (22/42%). Limited company: interest deductible,
    19% corporation tax, extraction not modelled. Lender stress test: 125% (145% for higher-rate taxpayers) at the
    higher of 5.5% or rate + 2 points. All are labelled assumptions with sources.

29. **Area tenure and EPC shares from the EPC register, not the Census.** Each home's latest certificate gives its
    tenure and energy score. This over-represents rented homes (every new tenancy needs a certificate), so the
    shares are labelled "of homes with a certificate" and used for ranking areas, not as counts.

## Version 3: more data, tested before use

30. **Extra layers tested one at a time over 3 seeds.** Flood risk, station and bus access, schools, OpenStreetMap
    amenities and urban/rural class each improved test median error by 0.03 to 0.07 points, against a seed-to-seed
    spread of 0.09 to 0.18 points. That is noise, so none went into the estimate. Out-of-fold residuals by group
    agree: homes in postcodes mostly at high/medium flood risk sell only 0.5% below the model's estimate, and
    distance groups for stations, schools, shops and main roads are within about 0.5%. Nearby sale prices
    already carry these effects. Rejected: adding them anyway, which makes the browser model bigger for no gain.

31. **Shown as information instead.** Investors still need to know about flood risk (insurance, lending), schools
    (tenant demand) and transport, so the dashboard shows them per property and on a neighbourhood map, with a
    flood warning in the buy-to-let notes.

32. **Schools matched in time; other layers are snapshots.** A sale only sees schools open in its year (DfE open
    and close dates). Flood risk (NaFRA2, 2025), stops, Ofsted grades and OpenStreetMap are current, a small look-ahead
    that would only flatter the test, and the layers still didn't help.

33. **Ofsted grades across three frameworks.** Overall effectiveness where given; quality of education for
    Sept 2024 - Nov 2025 inspections, which have no overall grade; report-card achievement after that.
    A third of nearby schools have no graded judgement in the March 2026 data (mostly new academies), and the
    dashboard says so rather than guessing.

34. **Map on 2021 LSOAs, not postcode sectors.** Sector boundaries aren't open data; LSOAs are, and at about
    1,500 people each they show street-level differences sectors hide. Price per m² is the default because
    median price mostly reflects the mix of house types.

## Version 4: following areas that move differently

35. **Diagnosed before fixing.** By predicted price the model is close to calibrated (+1.7% for the cheapest fifth,
    -2.6% for the dearest). By area it is not: 5 of 36 sectors had a bias beyond 2 standard errors (about 2 expected
    by chance), under-valued in rising ex-mining areas and over-valued in Bawtry and Tickhill. An oracle that
    removed each sector's own test bias would only reach 8.5% median error, so most remaining error is
    home-specific (condition, plot, layout), not area drift.

36. **Local residual correction kept; 12-month local prices rejected.** Recomputing neighbour and area levels on the
    last 12 months made the model worse (noisier levels). Correcting the estimate by half the model's median miss
    on the 10 nearest recent sales (sold 60+ days earlier, so already registered) improved every seed and cut the
    spread of area bias from 2.7% to 1.7%. The share and neighbour count were chosen on 2024 with a model trained
    to 2022, so the 2025-26 test is untouched.

37. **Production model trained to 12 months before the valuation month.** The correction needs out-of-sample misses,
    so the dashboard model mirrors the test exactly: trained on sales up to August 2025, with September 2025 -
    August 2026 sales used to measure local drift. Rejected: training on everything and using in-sample residuals,
    which are shrunk towards zero and would under-correct.

## Version 5: more about the home itself

38. **Plot size from title plans.** HM Land Registry's INSPIRE polygons give each freehold title's extent; OS Open UPRN places
    each EPC home (the certificate carries its UPRN) inside one. A block of flats or an estate shares a title, so the
    number of homes on the title is kept too. 98% of EPC homes land in a title. Alone it improved median error by
    0.30 points.

39. **Street and postcode prices.** Median index-adjusted price on the same street (same type) and in the same postcode over
    the previous 5 years, from earlier sales only. Streets carry value that sector and neighbourhood averages blur.

40. **More EPC detail, with the same timing rules.** Wall type, ceiling height and floor level from the certificate nearest
    the sale; insulation, glazing, heating, wood burner and solar only from certificates lodged before it, since these
    change with renovation. They partly capture condition, which the condition setting still covers.

41. **Kept only what helps on top of the rest.** Exact address positions, similar-size neighbours and the council tax band
    mix each helped a little alone but nothing once plot, street and EPC detail were in (dropping each changed error by
    0.00 to 0.02 points), so they were left out to keep the browser model simple.

42. **Settings tuned on 2024 only.** A random search (18 settings) on 2024 validation favoured more regularisation
    (min 80 sales per leaf, L2 = 20, 65% of features per tree). The test period was used once, to confirm.

43. **Browser model chosen for size when accuracy ties.** Candidates within 0.03 points on 2024 are noise apart, so the
    smallest won (31 leaves, 1,107 trees, 2.4 MB). The full-size tuned model is about 0.15 points better but 5x larger.

44. **Explanations are exact SHAP values.** TreeSHAP (Lundberg et al.) runs in the browser on the exported trees with
    their training counts; it matches LightGBM's `pred_contrib` to 6e-9. Features are grouped (size, plot, prices nearby,
    street, energy, last sale...) so the breakdown reads in plain terms.

45. **Council tax band is a cross-check, not an input.** There is no open per-address band data to train on. The check
    compares ranks: where the band sits among the same type and bedrooms in the neighbourhood (VOA counts), against where
    the estimate sits among recent nearby sales.

46. **Saved list in the dashboard's own private store.** Each viewer's saved properties live under their own private path
    in the dashboard's database, so nobody else sees them. "Estimate now" re-runs today's model on the saved details.

## Version 6: extensions, sales history and what-ifs

47. **No open record of extensions, so tested the closest thing.** OS OpenMap Local building outlines (April 2026) give each
    home's footprint; matched through OS Open UPRN, 99.6% of EPC homes land on an outline. Footprint, homes per outline,
    garden size and floor area per footprint changed error by +0.02 points on the untuned model and made the tuned one
    0.10 points worse, so they stay out. Floor area from the certificate already carries most of what an extension adds.

48. **Footprints used as a prompt instead.** Among homes certified since September 2024, 90% of houses have floor area at
    least 0.99 times their footprint per address (bungalows 0.55). An older certificate below that line is flagged as a
    possible extension since, with a request to enter the current floor area.

49. **Monotone floor area rejected.** LightGBM only allows monotone constraints with a loss like Huber, which is about
    0.1 points worse than L1 here. The L1 model already values 15 m² more as a gain for 98.5% of test homes (median +5%),
    so the what-if tool uses it and says so when a small addition reads as no gain.

50. **Last sale filled in automatically.** Each certificate's home is linked to its Land Registry sales through the same
    address matching as training, so picking an address fills the model's last-sale inputs, which were typed by hand before.

51. **What-if costs are sourced guide prices, not quotes.** Yorkshire single-storey £1,350-£2,200/m² and two-storey
    £1,200-£2,000/m² before VAT and fees (less.co.uk, 2026); rear dormer lofts £2,200-£2,800/m² outside London
    (planwatch.co.uk, 2026). On the model's numbers, 15 m² more adds about £665 per m² for a typical house (detached
    £1,150, semi £630, terraced £370), a third of the average price per m², against roughly £2,000/m² to build with VAT.
    Adding a room as well lifts it to about £875 per m². So in Doncaster an extension rarely pays back on resale value
    alone; it makes sense for the space, or where it lifts the rent.
52. **Compared on the same sales, with a publication lag.** Simple methods were scored on the 2025-26 test sales using
    only sales at least two months old (about when Land Registry publishes them; the UK HPI has a similar lag). Indexing
    the last sale with the UK HPI for Doncaster gave 13.0% median error on the 72% of homes with a previous sale (model
    7.8% on the same homes); price per m² of the 10 nearest sales gave 13.6%. Recomputing the model's own local price
    features with the same cut-off moved it from 8.25% to 8.27%, so the reported accuracy doesn't rely on sales that
    wouldn't be public yet. Commercial AVM figures aren't comparable (surveyor benchmarks, US markets, listing data).
53. **Full-size model in the browser.** Versions 4-6 used a smaller model to fit the dashboard's file limit; the full-size
    tuned settings were about 0.15-0.25 points better. Version 7 stores trees compactly: in pre-order the left child is
    always the next node, so only the right child is kept, and default-left, split kind and missing-value handling share
    one number. 2,043 trees of up to 63 leaves fit in 6.9 MB, predictions match LightGBM to 3e-8 on the log scale, SHAP
    values to 1e-8, and an explanation takes about 0.1 s in the browser.
54. **Certificate history kept.** Homes whose latest certificate was for a let (13% of test sales) were over-valued by
    2.7%. Six features from the certificate register, as of the sale date (or the valuation month in the dashboard), fixed
    that (+0.3%) and gained 0.03 points overall with the local correction, better on all 3 seeds. A first run showed
    0.09 points; correcting how same-day certificates were ordered (0.1% of sales) brought it to 0.03, a reminder that
    seed spread understates how much small data changes move these comparisons.
55. **Last-sale premium left out.** A home's residual at its previous sale (from a model without last-sale features,
    folds grouped by home) correlates 0.31 with its next residual, but the current model's test errors are uncorrelated
    with it (-0.001): the index-adjusted last price already carries it. Adding it cost 0.1 points.
56. **Nearest-sales local correction kept.** A smoothed version (every recent sale weighted by distance, age and type,
    shrunk when evidence is thin), tuned on 2024, was no better on 2025-26 (+0.003 points, spread 0.03). The k-nearest
    version was re-tuned on 2024: half of the median miss on the 40 nearest sales. Lease length was not tested: HM Land
    Registry's Registered Leases data needs an account to download.
57. **Year-by-year backtest.** Each year from 2020 is valued by a model trained on sales up to two years earlier
    (early-stopped on the year before), with the price index refitted month by month on sales at least two months old
    and the training prices deflated with it. Median error: 2020 7.8%, 2021 7.7%, 2022 8.0%, 2023 8.4%, 2024 8.2%,
    2025 8.0%, 2026 (to August) 8.0%. The stamp-duty rush and the rate rises didn't break it; 2023 was the hardest
    year. Local price features still use the final index, a small revision effect.
58. **A confidence score, and ranges that follow it.** A small LightGBM model (median of the absolute error) trained on
    2020-23 backtest errors, scaled on 2024, checked on 2025-26: High 4.9% median error, Good 6.6%, Fair 8.3%, Low 11.3%.
    The fixed ranges by price band were right on average (79.4%) but held 93% of prices for the most confident estimates
    and 70% for the least; ranges scaled by the score hold 76-81% at every level and 80.5% overall, about 3 points wider
    at the median. Homes typed in by hand broke it at first: in training, missing certificate details mean an unusual
    home, so the score said 20% where the real error was 11%. They get their own scaling, fitted on 2024 homes with the
    details blanked; on 2025-26 that gives 12% predicted against 11% actual and an 82% range coverage.
59. **Price-level bias measured, and left alone.** The IAAO ratio study gives COD 12.7 (standard: under 15), PRD 1.031
    (0.98-1.03) and PRB -0.06. Grouping by sale price exaggerates regressivity, but indexing the last sale shows almost
    none (PRB +0.007), so part is the model shrinking towards the middle. Shifting estimates by their size (fitted on
    2024) was within noise and made PRB worse; stretching them to make 2024's PRB zero cost 0.71 points of median error
    (spread 0.02). The page reports the checks and says why.
60. **Time stays in the index.** Zillow's approach, time as model features instead of deflating by an index, was 0.79
    points worse here: tree models can't extrapolate past their training years, and the local correction can't make up
    two years of price change. Time features alongside the index were within noise (+0.03, spread 0.12).
61. **Presentation.** The value tab puts the inputs beside a fixed estimate panel (stacked, estimate first, on a phone);
    the listing paste folds away; tabs scroll in one row on a phone; the method is a six-step flow plus short cards;
    narrow screens drop secondary table columns.
62. **Tab links in Safari.** The dashboard's `dash.setLink` also rewrites the frame's address with `history.replaceState`,
    which WebKit browsers refuse inside the dashboard frame ("SecurityError: The operation is insecure"). The tab code
    called it before drawing, so in Safari a tab could stay blank until the next data update. Tabs now draw first and the
    link call is caught; the public copy's stand-in does the same.
63. **Map without d3's geo module.** The d3 built into the Claude dashboard has no `d3-geo` or `d3-polygon`
    (`geoIdentity`, `geoPath` and `polygonContains` are missing), so the neighbourhood map failed there in every browser.
    The public copy bundles full d3, which hid it. The map now does its own fit-to-box projection, SVG path building and
    point-in-polygon test (even-odd fill, so holes still show), and every d3 function the page calls was checked against
    the dashboard's d3 by running the page in that runtime locally.
64. **Areas are neighbourhoods (MSOAs), not postcode sectors.** Named neighbourhoods were chosen: they fit the map's
    LSOA shapes exactly (sector boundaries aren't open data), have names people search for, and hold enough sales for
    steady growth figures. Search still accepts postcodes, sectors, wards and towns. The old sector table is gone; its
    data source stays in the dashboard, unused, until removing it is asked for.
65. **Rents stay borough-wide.** No open source gives private rents below the local authority (ONS PIPR is by local
    authority; listing sites block automated access; the one open neighbourhood rent guide found gives no source).
    Borough rents only, labelled, rather than letting readers type local rents.
66. **Repeat sales for neighbourhood growth.** Medians over 3-year windows (the old sector figures) move with the mix
    of homes sold. A repeat-sales index doesn't, and tracks the UK HPI closely for Doncaster. Thin neighbourhoods borrow
    strength from Doncaster's index through a smoothness penalty chosen by cross-validation.
67. **Opportunity cost.** Total return is compared with what the same cash would earn instead. The default is the
    10-year gilt, matched to the 10-year growth figures and a 10-year hold; Bank Rate is the cash alternative, and
    readers can enter their own rate (for example an expected share return). Buying and selling costs are spread over
    the holding period, so total return is exactly net yield plus growth.
68. **Colours.** Measures with a better and a worse end use the dashboard's diverging ramp (blue better, red worse,
    grey within one step of Doncaster, or of zero for the opportunity cost), in equal steps either side, so a colour
    means the same distance from average on both sides. Prices and the private-rented share have no better end and use
    the blue sequential ramp in sevenths. Flood risk uses grey for none and reds for more.
69. **Light/dark switch.** The page pins the dashboard's theme by setting `data-mode` on the root (the runtime's own
    switch for its tokens); the public copy reads the same attribute. It lasts for the visit, as pages can't store
    settings.
70. **Motion on the dashboard, not a video.** No video tool was available, and an animated dashboard was chosen
    over a film. Everything animates from the page's own data and comes to rest on a complete,
    readable view, so a reader who never presses Play misses nothing:
    - *Prices since 1995*: a time-lapse of each neighbourhood's yearly change (blue rose, red fell) with a bar race on
      growth since 1995 and Doncaster's line drawing itself, marking the boom year, the 2008 peak, the low and the
      recovery (all taken from the data). It plays once when first seen, slows through the crash, and can be paused,
      scrubbed or replayed.
    - *Hurdle rate*: the map lowers the rate you could earn elsewhere from above the best total return to the
      opportunity cost, so neighbourhoods turn from red to blue as they start to beat it. It ends on exactly the
      colours of "Return above the opportunity cost".
    - *Buy-to-let*: the ranking builds up the first time it is seen (cards, counting numbers, circles flying out
      from Doncaster's point in rank order); circles glide to new places when the type, period or rate changes; the
      neighbourhood figures count to new values and its history line draws in.
    - With "reduce motion" set, nothing plays by itself and every view appears at once.
71. **One home against its neighbourhood.** The question: how much better or worse is a home than the average
    there, in % and SD? It is compared with the spread of the last 3 years' sales of its type in its neighbourhood (all types,
    then Doncaster, when there are under 30): price against model value from the out-of-sample backtest (so the spread
    is what buyers really paid against an honest estimate), price per m² and gross yield at modelled rents. The headline
    averages the SDs for price-against-value and yield; price per m² is shown but left out, as it largely repeats
    price. Lower prices count as better. A big discount is flagged as possibly condition the model can't see.
72. **Rents linked to value, not flat.** A price-linked rent model, not flat ONS averages. Rents follow
    prices by β = 0.60 across council areas (leave-one-area-out error 5.9% vs 11.8% without prices),
    and by 0.48 across house types inside Doncaster, so applying β within the borough is a stated
    assumption with some support. The reference price is Doncaster's UK HPI average for the type, because that is what
    β was fitted against. The range uses ONS rent quartiles (2022-23, the last edition with them). The deal analyser
    now starts from this estimate; a pasted listing's rent still wins.
73. **Buy-to-let became Invest.** One tab for deals: the scorecard and rent first, then the existing analyser. The
    Areas tab keeps borough rents (the earlier choice); the Invest tab's "typical home here" uses modelled rents
    so it compares like with like.
74. **Same street name, different places.** A listing for a home on Shakespeare Avenue, DN5 8EZ (Sprotbrough),
    checked against the dashboard, which was showing the same house number on Shakespeare Avenue, Campsall, DN6 9NN. The data was current (Land
    Registry's August 2026 update, published 29 September 2026, has all three DN5 8EZ sales). The sales history now
    names the address and postcode it shows and how far the records run; reading a listing with no postcode offers
    every postcode of a street name used in more than one place, instead of only the busiest one.
75. **Rates on hover.** The opportunity-cost buttons show each rate on the button and, on hover, what it is and where
    it comes from; every "above" figure names the rate it is measured against.
76. **Percentages, not SDs.** Standard deviations proved hard to read. The scorecard now gives the share of
    recent sales of the type in the neighbourhood that the home beats (50% is typical), per measure and combined.
77. **The time-lapse waits.** It no longer plays by itself; it rests at 2026 and plays from 1995 on request. If the
    reader leaves the tab mid-play it finishes at 2026.
78. **Tenant risk, from what exists.** No open data covers individual tenants. Two official measures stand in:
    landlord court possession claims (Ministry of Justice), which exist only for whole council areas, shown on the
    Market tab against Yorkshire and England and split into standard claims (which include rent arrears), accelerated
    no-fault claims (Section 21, ended 1 May 2026) and bailiff evictions; and anti-social behaviour reported to the
    police, placed into each LSOA and neighbourhood, on the map, the profiles, the rankings (with a flag above 1.5x
    Doncaster's rate) and the Investing scorecard. Anti-social behaviour isn't only tenants' doing, and town-centre
    areas with few residents score high; the notes say so.
79. **"Investing".** The tab is named Investing.
80. **A risk allowance, as a switch.** The ranking didn't allow for anti-social behaviour or bad tenants. The allowance turns each measured risk into a yearly cost or loss, so it sits in the same
    units as the return: tenant risk anchored on what rent guarantee insurance costs (the market's own price for
    arrears and eviction costs), scaled by Doncaster's court-claims rate against England's and by each area's
    anti-social behaviour and deprivation; flood insurance (buy-to-let is outside Flood Re); EPC upgrades (an expected
    cost, since lettings need C by 2030); and a downturn at each area's own 2008 depth, once per 30 years (one in the
    31 years of data). The settings are on the page, labelled as assumptions. Off by default, so the plain returns
    stay visible; the table and profiles show the allowance either way. On the Investing tab it uses the home's own
    postcode flood share and leaves out EPC, which the deal already costs. Crime is covered through anti-social
    behaviour and deprivation, which move with it; turnover and licensing are left out (small, or ending in 2027).

81. **Refurbishment costs by item, not per m² of the whole home.** The costs looked far too high, and pricing a
    kitchen by floor area punishes bigger homes. Both were real: the three per-m² figures were unsourced guesses, and charging £700/m² for a kitchen and bathroom made one 85 m² home's cost £59,500.
    The guides price a 3-bed full renovation at £30,000 to £33,000 here, so the old figures ran 3 to 6 times too
    high (not 10). Now a kitchen and each bathroom are fixed amounts by finish, and only the work that grows with the
    home (decorating, flooring, rewiring, heating, plastering) goes by floor area. One source, less.co.uk (April
    2026), for every item so the Yorkshire adjustments are consistent; it is the same source as the extension costs.
    The flip calculator also stopped buying every job at "needs full renovation" and selling at "recently
    refurbished": a cosmetic job now goes from "dated" to "good", which with cheaper works would otherwise have
    shown profits the calibration doesn't support.

82. **Weak scaling, and finish that follows value.** Kitchens and bathrooms aren't really fixed costs, the
    costs still looked slightly high, and cheaper houses get cheaper kitchens. The London Plan's
    kitchen standards grow at about half the rate of the home (fitments 0.58, living-kitchen-dining 0.42), so a
    kitchen now grows with the square root of floor area; less.co.uk's circuit counts give a rewire the same
    power. Bathrooms stay fixed per bathroom, since bigger homes add bathrooms rather than bigger ones. The
    boiler is a fixed part of the heating. The 3-bed guide prices now apply at Doncaster's typical 3-bed semi
    (84 m², from the certificates) rather than the guide's 72.5 m², which brings the per-m² trades down by
    about 14%. Finish follows value from the bottom of the budget range at the 10th-percentile price to
    mid-range at the 90th: an assumption, labelled, with budget and mid-range still selectable. The contingency
    is now an input on the page.
83. **Flood insurance allowance cut from £600 to £110 a year.** The earlier note that Flood Re excludes buy-to-let
    was wrong: its eligibility criteria include residential buy-to-let held by individuals and built before 2009.
    Flood Re reports at-risk homes without claims paying about 38% above the market, which is £110 on the £300
    landlord insurance here; previously flooded homes in Yorkshire pay about £200 more (Compare the Market, Jan
    2026). Company-owned lets and newer homes fall outside Flood Re, so the setting stays editable.
84. **Risk allowance on from the start**; the switch still turns it off.
85. **A chosen period on the price time-lapse.** Dragging across Doncaster's line (or picking the years) sets the
    period; the map shows growth over it, coloured against Doncaster's growth with bins spaced by how much the
    neighbourhoods differ, since over long periods every area rose and a scale centred on zero would be all blue.
    Each year's change is still one click away. The court-claims card moved to the bottom of the Market tab.

86. **Period slider and quick buttons.** The line shouldn't be cut off at the period's end, and the controls had to
    work on a phone. The line now stays whole with the period as a shaded box; a two-handle slider and six quick
    periods set it, and dragging across the line still works with a mouse (not with a finger, so scrolling past it is safe).

87. **Version number and changelog from data.** A version counter and a changelog tab. The changelog is a
    dataset (one row per change, with the valuation model version each release used), so a release adds rows rather
    than editing the page, and the header's version is the newest number in it. Versions follow the numbering already
    used in this log and the README; dates are the days each version's scripts were written (9 and 10 October 2026).

## Version 18: fixes from an independent review

88. **Each finding checked before acting.** All six main findings and both smaller ones were confirmed in the code and
    reproduced. Two matter less than they first sound, and that is measured rather than assumed (89, 90).
89. **Later certificates: kept, measured, disclosed.** Size and build details may come from a certificate lodged after the
    sale (up to 90 days, or the first certificate if none came before). Only 0.6% of test sales are affected. A strict
    re-run gives 8.02% against 8.04%, and 8.03% against 7.95% for 2020: within seed noise. The rule stays, because it
    adds size for homes that would otherwise have none, but the "nothing from the future" wording is withdrawn. Deprivation
    (2025) and plot size (current title plans) have no dated versions; removing them altogether costs about 0.2 points, which
    bounds what their timing could be worth.
90. **Production training filter fixed.** The keep list only covered sales to December 2024, so the page's model missed
    January to August 2025. The same 0.8 log-point rule now applies to later sales, against the test model's estimate,
    and the script asserts that recent sales are in. Estimates on the page move by a median of -0.3%.
91. **Section 24 relief capped.** The 20% (22% from April 2027) credit is on the lowest of finance costs and property
    profits; unused costs and property losses carry forward through the 10-year projection. HMRC's third limit, adjusted
    total income above the personal allowance, needs income the page doesn't ask for, so it is assumed not to bind and said so.
92. **Certificate fields follow the address.** Fields a certificate fills are recorded; when the certificate changes or is
    cleared, any field still as it set it is reset, and a missing value on the new certificate shows as missing. Fields
    typed or read from a pasted listing are left alone.
93. **Impossible inputs refused.** Floor area 10 to 1,500 m², rooms 1 to 30, deposit 0% to 100%, rates and fees within
    plain limits. The page says what is wrong and clears the old results rather than leaving them on screen.
94. **IRR edge cases.** The search widens until the NPV changes sign, returns nothing when no rate fits or the cash flows are
    all zero, and says when the cash flows change sign more than once.
95. **Flood allowance corrected again: £445, as a scenario.** Decision 83 misread Flood Re: its criterion 2 needs the
    policyholder or family to live in the home, or the home to be empty, which a let doesn't meet. So let homes are priced on
    the open market, and the evidence for that is Flood Re's pre-scheme figure (high-risk homes with no claims quoted 148%
    above the market). It is labelled a scenario that needs a quote.
96. **Rent error against the actual rent.** The leave-one-area-out error divided by the predicted rent; it now divides by
    the actual rent (5.9%, against 12.1% for the regional average).
97. **Accuracy for what is entered.** The estimate panel already gave a typical error for each home. It now adds the tested
    medians for homes typed in by hand (11.2% with a floor area, 13.9% with only the type), and the Model accuracy tab shows
    them beside the headline and the strict check.

## Version 19: second review

98. **Each finding checked again before acting.** All three bugs were reproduced; the wording points were fair.
99. **Field ownership, not matching values.** Version 18 cleared any field still equal to what the certificate had put
    there, so a pasted listing with the same 85 m², D rating and bungalow was wiped when the listing cleared the old
    certificate. Ownership is now tracked: a certificate owns the fields it fills until typing or a listing takes them
    over, and clearing it resets only what it still owns. Picking another address still shows that address's
    certificate in full, blank where it has nothing.
100. **One clearing function.** An invalid estimate now clears every result that came from the last one: the asking-price
    advice, explanation, comparables and map, area facts, council tax check, sales history, what-if, and on the
    Investing tab the scorecard and rent estimate.
101. **Every IRR, not one.** The solver scans rates from -99% to 10,000% on a log grid and refines every change of sign, so
    -100, 230, -132 gives 10% and 20%. Two or more rates: the page says the IRR is ambiguous and gives the NPV at the
    10-year gilt. None: it says whether the cash flows never change sign or no rate in that range fits.
102. **Three seeds, and plainer claims.** The strict check now runs three seeds paired with the published rules: -0.03
    points on the 2025-26 test, +0.04 for 2020, "little aggregate change". Dropping deprivation and plot size is
    called a sensitivity test, not a bound. The look-ahead note now lists what is and isn't strictly before the sale.
103. **Regression tests in the project.** `tests/test_units.js` runs the shipped functions (33 checks) and
    `tests/test_ui.py` the state changes in a browser (8 checks); both fail on version 18 where the review said they should.

## Version 20: third review

104. **Each finding reproduced first.** Five new browser cases failed on version 19 before anything changed: the
    scorecard kept the last figures for a refused price (and drew a 1,536% return for a £500 price, which the deal
    analyser refuses), a running count-up wrote a cleared rent estimate back, the "Use £… in the deal" button outlived
    its estimate, and the flip took -6 months or 40 bathrooms as given. Both IRR examples failed as described.
105. **One set of input checks, scoped by panel.** `DEAL_CHECKS` holds every deal input's range. The mortgage analysis
    checks all of them; the cash-purchase scorecard checks price, rent and running costs (`CASH_KEYS`) and ignores
    the mortgage; the rent markers check only what each uses (the price-based "matches the gilt" marker ignores the
    rent; the mortgage break-even checks every input except the rent it solves for). Over-clearing was avoided on purpose: an impossible
    deposit doesn't blank a scorecard that never uses it. The flip appraisal has its own checks and now draws even
    when the mortgage inputs are refused, since it doesn't use them. Messages give the allowed range.
106. **Blanking a counting figure stops the count.** `still()` cancels the element's pending animation frame, forgets
    its last value (so the next figure appears directly rather than counting from a stale one) and writes the dash.
    Every clear path for an animated figure uses it.
107. **IRR by root isolation, and no claim of uniqueness.** NPV is a polynomial in x = 1/(1+r); between neighbouring
    turning points it is monotone, so it crosses zero at most once. The turning points are the roots of the
    derivative, found the same way down to a straight line; each monotone stretch whose ends differ in sign is
    bisected, and a turning point where the NPV is zero to rounding (1e-13 of the sum of the absolute discounted cash
    flows) counts as a repeated rate. Tested on 2,000 cash flows built from 1 to 5 known rates, 1,000 pairs 0.01
    points apart (the old grid found 45 of these), 1,000 repeated rates among up to four others and 300 random
    ten-year deals against a 200,000-point scan: all found, none extra. Limit: with many rates bunched together (eight
    between 81% and 224% in one test) the NPV stays within rounding of zero across about a point, so the cash flows
    don't pin the rate down to better than that; no deal on this page gets near it. Wording: one change of sign means
    exactly one rate (Descartes' rule of signs). With more, even a single rate comes with a warning that the IRR can
    mislead, and the NPV at the 10-year gilt.
108. **Tests that don't wait for the page to settle.** `tests/test_ui.py` now changes inputs two animation frames into
    a count-up, types a price key by key through refused values, and checks each dependent panel (15 cases; E, F, G,
    G2 and J fail on version 19). `tests/test_units.js` has 54 checks.

## Version 21: fourth review

109. **Checked first, again.** Every bug the review listed was reproduced in a browser or a script before anything
    changed, and 19 new browser cases fail on version 20 and pass now. Two were worse than reported: decorating a home
    that needs a full renovation showed £4.50 back per £1, and 145 postcodes in the lookup are outside Doncaster.
110. **A listing paste starts clean.** Each paste resets the fields the last one filled (unless you've changed them),
    so details never carry from one listing to the next. The type is the first one the text names, after taking out
    words that only look like types (flat roof, roof terrace, detached garage, granny flat, a street called Terrace);
    bedrooms can be written as words. The home's postcode is a full postcode in the district the listing names; one in
    the agent's details or another district is ignored and said to be. With no location at all the postcode is
    cleared rather than the last one valued. Street chips are whole postcodes (they used to split at every space).
111. **Typed deal figures belong to the home.** A different home (postcode, address, listing, saved home) starts the
    deal afresh; editing the same home's details keeps the price, rent and EPC cost you typed.
112. **The flip uses your price and real finance.** It buys at your price when you've given one, otherwise at the
    model's value in the condition the works put right. Finance is a bridging loan on part of the price (70%, 12% a
    year, 2% fee: Capitalise's 2026 rates), so interest is on the loan and your cash is the rest. It gives the highest
    price that breaks even and the highest for a 15% margin on the sale price (planning viability guidance: 15-20%).
113. **The scorecard and its markers share one return.** `homeReturn()` gives the scorecard's total (net yield +
    neighbourhood growth - risk allowance when on); the "matches the gilt" rent solves that same total, so setting the
    rent to it lands on the gilt, not 0.6 points below. A £0 rent is the lowest yield (it beats under 5% of sales), not
    a missing one. The projection's price growth defaults to the same growth figure.
114. **Tax on the gain and corporation tax bands.** The 10-year IRR is after capital gains tax (18% or 24% above the
    £3,000 exemption; for a company, corporation tax on the gain on top of that year's profit). Corporation tax has
    marginal relief between £50,000 and £250,000. Not modelled: a basic-rate owner's gain spilling into the higher rate,
    associated companies.
115. **Works lift condition only from where they start.** If a home starts worse than the condition the works put
    right, the what-if counts no rise in condition and says why.
116. **Limits in one place.** The page's own min/max attributes are set from the checks the script runs, so they can't
    disagree; risk settings and your own rate outside their ranges are refused, with a message, and the default used.
117. **Typing redraws once you pause.** Each estimate with its SHAP breakdown takes about 0.4 s (over 1 s on a slower
    phone); typing now redraws 0.22 s after the last key rather than on every key.
118. **Postcodes outside Doncaster are refused**, in the dashboard and predict.py: a postcode counts as Doncaster's when
    its 2021 small area is one of the borough's 199.
119. **predict.py checks like the dashboard.** Same limits; months must be YYYY-MM and in the index; an address must
    match one home word for word ("3 Main Street" no longer finds 103); the last sale's new-build flag comes from the
    record instead of being 0. `tests/test_parity.py` compares its features with the training frame for 397 recent sales:
    everything not dated by design matches, to the lookups' rounding, for at least 99.5% of homes (the rest have a
    second certificate within 90 days of the sale).
120. **One cleaning rule.** The production training rows come from one function, `export_v7.production_rows`, used by
    both `export_v7.py` and `production_v18.py`; rerunning `export_v7.py` no longer brings back the 2025 filter bug.
    Rerunning `production_v18.py` after the change gives the same model, byte for byte.
121. **No addresses in what's shared.** The public copy now strips every capitalised house name and number from the
    comparable sales (about 600 got through before). The zip leaves out the address lookup (`model/epc_*.csv`): EPC
    address and postcode fields are under Royal Mail terms and are treated as personal data. `src/assemble_model_dir.py
    --with-addresses` rebuilds it on your own machine. `tests/test_privacy.py` checks both.
122. **Registration lag measured, not assumed.** New builds are 4.3% of 2025 test sales and none of 2026's. They are
    the easiest homes (5.3% median error), and January to August 2026 scores 8.12% against 8.09% for the same months
    of 2025, so the lag doesn't flatter the headline. The "two months, so published" wording is corrected.
123. **Seed averaging tested, left out.** Three seeds averaged: 7.92% against 7.97-8.04% alone. About 0.07 points for
    four times the trees in the browser; not worth it.
124. **Condition recalibrated.** Folds grouped by home, and the uplift every long-hold resale shows (+1.4% at both
    ends) subtracted: -8.9% for needs full renovation (was -8.3%), +6.2% for recently refurbished (was +7.7%). The full
    served model, which sees the last sale, already reads a quick resale as refurbished (+0.6%), so the setting stays
    calibrated on the model without last-sale features, for homes whose condition the model can't see.
125. **A fair baseline.** A hedonic regression on the model's own 62 features with sector fixed effects, trained and
    tested the same way: 9.81% against the model's 8.07%. It replaces the first version's ridge (16.2%), which used
    far fewer features and overstated the gap.
126. **One entry point, experiments apart.** `pipeline.py` runs the build in order by stage; tests whose only output is a
    results table moved to `experiments/`. Not done: one feature builder with an as-of date for training, backtest and
    serving. That rewrite would change every published number; the parity test is the guard until then.
127. **Rates.** The gilt is 5.48% (the 8 Oct 2026 close; 5.53% was that day's intraday high). Bank Rate stays 3.75%.


## Version 22: fifth review

128. **Capital gains tax uses the basic-rate band.** A basic-rate owner pays 18% only on the part of the taxable gain
    that fits in the unused basic-rate band (£37,700, frozen to April 2031 and assumed to stay there), after other
    taxable income (£20,000 unless entered) and that year's rental profit; 24% above. Before, the whole gain was taxed
    at 18%: on HMRC's own example (£20,000 income, £52,600 gain) the page gave £8,928 against HMRC's £10,842. Companies
    and higher-rate owners are unchanged. The year-10 note shows the split.
129. **Improvements off the gain, repairs off the rent.** Only capital improvements are allowable against the gain;
    repairs and decorating aren't. A new input says how much of the works and EPC upgrade is improvement (£0 by
    default, never more than the two together); the rest is deducted from the first year's rental profit, the usual
    treatment for repairs to a let home. Before, all of it came off the gain.
130. **A listing doesn't inherit a postcode.** A listing naming only a district ("Doncaster DN4") clears the postcode
    instead of keeping the last home's, so no estimate is shown for the wrong home. If the old postcode is in that
    district, a dashed "Keep" chip offers it back; keeping it is the reader's choice.
131. **The flip uses what you typed or nothing.** An invalid purchase price clears the calculator with the reason
    instead of falling back to the model's value; a blank price still uses the model; a £0 works quote is £0, not the
    guide cost.
132. **Condition by what the estimate knows.** Calibrated twice: against the model without last-sale features (needs
    full renovation -8.9%, recently refurbished +6.2%) for an estimate with no last sale, and against the full model
    (-4.7% on the 546 purchases that had an earlier sale, a median 10 years before; +0.6% on resales within 18 months)
    for one that has. The rule: no last sale, the first; a worse condition, the second; a better one, the second if the
    last sale was within 18 months and the first otherwise (works since an older sale the model can't see, a case the
    repeat sales can't measure). Dashboard and `src/predict.py` share the rule; `condition.csv` carries both columns.
133. **The page rebuilds from the zip.** The page source moved from `outputs/dash2/` to `dashboard/`; outputs/dash2/
    holds only data, and the zip now carries it without the address lookups. Every assumption is in one file,
    `config/assumptions.csv`; the scripts that set assumptions only add missing keys (rerunning `assumptions_v9.py` no
    longer resets the gilt to 5.42%), and `src/apply_assumptions.py` copies it to the dashboard. `tests/test_build.py`
    rebuilds the public copy from the zip and checks it matches byte for byte.
134. **Two page scripts.** The Claude dashboard refuses any one file over 256 KB, and app.js reached 258 KB. The Market
    and Accuracy tabs moved, unchanged, to `dashboard/market_accuracy.js`, loaded first; app.js passes it the 30
    helpers it uses and gets back the two tab renderers. Chosen over minifying (the served code stays the readable
    source) and over trimming comments (no room for the next feature). `tests/test_build.py` checks the size limit.

## Version 23: three views of a deal

135. **One projection.** The 10-year projection moved out of the page's drawing code into `projectDeal`, which takes an
    optional path of values. The tiles, the projection table, the tornado and the past-decades fan all call it, so they
    can't disagree; unit tests check that a value path equal to the growth figure gives the same IRR, and that the IRR
    solves the after-tax cash flows.
136. **The mortgage rate chart.** The first year's cash flow at every rate (0.05-point steps), the break-even by linear
    interpolation between steps, and the stress-test limit by the deal card's own rule (rent ≥ ICR × interest at the
    larger of the floor and the rate + 2 points; lenders test interest only, so it is the same for repayment loans). The
    curves don't depend on the rate, so dragging moves the marker without redrawing; the scale holds still during a
    drag and grows after it (it ran away when it grew mid-drag). On a touch screen a drag starts only after a mostly
    sideways move, so scrolling past the chart can't change the deal.
137. **The tornado's swings.** Round, fixed swings (in `config/assumptions.csv`) so inputs compare across deals, rather
    than each input's own uncertainty, which the page doesn't know. Paying 10% less keeps the home's value as entered
    (otherwise a cheaper purchase would also sell for less, understating what negotiating is worth). The deposit isn't
    lowered below the usual 25% buy-to-let minimum. Rows are ordered by the furthest either end moves from the figure
    as entered; rows with no effect, or with no single IRR at one end, are named in the note.
138. **Past decades, not a forecast.** The fan uses the neighbourhood's own yearly repeat-sales index (1995 on), one
    10-year stretch per purchase year: 22 stretches that overlap, so a few market cycles seen from every starting
    point, and the page says so. Prices are nominal, and rent growth, costs and the mortgage rate stay as entered, so a
    past decade's very different rates aren't replayed. A purchase year "beats the gilt" when its after-tax cash flows
    have a positive NPV at the gilt (the same as the IRR test when there is one IRR, and defined when there isn't, as
    for a sale below the loan); years with no single IRR are shown apart, with their total profit. Considered and left
    out: a block bootstrap of yearly changes, which gives smoother bands but invents decades that never happened.

## Version 25: before publishing on GitHub

139. **What a public repository may carry.** The code is MIT; the data keeps its licences, with the attribution lines
    in the README and the page footer (Land Registry's Price Paid Data includes Ordnance Survey and Royal Mail address
    data, which may be displayed for property price information but not handed out in bulk). So the shared copy keeps
    comparable sales to street and postcode (`src/addresses.py --strip-shared-copy`, checked by `tests/test_privacy.py`),
    as the public page already did; `predict.py` doesn't use the address. Tables derived from OpenStreetMap are
    shared under its Open Database Licence, and d3's ISC notice ships in `dashboard/vendor/` and the public page.
