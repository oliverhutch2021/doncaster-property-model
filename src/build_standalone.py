"""Build a single self-contained HTML file of the dashboard that runs anywhere: double-click it, email it, or host it
for free (GitHub Pages, Netlify). Same page and script as the Claude dashboard, with:
  - a small stand-in for the dashboard's `dash` data API, serving the datasets embedded in the file
  - d3 inlined, and its own light/dark theme colours and fonts
  - no house-level address data: the EPC address lookup, sales history and saved list are left out, and comparable
    sales show the street and postcode without the house number
Reads the page source from dashboard/ (_css.html, _body.html, the scripts it names (market_accuracy.js, app.js) and
vendor/d3.min.js: the canonical copy, see
src/build_page.py) and its data from outputs/dash2/ (and outputs/dash/market_monthly.csv). Deterministic: the same
inputs give the same file byte for byte, which tests/test_build.py checks against the shipped public/index.html.
Output: outputs/standalone/index.html, or the path in DPM_OUT"""
import csv, io, json, os, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parents[1]; D = ROOT / "outputs/dash2"; OUT = ROOT / "outputs/standalone"; OUT.mkdir(exist_ok=True)
# DPM_TEST_BUILD=<path>: a private copy WITH the address files, for browser tests only (never published or shared)
TEST = os.environ.get("DPM_TEST_BUILD")
SRC = ROOT / "dashboard"; D3 = SRC / "vendor/d3.min.js"   # d3 7.9.0 (ISC licence)
CSV = ["ablation", "accuracy", "accuracy_breakdown", "area_bias", "assumptions", "comps", "condition", "ct_mix", "ext_flag", "feature_importance",
       "layer_tests", "levels", "lha", "pc_extras", "places", "postcodes", "price_index", "rents", "rules", "sectors", "street_levels", "streets",
       "test_sample", "tier_index", "nbhd_index", "nb_dist", "rent_model", "possession", "changelog", "strict_eval"] + [k for k in ("method_compare", "backtest", "ratio_study", "confidence") if (D / f"{k}.csv").exists()]
JSON = ["model_trees", "model_meta", "lsoa_map", "neighbourhoods"] + (["conf_trees"] if (D / "conf_trees.json").exists() else [])

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f: return list(csv.DictReader(f))
from addresses import street_only   # house numbers and names out of comparable sales (src/addresses.py)

# CSVs travel as text and are parsed on first use (d3.csvParse, cells as text, as in the dashboard); JSON as JSON
def to_csv(rows):
    s = io.StringIO(); w = csv.DictWriter(s, fieldnames=list(rows[0].keys()), lineterminator="\n"); w.writeheader(); w.writerows(rows); return s.getvalue()
comps = read_csv(D / "comps.csv")
for r in comps: r["address"] = street_only(r["address"])
texts = {k: (D / f"{k}.csv").read_text(encoding="utf-8") for k in CSV if k != "comps"}
texts["comps"] = to_csv(comps)
if TEST:
    texts["comps"] = (D / "comps.csv").read_text(encoding="utf-8")
    for f in sorted(D.glob("epc_*.csv")): texts[f.stem] = f.read_text(encoding="utf-8")
texts["market_monthly"] = (ROOT / "outputs/dash/market_monthly.csv").read_text(encoding="utf-8")
data = {"csv": texts, "json": {k: json.load(open(D / f"{k}.json")) for k in JSON}}
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")

css = (SRC / "_css.html").read_text(encoding="utf-8"); body = (SRC / "_body.html").read_text(encoding="utf-8")
# the page's own scripts, in the order _body.html names them, inlined at the end (after d3 and the data shim)
SCRIPTS = re.findall(r'<script src="([\w.]+)"></script>', body)
assert SCRIPTS and SCRIPTS[-1] == "app.js", SCRIPTS
for f in SCRIPTS: body = body.replace(f'<script src="{f}"></script>', '')
app = "\n".join(f"<script>{(SRC / f).read_text(encoding='utf-8')}</script>" for f in SCRIPTS)
assert "</script" not in "".join((SRC / f).read_text(encoding="utf-8") for f in SCRIPTS)
# the dashboard's own chart ramps (diverging blue-grey-red and sequential blue), light and dark
DIV_L = ["#256abf", "#5598e7", "#9ec5f4", "#f0efec", "#f4abab", "#e66767", "#b93535"]; DIV_D = ["#6da7ec", "#2a78d6", "#184f95", "#383835", "#8e2626", "#d03b3b", "#ec7e7e"]
SEQ_L = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]; SEQ = dict(light=SEQ_L, dark=SEQ_L[::-1])
ramps = lambda d, s: " ".join(f"--cds-chart-diverging-{i + 1}: {c};" for i, c in enumerate(d)) + " " + " ".join(f"--cds-chart-sequential-{i + 1}: {c};" for i, c in enumerate(s))
DARK = """color-scheme: dark;
  --color-bg: #1a1a19; --color-panel: #222220; --color-fg: #f4f3ef; --color-fg-muted: #c3c2b7; --color-border-line: #3a3a37;
  --color-ok: #4cc14c; --color-warn: #f0b23c; --color-bad: #ee6b6b;
  --cds-chart-grid: #30302d; --cds-chart-axis: #4a4a46; --cds-chart-muted: #4a4a46; --cds-chart-reference: #8f8e87;
  --cds-surface-popover: #2a2a28; --cds-border: #3a3a37; --cds-shadow-popover: 0 4px 16px rgba(0,0,0,.5); --cds-text-secondary: #c3c2b7;
  """ + ramps(DIV_D, SEQ["dark"])
