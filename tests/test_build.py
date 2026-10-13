"""The shipped page can be rebuilt from what ships (fifth review).

  1. dashboard/index.html is dashboard/_css.html + dashboard/_body.html (src/build_page.py --check)
  2. the dashboard's assumptions are config/assumptions.csv, unchanged (src/apply_assumptions.py)
  3. src/build_standalone.py, run on dashboard/ and outputs/dash2/, gives the public copy byte for byte
     (public/index.html in the zip, outputs/standalone/index.html in a full checkout)
  4. no page file is over 256 KB, the most the Claude dashboard accepts for one file (index.html and each script it loads)
  python tests/test_build.py"""
import filecmp, os, pathlib, re, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]; fails = []
def check(name, ok, detail=""):
    print("PASS" if ok else "FAIL", name, detail); (None if ok else fails.append(name))
r = subprocess.run([sys.executable, str(ROOT / "src/build_page.py"), "--check"], capture_output=True, text=True)
check("1 dashboard/index.html is built from its source", r.returncode == 0, r.stdout.strip())
check("2 the dashboard's assumptions are config/assumptions.csv", filecmp.cmp(ROOT / "config/assumptions.csv", ROOT / "outputs/dash2/assumptions.csv", shallow=False))
shipped = next((p for p in (ROOT / "public/index.html", ROOT / "outputs/standalone/index.html") if p.exists()), None)
with tempfile.TemporaryDirectory() as tmp:
    out = pathlib.Path(tmp) / "index.html"
    r = subprocess.run([sys.executable, str(ROOT / "src/build_standalone.py")], capture_output=True, text=True, env={**os.environ, "DPM_OUT": str(out)})
    same = r.returncode == 0 and shipped is not None and filecmp.cmp(out, shipped, shallow=False)
    check("3 the public copy rebuilds byte for byte", same, (r.stderr.strip().splitlines() or [""])[-1] if r.returncode else f"{out.stat().st_size / 1e6:.1f} MB vs {shipped}")
page = ROOT / "dashboard/index.html"
files = [page] + [ROOT / "dashboard" / f for f in re.findall(r'<script src="([\w.]+)"></script>', page.read_text(encoding="utf-8"))]
big = [f"{f.name} {f.stat().st_size:,} bytes" for f in files if f.stat().st_size > 256 * 1024]
check("4 every page file is under 256 KB", not big, ", ".join(big) or ", ".join(f"{f.name} {f.stat().st_size / 1024:.0f} KB" for f in files))
sys.exit(1 if fails else 0)
