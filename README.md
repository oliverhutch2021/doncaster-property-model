# Doncaster Property Model

A valuation and investment model for residential property in Doncaster, built from open data.
It estimates what a home would sell for today, gives an 80% price range, adjusts for condition,
and turns the estimate into buy-to-let, area-screening and buy-refurbish-sell numbers. Results are
shown in an interactive dashboard that runs the model in the browser.

A plain-English guide to how it works and what it's for is in `docs/How-the-model-works.pdf`.

## Results (test set: 5,995 sales, Jan 2025 - Aug 2026, never seen in training)

Each row adds one data layer to the LightGBM model (same temporal split throughout):

| Model | Median error | Within 10% | Within 20% | Mean absolute error |
|---|---|---|---|---|
| Hedonic regression on the same features (fair linear baseline, fourth review) | 9.8% | 51% | 80% | £26,349 |
| Ridge regression, first version's features (the old baseline) | 16.2% | 32% | 59% | £44,242 |
| LightGBM, location and deprivation only (v1) | 13.2% | 39% | 67% | £38,145 |
| + EPC: floor area, rooms, build age, energy rating | 9.7% | 52% | 80% | £26,738 |
| + prices of the 10 nearest earlier sales | 9.6% | 52% | 80% | £26,433 |
| + the home's own last sale, index-adjusted | 8.7% | 56% | 82% | £24,545 |
| + removing 224 unexplainable training sales | 8.6% | 56% | 82% | £24,598 |
| + plot size, street/postcode prices, more EPC detail (v5, 3 seeds) | 8.2% | 58% | — | — |
| + tuned settings (full size, 3 seeds) | 8.1% | 58% | — | — |
| + local correction (3 seeds) | 8.06% | 59% | — | — |
| + certificate history (v7, final, 3 seeds) | **8.03%** | **59%** | — | — |

- Dashboard model (v7, as exported): **8.04% median error**, 60% within 10%, 84% within 20%, mean absolute error £22,737.
  Homes with a known previous sale (72% of test sales): 7.6%. Without one: 9.4%. Version 5's browser-sized model was 8.25%.
- **Version 8 (current): testing and confidence.**
  - *Backtest:* each year since 2020 valued by a model trained on sales up to two years before, with a price index
    rebuilt as known at the time. Median error 7.8% (2020), 7.7%, 8.0%, 8.4% (2023), 8.2%, 8.0%, 8.0% (2026 to August).
  - *Confidence score:* a small second model (300 trees) predicts each estimate's typical error from 2020-23 backtest
    errors; scaled on 2024, checked on 2025-26. High confidence (7% of homes) had a 4.9% median error, Good (29%) 6.6%,
    Fair (33%) 8.3%, Low (31%) 11.3%; keeping the most confident 70% gives 7.1%. The 80% ranges now scale with it: each
    level's range held the price for 76-81% of sales (the fixed ranges held 93% for the most confident and 70% for the
    least), overall 80.5%. Homes typed in by hand get their own scaling (calibrated on 2024 with certificate details blanked).
  - *Assessors' checks (IAAO ratio study):* COD 12.7, inside the standard of under 15; PRD 1.031, just over the
    0.98-1.03 band; PRB -0.06, so estimates are slightly regressive. Correcting estimates by size was no better and
    stretching them to remove the bias cost 0.7 points of median error, so they are left as they are.
  - *Time inside the model (Zillow-style)* instead of a price index: 0.8 points worse (trees can't run ahead of their
    training years); time features alongside the index: no better.
- **Version 7.** The full-size tuned model now runs in the browser: its trees are stored compactly (left child
  implied, three flags packed into one number), so 2,043 trees fit in 6.9 MB. The home's energy-certificate history was
  added: why the latest certificate was done, its tenure, any certificate for a let in the last 5 years, certificate age
  and count, and the energy-score change since the previous one. Homes last certified as lets had been over-valued by
  2.7%; now +0.3%. Overall it gained 0.03 points (3 seeds, every seed better). Tested and left out: how far the home's last
  sale was from the model (0.1 points worse; the last sale price already carries it) and a smoothed local correction
  (no better than the nearest-sales one).
- **Version 5.** Plot size from HM Land Registry title plans, recent prices on the same street and postcode, and more
  EPC detail (walls, loft, glazing, heating, fireplaces, ceiling height) took the full-size model from 8.77% to 8.24%,
  and tuned settings to 8.10% (3 seeds each). Exact address positions, similar-size neighbours and the
  neighbourhood council tax mix added nothing on top and were left out.
- **Local correction.** One Doncaster-wide index under-values areas rising faster than the rest. Each estimate is shifted by
  half of the model's median miss on the 40 nearest sales of the last 12 months (tuned on 2024). The spread of
  sector-level bias on 2025-26 fell from 2.3% to 1.5%.