theme = """<style>
:root { color-scheme: light;
  --font-anthropic-sans: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; --font-anthropic-serif: "Source Serif 4", Georgia, serif;
  --color-bg: #ffffff; --color-panel: #fcfcfb; --color-fg: #0b0b0b; --color-fg-muted: #52514e; --color-border-line: #e3e2dd;
  --color-ok: #0a7d0a; --color-warn: #a86400; --color-bad: #c03333;
  --cds-chart-grid: #ecebe7; --cds-chart-axis: #c9c8c1; --cds-chart-muted: #c9c8c1; --cds-chart-reference: #8f8e87;
  --cds-surface-popover: #ffffff; --cds-border: #e3e2dd; --cds-shadow-popover: 0 4px 16px rgba(0,0,0,.12); --cds-text-secondary: #52514e;
  --cds-font-size-title: 1.75rem; --cds-font-size-heading: 1.0625rem; --cds-font-size-body: 0.9375rem; --cds-font-size-caption: 0.8125rem; --cds-font-weight-medium: 600;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 12px; --cds-pad-lg: 18px; --cds-gap-xs: 4px; --cds-gap-sm: 10px; --cds-gap-md: 14px; --cds-gap-lg: 22px;
  --cds-radius: 8px; --cds-dur-slow: .3s; """ + ramps(DIV_L, SEQ["light"]) + """ }
:root[data-mode="dark"] { """ + DARK + """ }
@media (prefers-color-scheme: dark) { :root:not([data-mode="light"]) { """ + DARK + """ } }
html, body { margin: 0; background: var(--color-bg); color: var(--color-fg); }
#dash-root { padding: 24px 16px 40px; }
.dpm-foot { max-width: 1180px; margin: 28px auto 0; color: var(--color-fg-muted); font: 0.8125rem/1.5 var(--font-anthropic-sans); }
</style>"""
shim = """<script>
window.DPM_STANDALONE = __STANDALONE__;
(() => {
  const RAW = JSON.parse(document.getElementById('dpm-data').textContent), DATA = { ...RAW.json };
  const get = (id) => { if (!DATA[id] && RAW.csv[id] != null) DATA[id] = d3.csvParse(RAW.csv[id]); return DATA[id]; };
  const dark = () => { const m = document.documentElement.getAttribute('data-mode'); return m === 'dark' || (m !== 'light' && !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)); };
  const LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
  const DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
  const fns = [];
  window.dash = {
    get colors() { return dark() ? DARK : LIGHT; },
    data(id) {
      const rows = get(id);
      if (rows) return { status: 'ok', data: rows, columns: rows.length ? Object.keys(rows[0]) : [], refreshing: false, meta: [] };
      if (/^epc_/.test(id)) return { status: 'ok', data: [], columns: [], refreshing: false, meta: [] };   // no address register in the public copy
      return { status: 'missing', data: [], columns: [], refreshing: false, meta: [] };
    },
    onData(fn) { fns.push(fn); fn(); },
    setLink(name) { try { history.replaceState(null, '', '#' + name); } catch (e) { /* some browsers block this for local files */ } },
    params() { return {}; }, setParams() {}, resetParams() {}, refresh() {}
  };
  let t; const rerun = () => { clearTimeout(t); t = setTimeout(() => fns.forEach((f) => f()), 150); };
  window.addEventListener('resize', rerun);
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', rerun);
})();
</script>"""
foot = """<p class="dpm-foot">This public copy leaves out house-level address data: the address lookup, sales history and saved list.</p>"""
html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doncaster Property Model</title>
<meta name="description" content="Valuation, buy-to-let and area analysis for Doncaster homes, from open data.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Source+Serif+4:wght@400&display=swap" rel="stylesheet">
{theme}
{css}
</head><body>
<div id="dash-root">
{body}
{foot}
</div>
<script id="dpm-data" type="application/json">{blob}</script>
<script>/*! {(SRC / "vendor/LICENSE-d3.txt").read_text(encoding="utf-8").strip()} */
{D3.read_text()}</script>
{shim}
{app}
</body></html>"""
html = html.replace("__STANDALONE__", "false" if TEST else "true")
dest = pathlib.Path(TEST) if TEST else pathlib.Path(os.environ["DPM_OUT"]) if os.environ.get("DPM_OUT") else OUT / "index.html"
dest.write_text(html, encoding="utf-8")
print("wrote", dest, round(dest.stat().st_size / 1e6, 1), "MB")
