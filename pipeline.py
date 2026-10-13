"""The whole build, in order: raw data -> features -> train -> evaluate -> export -> page.

  python pipeline.py --list              the steps, what each one writes, and the stage it belongs to
  python pipeline.py                     run every step
  python pipeline.py --from lookups      run from a stage (or a script name) to the end
  python pipeline.py --only evaluate     run one stage (or one script)
  python pipeline.py --dry-run ...       print what would run

The scripts carry version numbers because the project grew a layer at a time (README, docs/DECISIONS.md); each later
export adds to or replaces the datasets of the ones before, so the order below is the order the published files were
built in, and it matters. Experiments whose only output is a table of test results now live in experiments/ (their
results are kept in outputs/*.json and read from there); nothing here needs them to run.

What hasn't been done: a single rerun of every step from freshly downloaded data. Each step was run as the project
grew, and rerunning the last ones reproduces the published model exactly (src/production_v18.py gives the same 2,043
trees, byte for byte). Raw data refreshed since (new certificates, new sales) will move the numbers.
Two steps need things that aren't downloadable for you: the EPC bulk file needs your own registration, and
src/model_v5_tune.py takes hours (its settings are kept in outputs/metrics_v5_tests.json, so it's skipped unless asked).
"""
import argparse, pathlib, subprocess, sys, time
ROOT = pathlib.Path(__file__).resolve().parent
S = lambda f, *a: ("src/" + f,) + a
STEPS = [
    # stage, script and arguments, what it does
    ("data", S("fetch_data.sh"), "download the raw data (Land Registry, ONS, OS, police.uk, MoJ ...; the EPC file needs your own registration)"),
    ("data", S("fetch_postcodes.py"), "postcode centroids, deprivation and areas"),
    ("data", S("build_dataset.py"), "joins the raw files in DuckDB (sql/01-03), with row-count checks after each join"),
    ("data", S("epc_match.py"), "matches certificates to sales by postcode and address -> data/processed/sales_epc.parquet"),
    ("data", S("amenities.py"), "flood, transport, schools and rural-urban class per postcode"),
    ("data", S("osm_features.py"), "OpenStreetMap places and distances per postcode"),
    ("data", S("plots.py"), "plot size per home: OS Open UPRN points inside Land Registry title plans"),
    ("data", S("buildings.py"), "building footprint per home (OS OpenMap Local)"),
    ("features", S("model_v2.py"), "price index, nearest-sale and last-sale features, and the training clean-up list (outputs/train_keep_ids.csv)"),
    ("features", S("features_v5.py"), "plot, street and postcode prices, extra certificate fields -> model_frame_v5"),
    ("features", S("features_v7.py"), "certificate history per sale -> model_frame_v7, the frame every model below trains on"),
    ("export", S("export_v2.py"), "first dashboard datasets: rents, housing benefit caps, rules, sectors, levels, postcodes, index"),
    ("export", S("export_v3_extras.py"), "places, postcode extras and the neighbourhood map"),
    ("export", S("export_v4.py"), "area bias and sector tables"),
    ("export", S("export_v5.py"), "sector names and the v5 tables"),
    ("lookups", S("export_v5_lookups.py"), "address lookup (outputs/dash2/epc_*.csv: holds addresses, stays private), street levels, council tax mix"),
    ("lookups", S("export_v6_extras.py"), "index by area tier, sales history and footprints in the address lookup, cost assumptions"),
    ("train", S("model_v5_tune.py"), "LightGBM settings chosen on 2024 (hours; skipped unless named with --only)"),
    ("train", S("export_v7.py"), "test model (2015-23, early-stopped on 2024), local correction tuned on 2024, 80% ranges, accuracy, browser trees"),
    ("lookups", S("export_v7_lookups.py"), "certificate history per address, as of the valuation month"),
    ("evaluate", S("compare_methods.py"), "the model against the quick methods and a hedonic regression on the same features"),
    ("evaluate", S("model_v8_backtest.py"), "year-by-year backtest 2020-2026 with the index as known at the time"),
    ("evaluate", S("model_v8_confidence.py"), "confidence model and adaptive ranges"),
    ("evaluate", S("model_v8_typed.py"), "confidence scaling for homes typed in by hand"),
    ("evaluate", S("export_v8.py"), "accuracy-tab datasets: backtest, ratio study, confidence"),
    ("export", S("areas_v9.py"), "neighbourhood figures, repeat-sales indices, outlines"),
    ("export", S("assumptions_v9.py"), "opportunity costs and holding period, added to config/assumptions.csv if missing (never overwritten)"),
    ("export", S("invest_v10.py"), "rent model and neighbourhood sale spreads"),
    ("export", S("tenants_v11.py"), "landlord court claims and anti-social behaviour"),
    ("export", S("refurb_v13.py"), "refurbishment costs, into config/assumptions.csv"),
    ("train", S("production_v18.py"), "the production model: every kept sale before the last 12 months, with the shared cleaning rule"),
    ("evaluate", S("strict_eval_v18.py"), "strict timing check, seed 42"),
    ("evaluate", S("strict_eval_v19.py"), "strict timing check, seeds 7 and 2026, paired with seed 42"),
    ("evaluate", S("eval_cohorts_seeds.py"), "accuracy by sale year and new build (registration lag), and seed averaging"),
    ("evaluate", S("condition_calibration.py", "--write"), "condition setting: folds grouped by home, long-hold resales subtracted"),
    ("page", S("apply_assumptions.py"), "copies config/assumptions.csv, the one place assumptions are kept, into the dashboard"),
    ("page", S("flag_doncaster_postcodes.py"), "marks postcodes outside Doncaster"),
    ("page", S("build_page.py"), "dashboard/index.html from dashboard/_css.html and _body.html"),
    ("page", S("assemble_model_dir.py"), "model/ for src/predict.py (add --with-addresses yourself for the address lookup)"),
    ("page", S("build_standalone.py"), "the public single-file copy (outputs/standalone/index.html)"),
]
STAGES = ["data", "features", "export", "lookups", "train", "evaluate", "page"]
SLOW = {"src/model_v5_tune.py"}

def name(step): return pathlib.Path(step[1][0]).stem

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="start", help="a stage or a script name"); ap.add_argument("--only", help="a stage or a script name")
    a = ap.parse_args()
    if a.list:
        for i, st in enumerate(STEPS, 1): print(f"{i:2d}. {st[0]:9s} {' '.join(st[1]):45s} {st[2]}")
        sys.exit(0)
    steps = STEPS
    if a.only:
        steps = [st for st in STEPS if a.only in (st[0], name(st))]
    elif a.start:
        k = next((i for i, st in enumerate(STEPS) if a.start in (st[0], name(st))), None)
        if k is None: sys.exit(f"no stage or script called {a.start}")
        steps = STEPS[k:]
    if not a.only: steps = [st for st in steps if st[1][0] not in SLOW]
    if not steps: sys.exit("nothing to run")
    for st in steps:
        cmd = (["bash"] if st[1][0].endswith(".sh") else [sys.executable]) + [str(ROOT / st[1][0]), *st[1][1:]]
        print(f"[{st[0]}] {' '.join(st[1])}: {st[2]}", flush=True)
        if a.dry_run: continue
        t0 = time.time(); r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode: sys.exit(f"stopped: {st[1][0]} failed (exit {r.returncode})")
        print(f"   done in {time.time() - t0:,.0f} s", flush=True)
