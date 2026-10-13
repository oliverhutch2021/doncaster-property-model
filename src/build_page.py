"""The dashboard page from its source, in one place: dashboard/index.html = dashboard/_css.html + dashboard/_body.html.
The script is dashboard/app.js and d3 is dashboard/vendor/d3.min.js; these four files are what the Claude dashboard
publishes (files/index.html, files/app.js) and what src/build_standalone.py builds the public copy from. The data the
page reads lives in outputs/dash2/.
  python src/build_page.py           write dashboard/index.html
  python src/build_page.py --check   exit 1 if dashboard/index.html isn't the current source (used by tests/test_build.py)"""
import pathlib, sys
P = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
page = (P / "_css.html").read_text(encoding="utf-8") + (P / "_body.html").read_text(encoding="utf-8")
if "--check" in sys.argv:
    ok = (P / "index.html").exists() and (P / "index.html").read_bytes() == page.encode("utf-8")
    print("dashboard/index.html is", "current" if ok else "OUT OF DATE: run python src/build_page.py"); sys.exit(0 if ok else 1)
(P / "index.html").write_text(page, encoding="utf-8", newline="\n"); print("wrote dashboard/index.html", f"{len(page.encode()) / 1e3:.0f} kB")
