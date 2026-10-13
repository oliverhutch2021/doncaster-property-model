"""House numbers and names out of comparable-sale addresses, for everything that's shared.

Comparable-sale addresses are "PAON SAON Street", with the house number or name (PAON, SAON) in capitals and the street
title-cased (src/production_v18.py). Every leading all-capitals or numbered word goes: "ROSE COTTAGE 12 Main Street"
-> "Main Street". An address with no street part becomes "" (the postcode is shown instead). Running it twice changes
nothing. Used by src/build_standalone.py (the public page) and src/assemble_model_dir.py (model/ for the shared copy).
Run directly, it rewrites outputs/dash2/comps.csv and model/comps.csv street-only, for a copy you are about to share:
  python src/addresses.py --strip-shared-copy"""
import csv, io, pathlib, re, sys

def street_only(addr):
    toks = addr.split()
    while toks and (re.search(r"\d", toks[0]) or re.fullmatch(r"[A-Z0-9'&.,/()\-]+", toks[0])): toks.pop(0)
    return " ".join(toks)

def strip_file(path):
    with open(path, newline="", encoding="utf-8") as f: rows = list(csv.DictReader(f))
    for r in rows: r["address"] = street_only(r["address"])
    s = io.StringIO(); w = csv.DictWriter(s, fieldnames=list(rows[0].keys()), lineterminator="\n"); w.writeheader(); w.writerows(rows)
    pathlib.Path(path).write_text(s.getvalue(), encoding="utf-8"); return len(rows)

if __name__ == "__main__" and "--strip-shared-copy" in sys.argv:
    root = pathlib.Path(__file__).resolve().parents[1]
    for p in (root / "outputs/dash2/comps.csv", root / "model/comps.csv"):
        if p.exists(): print(p.relative_to(root), strip_file(p), "rows, street only")