- The 80% prediction range covered 80.5% of test sales (79.4% with the version 7 fixed ranges).
- Flood risk, transport, schools, OpenStreetMap amenities and urban/rural class were each tested on top of this model
  (3 seeds). None beat seed-to-seed noise (best: -0.07 points, spread ±0.16), so they are shown in the dashboard
  but left out of the estimate.

## Strict timing check (v19, `src/strict_eval_v19.py`)

The headline test lets a sale take its size, rooms and build details from a certificate lodged up to 90 days after it,
or from the home's first certificate if none came before (energy ratings and certificate history were always strictly
before the sale). Re-run with only certificates lodged by the sale date, three LightGBM seeds each, the change paired
with the published rules seed by seed:

| Check | Sales | Median error, mean of 3 seeds | Change (range over seeds) | Within 10% |
|---|---|---|---|---|
| 2025-26 test, published rules | 5,995 | 7.99% (7.96% to 8.04%) | | 59.3% |
| 2025-26 test, only certificates lodged by the sale date | 5,995 | 7.96% | −0.03 points (−0.08 to −0.01) | 59.4% |
| Same, and without deprivation or plot size (sensitivity test) | 5,995 | 8.23% | +0.24 points (+0.17 to +0.29) | 58.0% |
| 2020, published rules (trained to 2018, no local correction) | 3,925 | 7.97% | | 59.4% |
| 2020, only certificates lodged by the sale date | 3,925 | 8.01% | +0.04 points (0.00 to +0.08) | 59.2% |

Little aggregate change. The 35 test sales (0.6%) that used a later certificate are valued less well under the strict
rule (median error 9.5% → 15.5%; for 2020's 135, 10.9% → 11.8%). The deprivation scores (2025) and plot sizes
(current title plans) have no dated versions; dropping them is a sensitivity test, not a measure of their timing,
because it also loses what they legitimately add. Not measured: neighbour price per m² uses each neighbour's
best-known floor area. The 8.04% headline is the seed used throughout the project; the three-seed mean is 7.99%.

## Registration lag and seed averaging (fourth review, `src/eval_cohorts_seeds.py`)

Land Registry registers some sales months after completion, new builds above all. New builds are 4.3% of 2025 test
sales but none from February 2026, and August 2026 has 82 sales against a usual 300-400, so the 2026 part of the test
set is the sales that registered quickly. On the published test model:

| Test sales | Sales | Median error | Within 10% |
|---|---|---|---|
| All, Jan 2025 - Aug 2026 | 5,995 | 8.04% | 60% |
| Sold in 2025 | 4,240 | 7.99% | 60% |
| Sold Jan - Aug 2025 (same months as 2026) | 2,757 | 8.09% | 60% |
| Sold Jan - Aug 2026 (registered so far) | 1,755 | 8.12% | 60% |
| New builds | 186 | 5.31% | 83% |
| Not new builds | 5,809 | 8.19% | 59% |

New builds are the easiest homes to value, so their absence doesn't flatter 2026: those months score much the same as
the same months of 2025. The headline will be scored again once Land Registry catches up; other late registrations
(not only new builds) can't be told apart in the published data.

Averaging three LightGBM seeds (42, 7, 2026) gives 7.92% against 8.04%, 7.97% and 7.97% for each seed alone: about 0.07
points against a typical seed. It would need three production models (8,310 trees instead of 2,043), so the browser
model and every keystroke would cost about four times as much. Left out; the seed spread is reported instead.

## Production model (v18, `src/production_v18.py`)

The dashboard's model is refitted after testing on every kept sale before the local-correction window: 46,566 sales from
January 2015 to August 2025. Until v18 the filter in `src/export_v7.py` kept only sales on the 2024 clean-up list, so all
2,757 sales from January to August 2025 were left out while the metadata said August 2025. Sales from January 2025 are
now cleaned with the same 0.8 log-point rule against the test model's estimate (14 removed), the training dates and count
come from the rows used, and an assertion stops the script if recent eligible sales go missing. On September 2025 to
August 2026 sales, which neither version saw, the refit's error before the local correction is 7.97% against 8.08%.
The reported test accuracy comes from the separate test model and is unchanged.

## How it compares (`src/compare_methods.py`)

The common quick methods, scored on the same test sales. Each method only sees sales at least two months old, by when
most sales appear in Land Registry's published data (new builds and some others take months longer; see below).

| Method | Sales it can value | Median error | Within 10% | Model on the same sales |
|---|---|---|---|---|
| Last sale x UK House Price Index, Doncaster (online "worth now" calculators) | 72% | 13.0% | 41% | 7.6% |
| Last sale x UK HPI for the property type | 72% | 12.7% | 42% | 7.6% |
| Median £/m² of the 10 nearest same-type sales, last 12 months, x floor area | 98% | 13.6% | 39% | 8.0% |
| Median £/m² of same-type sales in the postcode sector x floor area | 96% | 14.9% | 36% | 7.9% |
| Median price of same-type sales in the postcode sector | 99% | 17.5% | 31% | 8.1% |
| Hedonic regression on the model's own 62 features, with a fixed effect per postcode sector | 100% | 9.8% | 51% | 8.1% |
| **This model (v7), with the same two-month cut-off** | 100% | **8.07%** | 59% | |

- The hedonic regression is the fair baseline: the same features, the same training and test sales, the same local
  correction, in a linear model (ridge, strength chosen on 2024; missing values filled with the training median plus a
  missing flag; logs of skewed sizes and counts; size by type; a fixed effect for each postcode sector). The model beats
  it by 1.7 points. The earlier "ridge 16.2%" row was the first version's model on its smaller feature set, which
  overstated the gap.
- The reported 8.04% let the model's local price features use every earlier sale. With the two-month cut-off it is
  8.07%, so the result doesn't depend on data that wouldn't be published yet.
- The index-the-last-sale method gets worse the older the last sale: 8.6% under 5 years, 18.1% at 10+ years
  (model 6.2% and 8.6% on the same homes). It also over-values by 4% at the median.
- Commercial AVMs: UK portals don't publish their accuracy against sale prices. Hometrack (which powers Zoopla's estimate)
  says 80% of its valuations are within 10% of the surveyor's value. Zillow reports about 7% median error for US homes
  not for sale (2026), and Redfin 7.4%. These use different benchmarks, markets and data, so they are context, not a
  head-to-head.

