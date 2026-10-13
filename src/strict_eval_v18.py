"""Strict historical evaluation (v18). The headline test lets a sale take its size, rooms, age, built form and other
physical details from a certificate lodged up to 90 days after the sale, or failing that from the home's first
certificate, however late (src/epc_match.py, src/features_v5.py). Deprivation (IMD 2025) and plot size (2026 title
plans) are also applied to every sale whatever its date. This script measures what that is worth.

  current  the published set-up: test model trained 2015-2023, early-stopped on 2024, local correction (alpha, k from
           model_meta), scored on January 2025 to August 2026
  strict   the same, but each sale's own certificate details come only from certificates lodged on or before the sale
           date (no grace period, no later certificate). Energy and certificate-history fields were already strict.
  strict, no later-dated area data
           strict, and the deprivation and plot-size inputs removed altogether. There is no as-of-date version of them
           here, so this is a bound: it also throws away what those inputs legitimately add.
Neighbour price per m2 still uses each neighbour's best-known floor area (a second-order effect, noted).
Also repeated for 2020 (the most affected backtest year, 3.4% of sales on a later certificate): trained to 2018,
early-stopped on 2019, no local correction, with the index as published (the full backtest rebuilds the index as known
at the time; this check isolates the certificate rule only).
Output: outputs/strict_eval_v18.json, outputs/dash2/strict_eval.csv"""
import json, pathlib, sys, numpy as np, pandas as pd, duckdb
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import export_v7 as E
from epc_match import load_epc

s, keep, OUT, D = E.s.copy(), E.keep, E.OUT, E.D
RAW = E.ROOT / "data/raw"
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42) | tuned
meta = {r["key"]: r["value"] for r in json.load(open(D / "model_meta.json"))}; ALPHA, K = float(meta["local_alpha"]), int(meta["local_k"])

# ---------- strict certificate details: latest certificate lodged on or before the sale ----------
e = load_epc()
x = duckdb.sql(f"""select certificate_number, walls_description, number_open_fireplaces, floor_height, floor_level, flat_top_storey,
        number_heated_rooms, glazed_area from read_csv_auto('{RAW}/epc_doncaster.csv', all_varchar=true, sample_size=-1)""").df()
e = e.merge(x, on="certificate_number", how="left")
w = e.walls_description.fillna("").str.lower()
e["wall_type"] = np.select([w.str.contains("cavity"), w.str.contains("solid brick"), w.str.contains("system"), w.str.contains("timber"),
                            w.str.contains("stone|granite|sandstone")], [0, 1, 2, 3, 4], np.nan)
e["fireplaces"] = pd.to_numeric(e.number_open_fireplaces, errors="coerce")
e["ceiling_m"] = pd.to_numeric(e.floor_height, errors="coerce").where(lambda v: v.between(1.8, 5))
fl = e.floor_level.fillna("").str.lower()
e["floor_level_n"] = np.select([fl.str.contains("basement"), fl.str.contains("ground"), fl.str.contains("mid"), fl.str.contains("top")], [-1, 0, 1.5, 3],
                               pd.to_numeric(fl.str.extract(r"(\d+)")[0], errors="coerce"))
e["floor_level_n"] = np.where(fl == "", np.nan, e.floor_level_n)
e["top_floor"] = e.flat_top_storey.map({"Y": 1.0, "N": 0.0}); e["heated_rooms"] = pd.to_numeric(e.number_heated_rooms, errors="coerce")
e["glazed_area_n"] = e.glazed_area.fillna("").str.lower().map({"much less than typical": -2, "less than typical": -1, "normal": 0, "more than typical": 1, "much more than typical": 2})
e["bungalow"] = (e.epc_type == "Bungalow").astype(float).where(e.epc_type.notna())
e["built_form_code"] = e.built_form.map({"Detached": 0, "Semi-Detached": 1, "End-Terrace": 2, "Mid-Terrace": 3, "Enclosed End-Terrace": 4, "Enclosed Mid-Terrace": 5})
PH = ["floor_area", "rooms", "age_year", "extensions", "bungalow", "built_form_code", "wall_type", "ceiling_m", "floor_level_n", "top_floor", "heated_rooms", "glazed_area_n", "fireplaces"]
e = e.dropna(subset=["dwelling", "lodgement_date"]).copy(); e["dwelling"] = e.dwelling.astype(str)
sd = s.loc[s.dwelling.notna(), ["unique_id", "dwelling", "sale_date"]].copy(); sd["dwelling"] = sd.dwelling.astype(str)
a = pd.merge_asof(sd.sort_values("sale_date"), e[["dwelling", "lodgement_date"] + PH].sort_values("lodgement_date"),
                  left_on="sale_date", right_on="lodgement_date", by="dwelling", direction="backward", allow_exact_matches=True)
