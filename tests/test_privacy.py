"""What the shared copies must not carry (fourth review).

  1. the public page (public/index.html, or outputs/standalone/index.html in a full checkout) holds no house numbers or
     names: comparable sales show the street and postcode only, and no address-level certificate lookup is embedded
  3. (shared copy) comparable sales in outputs/dash2/comps.csv and model/comps.csv keep the street only
  2. the shared zip holds no address lookup (epc_*.csv in model/ or outputs/dash2/): the EPC licence keeps certificate
     addresses under Royal Mail terms, and they are treated as personal data. Only checked when run from the zip (a full
     checkout has data/, which the zip leaves out).
  python tests/test_privacy.py"""
import csv, io, json, pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
page = next((p for p in (ROOT / "outputs/standalone/index.html", ROOT / "public/index.html") if p.exists()), None)
fails = []
if page is None: print("SKIP 1: no public page built")
else:
    html = page.read_text(encoding="utf-8")
    blob = json.loads(re.search(r'<script id="dpm-data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    rows = list(csv.DictReader(io.StringIO(blob["csv"]["comps"])))
    leaks = [r["address"] for r in rows if re.search(r"\d|\b[A-Z]{2,}\b", r["address"])]
    epc = [k for k in blob["csv"] if k.startswith("epc_") and blob["csv"][k].count("\n") > 1]
    print(f"{'PASS' if not leaks else 'FAIL'} 1a {len(rows):,} comparable sales, {len(leaks)} with a house number or name", leaks[:5])
    print(f"{'PASS' if not epc else 'FAIL'} 1b no address-level certificate data embedded", epc[:3])
    if leaks or epc: fails.append(1)
if (ROOT / "data").exists(): print("SKIP 2: full checkout (model/ and outputs/dash2/ hold your own address lookup)")
else:
    found = sorted(str(p.relative_to(ROOT)) for d in ("model", "outputs/dash2") for p in (ROOT / d).glob("epc_*.csv"))
    print(f"{'PASS' if not found else 'FAIL'} 2 no address lookup in model/ or outputs/dash2/", found[:3])
    if found: fails.append(2)
    # 3. comparable sales in the shared copy keep the street only (src/addresses.py --strip-shared-copy)
    import csv as _csv
    for f in (ROOT / "outputs/dash2/comps.csv", ROOT / "model/comps.csv"):
        if not f.exists(): continue
        bad = [r["address"] for r in _csv.DictReader(open(f, newline="", encoding="utf-8")) if re.search(r"\d|\b[A-Z]{2,}\b", r["address"])]
        print(f"{'PASS' if not bad else 'FAIL'} 3 {f.relative_to(ROOT)}: no house numbers or names", bad[:3])
        if bad: fails.append(3)
sys.exit(1 if fails else 0)
