"""Every assumption the dashboard uses lives in one file, config/assumptions.csv (key, label, value, unit, source): rates
and taxes, running costs, refurbishment prices, risk settings. Edit it there, then run this step, which copies it into
the dashboard's dataset (outputs/dash2/assumptions.csv) unchanged. The scripts that used to write assumptions
(src/export_v2.py, src/export_v6_extras.py, experiments/assumptions_v9.py, experiments/refurb_v13.py) no longer do:
rerunning any of them can't put back an old value, as rerunning assumptions_v9.py once reset the gilt to 5.42%.
tests/test_build.py checks the two files are the same."""
import csv, pathlib, shutil, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]; SRC = ROOT / "config/assumptions.csv"; DST = ROOT / "outputs/dash2/assumptions.csv"
rows = list(csv.DictReader(open(SRC, newline="", encoding="utf-8")))
keys = [r["key"] for r in rows]; dup = {k for k in keys if keys.count(k) > 1}
bad = [r["key"] for r in rows if not r["source"].strip() or r["value"].strip() == ""]
if dup or bad: sys.exit(f"config/assumptions.csv: duplicate keys {sorted(dup)}, rows without a value or source {bad}")
DST.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(SRC, DST); print(f"{len(rows)} assumptions -> {DST.relative_to(ROOT)}")