strict = s.copy().drop(columns=PH).merge(a[["unique_id"] + PH], on="unique_id", how="left")
assert len(strict) == len(s)
strict = strict.set_index("unique_id").loc[s.unique_id].reset_index()          # same row order as s
changed = ~np.isclose(strict.floor_area.fillna(-1).values, s.floor_area.fillna(-1).values)
print(f"strict: floor area differs for {changed.mean():.1%} of sales; missing {s.floor_area.isna().mean():.1%} -> {strict.floor_area.isna().mean():.1%}")

NO_LATER = [c for c in E.FULL if not (c.startswith("imd_") or c.startswith("plot_"))]
def run(frame, cols, label, tr_end="2023-12-31", va_end="2024-12-31", te_from="2024-12-31", te_to="2026-12-31", correct=True):
    k = frame.unique_id.isin(keep) | (frame.sale_date > va_end)
    tr = frame[(frame.sale_date <= tr_end) & k]; va = frame[(frame.sale_date > tr_end) & (frame.sale_date <= va_end) & k]
    m = E.fit_es(tr, va, P, cols); n = m.best_iteration
    te = frame[(frame.sale_date > te_from) & (frame.sale_date <= te_to)].copy()
    p = m.predict(E.X(te, cols), num_iteration=n) + te.log_idx.values
    if correct:
        pool = frame[frame.sale_date > tr_end].copy(); pool["r"] = pool.y_defl.values - m.predict(E.X(pool, cols), num_iteration=n)
        p = p + ALPHA * E.correction(pool, te, K)
    r = E.met(te, p) | {"trees": n}
    later = (te.epc_days_before_sale < 0).values
    r["n_later_cert"] = int(later.sum())
    if later.any(): r["mdape_later_cert_sales"] = float(np.median(np.abs(np.exp(p[later]) - te.price.values[later]) / te.price.values[later]))
    print(label, {k_: (round(v, 4) if isinstance(v, float) else v) for k_, v in r.items()}); return r

res = {"test_2025_26": {}, "year_2020": {}}
res["test_2025_26"]["current"] = run(s, E.FULL, "current")
res["test_2025_26"]["strict"] = run(strict, E.FULL, "strict")
res["test_2025_26"]["strict_no_later_area_data"] = run(strict, NO_LATER, "strict, no IMD or plot")
y20 = dict(tr_end="2018-12-31", va_end="2019-12-31", te_from="2019-12-31", te_to="2020-12-31", correct=False)
res["year_2020"]["current"] = run(s, E.FULL, "2020 current", **y20)
res["year_2020"]["strict"] = run(strict, E.FULL, "2020 strict", **y20)
res["share_later_cert_by_year"] = {str(y): round(float(g.mean()), 4) for y, g in (s.epc_days_before_sale < 0).groupby(s.sale_date.dt.year)}
json.dump(res, open(OUT / "strict_eval_v18.json", "w"), indent=1)
LAB = {("test_2025_26", "current"): "2025-26 test, published rules", ("test_2025_26", "strict"): "2025-26 test, only certificates lodged by the sale date",
       ("test_2025_26", "strict_no_later_area_data"): "2025-26 test, strict and without deprivation or plot size (a bound)",
       ("year_2020", "current"): "2020, published rules", ("year_2020", "strict"): "2020, only certificates lodged by the sale date"}
rows = [[split, k_, LAB[(split, k_)], v["n"], round(v["mdape"], 5), round(v["within10"], 4), round(v["within20"], 4), round(v["mae"]), v["n_later_cert"],
         round(v.get("mdape_later_cert_sales", float("nan")), 5)] for split in ("test_2025_26", "year_2020") for k_, v in res[split].items()]
E.wcsv("strict_eval.csv", ["split", "variant", "label", "n", "mdape", "within10", "within20", "mae", "n_later_cert", "mdape_later_cert"], rows)
print(json.dumps(res["share_later_cert_by_year"]))