## Neighbourhoods (v9, `src/areas_v9.py`)

- **Areas**: the 39 MSOAs (2021) in Doncaster, named by the House of Commons Library; each holds about five of the
  map's 199 LSOAs exactly.
- **Growth**: a repeat-sales index (Bailey-Muth-Nourse with Case-Shiller weights) on 50,488 pairs of standard Land
  Registry sales of the same home since 1995 (new-build first sales, type changes, gaps under 6 months and the 1% tails
  dropped), in years ending August. Each neighbourhood's index is Doncaster's plus a smooth deviation (random-walk
  penalty; lambda = 1,000 chosen by 5-fold cross-validation on held-out pairs, which beat Doncaster's index alone:
  weighted MSE 0.0507 vs 0.0536). 80% ranges from 200 bootstrap resamples.
- **Check against the official index**: Doncaster's repeat-sales annual changes correlate 0.986 with the UK HPI
  (mean gap 1.2 points a year); 10-year growth to 2025 is 4.49% a year against the UK HPI's 4.50%.
- **Returns**: a cash purchase at the local median price, let at Doncaster's ONS rent for the type (no open source
  gives rents for smaller areas, so cheaper areas get higher yields). Net yield takes off the dashboard's running-cost
  assumptions and spreads stamp duty (with surcharge), legal and selling costs over a 10-year hold; total return = net
  yield + past price growth a year; the opportunity cost defaults to the 10-year gilt (5.48% at the close on 8 Oct 2026), with Bank
  Rate (3.75%) or any rate from 0% to 30% as alternatives. Past growth isn't a forecast.

## Rent estimate (v10, `src/invest_v10.py`)

- No open data gives individual rents, so rent is linked to value:
  rent = Doncaster's ONS average rent for the type × (home's value ÷ Doncaster's UK HPI average price for the type)^β.
- β = 0.596 (clustered SE 0.030): fitted across 316 council areas in England and Wales,
  ONS Price Index of Private Rents (Aug 2026, by type) against UK HPI prices (last 12 months), with region and type
  effects (R² 0.94). Leaving each area out, its rents are predicted to within 5.9% of the actual rent (median),
  against 12.1% from the region's average alone. Within regions, β by type runs
  0.51 to 0.65; inside Doncaster, rents across the four types
  follow prices with a slope of 0.48.
- Likely range: the middle half of Doncaster rents for the bedroom count (ONS private rental market statistics,
  Oct 2022 to Sep 2023, the last edition with quartiles), as ratios around the estimate.
- Untested on individual lets (none are open), so the page says so and asks for a check against listings.

## Tenant risk (v11, `src/tenants_v11.py`)

- **Court claims** (Market tab): Ministry of Justice landlord possession statistics to April-June 2026, per 1,000
  privately rented households (Census 2021), over the previous four quarters. In the year to June 2026 Doncaster had
  4.6 standard claims per 1,000 rented homes (these include rent-arrears cases), higher than
  53% of 309 English council areas; 3.4 accelerated (no-fault Section 21) claims and
  1.9 bailiff evictions. Borough-wide only: there are no figures for smaller areas.
- **Anti-social behaviour** (Areas and Investing tabs): every police.uk report in Doncaster from 2025-09 to
  2026-08 (6,317 reports), placed in its LSOA by its map point, per 1,000 residents (Census 2021).
  Doncaster overall: 20.5 a year per 1,000 residents.
- Re-run after `src/areas_v9.py`, which rewrites the neighbourhood file.

## Risk allowance (v12)

