"""Gather what src/predict.py needs into model/, from the files the dashboard is built from, so the two can't drift apart.

  boosters   outputs/model/doncaster_lgbm_v7.txt (src/production_v18.py), outputs/model/confidence_v8.txt (src/model_v8_confidence.py)
  lookups    outputs/dash2/: model_meta.json, comps.csv, levels.csv, street_levels.csv, price_index.csv, postcodes.csv, condition.csv
  comps.csv  street only (house numbers and names removed, src/addresses.py) unless --with-addresses
  addresses  outputs/dash2/epc_<district>.csv, only with --with-addresses. These hold every certificate's address, which the
             EPC licence keeps under Royal Mail terms (the department treats address-level EPC data as personal data), so
             they stay on your own machine: the shared zip leaves them out, and predict.py --address needs them.
Old files in model/ that aren't listed here are left alone."""
import pathlib, shutil, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]; M = ROOT / "model"; D = ROOT / "outputs/dash2"; OM = ROOT / "outputs/model"
M.mkdir(exist_ok=True)
files = [(OM / "doncaster_lgbm_v7.txt", None), (OM / "confidence_v8.txt", None)] + [(D / f, None) for f in
         ("model_meta.json", "comps.csv", "levels.csv", "street_levels.csv", "price_index.csv", "postcodes.csv", "condition.csv")]
if "--with-addresses" in sys.argv: files += [(f, None) for f in sorted(D.glob("epc_*.csv"))]
for src, _ in files:
    shutil.copy2(src, M / src.name); print("model/" + src.name, f"{src.stat().st_size / 1e6:.1f} MB")
# comparable sales keep the street only (no house number or name) unless you build your own copy with addresses;
# predict.py doesn't use the address column
if "--with-addresses" not in sys.argv:
    sys.path.insert(0, str(ROOT / "src")); from addresses import strip_file
    print("model/comps.csv: street only,", strip_file(M / "comps.csv"), "rows")
if "--with-addresses" not in sys.argv: print("address lookups not copied (add --with-addresses on your own machine)")