A switch on the Areas, best buy-to-let and Investing views takes an allowance off each return, in points a year:
- **Tenants**: rent × 3.75% (the midpoint of rent guarantee insurance, typically 2.5% to 5% of rent) × Doncaster's
  landlord court claims against England's (0.79) × the area's risk index (its anti-social behaviour and deprivation
  against Doncaster's, averaged, kept within 0.4 to 3).
- **Flood**: the share of homes at flood risk × £445 a year of extra insurance, a scenario to check with a landlord quote. A typical let
  falls outside Flood Re (its criterion 2 needs the policyholder or family to live there, or the home to be empty), so cover is
  priced on the open market; before Flood Re, high-risk homes with no claims were quoted 148% above the market (£524 against £211).
- **EPC**: the share of homes below C × the £5,400 average to reach C (capped as the rules do), over the hold.
- **Downturn**: the area's own 2008 fall, once every 30 years (one downturn in the 31 years of data since 1995).
All three settings are editable on the page; they are allowances, not measured losses. The switch starts on. With the defaults the
allowance runs from 0.5 to 1.9 points; the top five changes from Mexborough West, Central Doncaster & Hyde Park,
Moorends, Edlington, Stainforth to Mexborough West, Moorends, Edlington, Conisbrough South, Central Doncaster & Hyde Park.

## Refurbishment costs (v14, `src/refurb_v13.py`)

Replaces three unsourced per-m² guesses (£300 cosmetic, £700 kitchen and bathroom, £1,200 full) that ran 3 to 6
times too high. Item by item at less.co.uk's Yorkshire prices (April 2026), with the Federation of Master Builders'
10% contingency (editable on the page). The guides price by house, so their 3-bed figures are taken at Doncaster's
typical 3-bed semi: 84 m², the median semi whose certificate shows 4 or 5 bedrooms and living rooms.

| Item | Cost | Grows with floor area |
|---|---|---|
| Kitchen | £4,550 to £10,000 by finish | to the power 0.5 (London Plan kitchen standards: fitments 0.58, living-kitchen-dining 0.42) |
| Bathroom, each | £2,300 to £5,800 by finish | no (set the number refitted) |
| Rewire (full renovation) | £5,940 for a 3-bed semi | to the power 0.5 (8-10 circuits in a 3-bed semi, 15-20 in a 5-bed detached at £150-£300 each) |
| Heating (full renovation) | £1,950 boiler + £26/m² radiators and pipes | boiler fixed, the rest in proportion |
| Decorating | £37/m² | in proportion |
| Flooring | £32/m² | in proportion |
| Re-skim walls and ceilings (full renovation) | £30/m² | in proportion |

Finish follows the home's value unless one is picked (an assumption): the bottom of the budget range at
Doncaster's 10th-percentile price (£100,000), the budget average at the median (£180,000) and the mid-range average
at the 90th percentile (£340,000), in between by log price. Examples with contingency, 85 m², one bathroom: a £68k
terrace, kitchen, bathroom, decorating and flooring £14,016, full renovation £27,970; a £228k semi, £19,272 and
£33,226; a 150 m² £527k detached, £32,464 and £52,581. VAT isn't added unless chosen (5% can apply to homes empty
for two years, HMRC VAT Notice 708). The buy-refurbish-sell calculator buys at your purchase price when you've given
one (typed in the deal, or the listing's asking price), otherwise at the model's value in the condition the works put
right ("dated", or "needs full renovation" for a full one); it sells at the condition they leave ("good", or
"recently refurbished" for a kitchen, bathroom and decoration or more), and takes your own quote if you have one.
Finance is a bridging loan on part of the price (70% by default; lenders mostly cap at 70-75%) at 12% a year with a
2% arrangement fee (Capitalise's 2026 rates: mostly 0.95-1.25% a month); the rest of the price, the works and the
buying costs are your cash, and a 0% loan is a cash purchase. An invalid price clears the calculator, a blank one uses
the model's value, and a £0 quote stays £0. It also gives the highest price that breaks even and the
highest for a 15% margin on the sale price (planning viability guidance treats 15-20% of the sale value as a
reasonable developer return). In the what-if tool, works lift a home's condition only if it starts no worse than the
condition they put right: decorating a home that needs a full renovation adds nothing for condition.

## Tests

```
node tests/test_units.js      # 101 checks: Section 24, corporation tax, CGT across the basic-rate band, IRR (repeated, close and several rates), the 10-year projection, input checks, listing parser, condition rule
python tests/test_ui.py       # 42 browser cases: listings, impossible inputs clearing every result, edits mid-animation and mid-typing, deal, flip, CGT, condition, Market and Accuracy tabs, the rate slider, tornado and past-decades fan
python tests/test_build.py    # the page rebuilds from its source, the assumptions are config/, the public copy rebuilds byte for byte, no page file over 256 KB
python tests/test_parity.py   # predict.py builds the same features as training (full checkout with the address lookup)
python tests/test_privacy.py  # no house numbers or names in the public copy, no address lookup in the shared model/
```
`test_ui.py` needs Playwright with Chromium. In a full checkout it builds a private test copy with the address lookup
(never published); from this repository, which has no address lookup, it runs the cases that don't need addresses
against `public/index.html`.

## Use the model in Python

`model/` holds the trained model (native LightGBM format) and the lookups it needs, including the recent sales used for the local correction.
It is the same model the dashboard runs (`doncaster_lgbm_v7.txt`); the two agree to within 0.00000004 on the log scale, and the browser's
SHAP explanations match LightGBM's `pred_contrib` to 9 decimal places.

```
pip install lightgbm pandas numpy
python src/predict.py --postcode "DN1 2EG" --type T --area 70 --prev-price 65000 --prev-month 2016-05 --condition dated
python src/predict.py --postcode "DN4 0AH" --type T --address "<house number> <street>" --explain   # needs the address lookup (below)
```

Only postcode and type are required; every other input is optional and the model handles it being missing. Inputs are
checked against the dashboard's limits (a 0 m² home, a month like `2016-5` that isn't in the index, a postcode outside
Doncaster or an address that fits more than one home is refused, not guessed). `tests/test_parity.py` checks that the
features it builds match the ones the model was trained on.

**The address lookup isn't in this copy.** `--address` reads `model/epc_<district>.csv`, which holds every
certificate's address. The EPC data is open, but its address and postcode fields are under Royal Mail terms and the
department treats address-level EPC data as personal data, so this project doesn't republish them. To use `--address`,
download the EPC data yourself (`src/fetch_data.sh` says how), then run `python pipeline.py --only lookups` and
`python src/assemble_model_dir.py --with-addresses`.
Prices are at the valuation month in `model/model_meta.json` (September 2026).

## Data

| Source | Used for |
|---|---|
| HM Land Registry Price Paid Data, Doncaster, 1995-2026 | Sale prices, dates, type, tenure, new build, addresses, previous sales |
| Energy Performance Certificates, Doncaster, 2012-2026 (MHCLG) | Floor area, rooms, built form, age, energy score, mains gas; tenure and EPC shares by area |
| postcodes.io (ONS Postcode Directory) | Coordinates, 2021 LSOA, ward |
| English Indices of Deprivation 2025 (MHCLG) | Neighbourhood deprivation, including crime and living environment |
| ONS Price Index of Private Rents | Doncaster rents by bedrooms and type, rent growth |
| DWP Local Housing Allowance 2026-27 | Housing benefit caps, Doncaster BRMA |
| Environment Agency flood risk by postcode (NaFRA2, 2025) | Flood risk card, map, buy-to-let warning (tested in the model) |
| DfT NaPTAN | Rail stations and bus stops (tested in the model) |
| DfE Get Information about Schools, Ofsted outcomes (Mar 2026) | Nearest schools and their grades (tested in the model) |
| OpenStreetMap (Geofabrik South Yorkshire) | Supermarkets, parks, GPs, pubs and cafés, motorway junctions, main roads (tested in the model) |
| ONS LSOA 2021 boundaries and rural-urban class | Neighbourhood map (tested in the model) |
| HM Land Registry INSPIRE Index Polygons (Doncaster) | Plot size per home (in the model) |
| OS Open UPRN | Places each EPC home on its title plan (in the model) |
| VOA Council Tax stock of properties (2025) | Council tax band check; band mix tested in the model |
| OS OpenMap Local building outlines (Apr 2026) | Possible-extension prompt (tested in the model) |
| less.co.uk and planwatch.co.uk 2026 cost guides | Extension and loft conversion costs in the what-if tool |
| gov.uk / HMRC / MHCLG guidance | Stamp duty, landlord tax, EPC rules, Renters' Rights Act (each with a source link in the dashboard) |

### Licences and attribution

The MIT licence (`LICENSE`) covers the code. The data in `outputs/`, `model/` and `public/` is derived from the
sources above and keeps their licences:

- Contains HM Land Registry data © Crown copyright and database right 2026, licensed under the
  [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
  Price Paid Data contains address data processed against Ordnance Survey's AddressBase Premium product, which
  incorporates Royal Mail's PAF® database; it is used here to show residential property price information.
- Energy Performance Certificate data © Crown copyright, under the Open Government Licence; the address fields are
  under Royal Mail and Ordnance Survey terms, which is why the address lookup is not shared (`tests/test_privacy.py` checks this).
- Contains public sector information licensed under the Open Government Licence v3.0 (ONS, MHCLG, DWP, DfE, DfT, VOA,
  Environment Agency).
- Contains OS data © Crown copyright and database right 2026.
- Map data © OpenStreetMap contributors, under the [Open Database Licence](https://opendatacommons.org/licenses/odbl/).
  The tables built from it, `outputs/dash2/places.csv` and the OpenStreetMap columns of `outputs/dash2/pc_extras.csv`
  (food and drink nearby, distance to a main road), are shared under the same licence.
- Comparable sales in this copy keep the street and postcode only: house numbers and names are removed
  (`src/addresses.py`), and the certificate address lookup isn't included. `tests/test_privacy.py` checks both.
- d3 is used under the ISC licence (`dashboard/vendor/LICENSE-d3.txt`, also in the public page).
- The dashboard and model are a statistical estimate, not a survey, mortgage valuation, or financial or tax advice.

Raw data is not committed. Run `src/fetch_data.sh` to download it. The EPC file needs a free GOV.UK One Login
download (see the script).

## Pipeline

One entry point runs the build in order, from raw data to the page:

```
python pipeline.py --list            # every step, its stage and what it writes
python pipeline.py                   # all of it
python pipeline.py --from evaluate   # from a stage (data, features, export, lookups, train, evaluate, page) or a script
python pipeline.py --only lookups    # one stage or one script
```

| Stage | Scripts (in order) |
|---|---|
| data | `fetch_data.sh`, `fetch_postcodes.py`, `build_dataset.py` (sql/01-03 in DuckDB), `epc_match.py`, `amenities.py`, `osm_features.py`, `plots.py`, `buildings.py` |
| features | `model_v2.py` (index, last-sale and neighbour features, the clean-up list), `features_v5.py`, `features_v7.py` (the training frame) |
| export | `export_v2.py`, `export_v3_extras.py`, `export_v4.py`, `export_v5.py`: the first dashboard datasets, which later steps add to |
| lookups | `export_v5_lookups.py`, `export_v6_extras.py`, `export_v7_lookups.py`: the address lookup (private) and street levels |
| train | `model_v5_tune.py` (hours; skipped unless asked: its settings are kept in `outputs/metrics_v5_tests.json`), `export_v7.py` (test model, local correction, ranges), `production_v18.py` (the production model) |
| evaluate | `compare_methods.py`, `model_v8_backtest.py`, `model_v8_confidence.py`, `model_v8_typed.py`, `export_v8.py`, `strict_eval_v18.py`, `strict_eval_v19.py`, `eval_cohorts_seeds.py`, `condition_calibration.py` |
| export (investing) | `areas_v9.py`, `assumptions_v9.py`, `invest_v10.py`, `tenants_v11.py`, `refurb_v13.py` |
| page | `apply_assumptions.py` (config/ into the dashboard), `flag_doncaster_postcodes.py`, `build_page.py` (dashboard/index.html), `assemble_model_dir.py` (model/ for predict.py), `build_standalone.py` (the public copy) |

Modules the steps import: `features.py`, `price_index.py`, `correction.py`, `model_v5_tests.py` (the tuning harness),
`epc_match.py`, `export_v7.py` (shared helpers, including the one training clean-up rule `production_rows`).

The version numbers are history: the project grew a layer at a time, and each export adds to or replaces the
datasets of the ones before, so the order matters. Rerunning the last steps reproduces the published model exactly
(`production_v18.py` gives the same 2,043 trees, byte for byte). A single rerun of every step from freshly
downloaded data hasn't been done in one go; refreshed raw data will move the numbers.

**Rebuilding the page.** The page source is `dashboard/`: `_css.html` and `_body.html` (joined into
`index.html` by `src/build_page.py`), `market_accuracy.js`, `deal_charts.js` and `app.js` (the Market and Accuracy tabs
and the Investing tab's rate, tornado and past-decades charts have scripts of their own because the Claude dashboard
refuses any one file over 256 KB), and `vendor/d3.min.js`. Every assumption
(tax rates, costs, rates, refurbishment prices) is in one file, `config/assumptions.csv`, with its source; the steps
that set them only add missing keys, and `src/apply_assumptions.py` copies it to the dashboard. The repository carries the
dashboard's datasets in `outputs/dash2/` except the address lookups, so `python src/build_page.py` and
`python src/build_standalone.py` run from it, and `tests/test_build.py` checks the result matches `public/index.html`
byte for byte.

`experiments/` keeps the tests whose only output is a table of results (kept in `outputs/*.json` and shown in the
dashboard's tested-changes and ablation tables): `model.py` (version 1, ridge against LightGBM), `model_v3.py`,
`diagnose_v3.py`, `model_v4_tests.py`, `model_v6_tests.py`, `model_v7_tests.py`, `model_v7_correction.py`,
`model_v8_tests.py`, the first dashboard export and condition script, and `refurb_v12.py` (superseded by v13). They
still run (`python experiments/model_v8_tests.py`), importing the pipeline's modules from `src/`.

```
tests/                       unit, browser, train/serve parity and privacy tests (see Tests)
src/predict.py               value one home from the command line with the saved model
config/assumptions.csv       every assumption the dashboard uses, with its source
dashboard/                   the page source: _css.html, _body.html, index.html (built), market_accuracy.js, deal_charts.js, app.js, vendor/
outputs/dash2/               the dashboard's datasets (the address lookups stay on your own machine)
public/index.html            the single-file public copy
docs/How-the-model-works.pdf plain-English explanation of the model, its uses and its limits
```

## Dashboard

- **Value a property**: pick an address to fill size, age and energy rating from its EPC, or paste a
  Rightmove/Zoopla listing to read price, rent, bedrooms, type, size and postcode (a listing naming only a district
  clears the last home's postcode and offers it back as a dashed "Keep" chip). Gives the estimate, range,
  condition adjustment, asking-price check and nearby comparable sales.
- **Investing** (was Buy-to-let): the home on the first tab against recent sales in its neighbourhood, in % and in
  standard deviations: price against estimated value (out-of-sample backtest residuals), price per m² and gross yield,
  with a combined score (the share of recent sales it beats), anti-social behaviour there and Doncaster's landlord court claims, and its total return against the opportunity cost and a typical home there. A rent estimate
  linked to value (see below) with its likely range, the ONS bedroom average, the housing benefit cap and the rents
  needed to match the opportunity cost or break even with the mortgage. Then the full deal analyser (stamp duty with
  surcharge, Section 24 with the credit capped at the property profit and unused interest and losses carried forward, or limited company, April 2027 tax rates, lender stress test, stress scenarios, 10-year
  projection with an after-tax IRR) and a buy-refurbish-sell calculator. The sale in year 10 pays tax on the gain:
  for an individual, capital gains tax above the £3,000 exemption, at 18% on the part that fits in the unused
  basic-rate band (£37,700, frozen to April 2031, less other taxable income, £20,000 unless entered, and that year's
  rental profit) and 24% on the rest (HMRC's own example: £20,000 income and a £52,600 gain gives £10,842); corporation
  tax for a company (no exemption). Only improvements come off the gain; the rest of the works and EPC upgrade
  (repairs, decorating) comes off the first year's rental profit. Corporation tax has marginal relief: 19% up to £50,000 of profit, 25% from £250,000. The projection's
  price growth defaults to the figure the scorecard uses (the neighbourhood's 10- or 5-year growth); the "matches the
  gilt" rent solves the scorecard's own total return, risk allowance included. Prices, rents or EPC costs you type into
  the deal stay when you edit the same home's details and reset for a different home. Each panel checks the inputs it
  uses and clears until they are fixed. The IRR is every rate between -99% and 10,000% that gives a zero NPV, found by exact root isolation
  (repeated and very close rates included); when the cash flows change sign more than once the page says the IRR can
  mislead and gives the NPV at the 10-year gilt.
- **Three views of a deal** (Investing tab):
  - *What the mortgage rate does*: the first year's monthly cash flow before and after tax at every rate from 0%,
    with the break-even rate and the rates at which the lender's stress test fails. A slider, or a drag across the
    chart, sets the deal's rate and everything follows (the scale holds still during a drag).
  - *What matters most*: a tornado of the 10-year IRR after tax (or the first year's cash flow) with each input
    lowered and raised by a set amount, one at a time: price paid ±10% (the home's value unchanged), rent ±10%, rate,
    price growth, rent growth and cost inflation ±1 point, voids ±2 weeks, maintenance ±50%, deposit ±10 points (never
    below the usual 25% minimum). The swings are in `config/assumptions.csv`.
  - *If prices follow a past decade*: the deal's equity over 10 years if its price had followed the neighbourhood's
    repeat-sales index over the 10 years after each purchase year since 1995 (22 overlapping stretches), as a fan
    (every year's range, the middle half, the median, your own growth figure), and each purchase year's after-tax IRR
    against the 10-year gilt. Rent growth, costs and the mortgage stay as entered; it shows how much timing has
    mattered, not a forecast.
- **Sales history**: picking an address fills in its last Land Registry sale (a strong input) and lists every sale since 1995 in today's money.
- **What would works add?**: re-runs the model with an extension, loft conversion, better energy rating or refurbishment, against sourced 2026 build costs.
- **Possible-extension prompt**: flags homes whose OS building outline looks bigger than their certificate's floor area, and old certificates.
- **Prices by area tier** (Market tab): cheaper areas have risen fastest since 2015.
- **Prices since 1995** (Areas tab): pick a period with a two-handle slider or quick buttons (since 1995, since 2000,
  20, 10 or 5 years, 2007 to 2013), or drag across Doncaster's line; the line stays whole with the period shaded, the map
  shows each neighbourhood's growth over it against Doncaster's (or each year's change) and the bars race growth over it.
- **Tenancies ending in court** sits at the bottom of the Market tab.
- **Estimate panel**: value, 80% range drawn as a bar (with the asking price if given) and a confidence level with
  the typical error for a home like this.
- **Model accuracy tab**: against simple methods, year-by-year backtest, accuracy by confidence level, the assessors'
  fairness checks, data layers, and every change tested.
- **Why this estimate**: a SHAP breakdown of what moved the value up or down, computed in the browser, including the
  home's certificate history (for example, a home last certified as a let).
- **Council tax band check** and a private **Saved** list of properties with their estimates and buy-to-let numbers.
- **Around this home**: flood risk, nearest station, schools with Ofsted grades, supermarket, GP, park, junction, main road.
- **Areas and rents**: Doncaster's 39 named neighbourhoods. Search by name, town, ward, postcode sector or
  postcode; each neighbourhood shows its typical prices by type, gross and net yield, price growth over 1, 5, 10 and
  20 years (with 80% ranges), total return, return above an opportunity cost (10-year gilt, Bank Rate or your own
  rate), the 2008 fall and recovery, Census 2021 tenure, flood, EPC and deprivation, and the value of a typical home
  since 1995. A ranked "best buy-to-let" list, an income-against-growth chart and a sortable table cover all 39.
  The map colours red for worse and blue for better (grey about the Doncaster average) on returns, growth, liquidity,
  flood risk, deprivation and EPC, with blue shades for prices. Rents by bedrooms; housing benefit caps.
- **Motion**: a "Prices since 1995" time-lapse (yearly change by neighbourhood, a bar race on growth since 1995,
  Doncaster's line with the boom, 2008 peak, low and recovery), a "hurdle rate" play on the map that turns
  neighbourhoods from red to blue as the rate elsewhere falls, and a buy-to-let ranking that builds up when first seen.
  Nothing plays by itself when the reader's system asks for reduced motion.
- **Light or dark**: a switch in the header (the page otherwise follows the system or app theme).
- **Version and changelog**: the header shows the dashboard's version and date (version 27, 13 Oct 2026); it opens a
  Changelog tab listing every version. The list is the `changelog` dataset (`outputs/dash2/changelog.csv`, one row per change): add rows with the next version number for each
  release and the header follows.
- **Market** and **Model accuracy** tabs, and a method note.

### Public copy

`public/index.html` is one self-contained file (about 11 MB) holding the page, the model and its data, built by
`python src/build_standalone.py` from the dashboard datasets. It runs in any browser with no server. It is published at
https://oliverhutch2021.github.io/doncaster-property-model/ by `.github/workflows/pages.yml`, which deploys `public/` to
GitHub Pages on every push to `main` (repository Settings → Pages → Source: GitHub Actions).

The public copy leaves out house-level address data: the EPC address lookup, sales history and the saved list are hidden,
and comparable sales show the street without the house number. Everything else, including the estimate, range, SHAP
breakdown, what-if, buy-to-let and maps, works as in the dashboard.

## Key design decisions

See `DECISIONS.md` for the full decision log. In short:

- **Temporal split, not random.** Train 2015-2023, tune 2024, test 2025-26: the model is judged the way it would be used.
- **What the model knows, and when.** Strictly before the sale: the price index (sales known two months earlier),
  local price levels and nearest-sale prices, energy ratings and certificate history. Not strictly: size and build
  details can come from a later certificate (measured above: little aggregate change); 2025 deprivation scores and
  current plot sizes apply to every sale (sensitivity-tested only); neighbour price per m² uses best-known floor areas
  (not measured).
- **Condition from repeat sales** (`src/condition_calibration.py`). Homes resold within 3-18 months (n = 1,007) sold
  7.6% below a model without last-sale information at purchase and 7.7% above it at resale. Homes resold after 5 years
  or more (n = 2,633) sold about 1.4% above it at both ends, for reasons that aren't a quick refurbishment, so that is
  taken off: the setting is -8.9% for "needs full renovation" and +6.2% for "recently refurbished" (it was -8.3% and
  +7.7% before the fourth review). Each home's sales stay in one fold, so the model never learns a home's price from
  its own other sale. Against the full model (which sees the last sale), the resale premium all but disappears (+0.6%),
  because it already reads a quick resale of a cheap purchase as a refurbished home. So the setting depends on what the
  estimate knows (fifth review). Without a last sale it is the figure above. With one, it is measured against the full
  model: a purchase in need of renovation that had an earlier sale of its own (n = 546, a median 10 years before) sold
  4.7% below it, and a resale within 18 months of the last sale 0.6% above it; dated and good are half of those. A
  better condition after an older last sale uses the no-last-sale premium, a case the data can't measure, and the page
  says so. `src/predict.py` applies the same rule.
- **Ranges that are checked.** 80% ranges scale with each estimate's confidence (a second model predicts its typical
  error; calibrated on 2024, checked on 2025-26), with their own scaling for homes typed in by hand.

## Limitations

- Condition isn't in any open dataset, so it is a user input calibrated from repeat sales.
- Rents are Doncaster-wide averages by type, so area yields overstate returns in the cheapest areas.
- About 6% of sales have no matched EPC; they are valued without size, with a wider range.
- Not a survey, mortgage valuation or financial advice.
