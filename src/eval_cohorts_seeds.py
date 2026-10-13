"""Two checks on the published test (fourth review).

1. Registration lag. Land Registry registers some sales months after completion, new builds above all: in this data
   new builds are 4.3% of 2025 test sales but none from February 2026, and August 2026 has 82 sales against a usual
   300-400. So the 2026 part of the test set is the sales that registered quickly. This scores the published test
   model (trained 2015-2023, early-stopped on 2024, local correction) separately by sale year, for the same months of
   each year, and for new builds against other homes.
2. Seed averaging. The test model refitted with LightGBM seeds 7 and 2026 as well as the published 42, each with its
   own local correction; the three estimates averaged on the log scale, against each seed alone.

Output: outputs/eval_cohorts_seeds.json, and the 'sale year' and 'new build' rows of outputs/dash2/accuracy_breakdown.csv
(rewritten in place; the other rows come from src/export_v7.py)."""
import csv, json, pathlib, sys, numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import export_v7 as E

s, OUT, D = E.s, E.OUT, E.D
tuned = json.load(open(OUT / "metrics_v5_tests.json"))["core_tuned"]["params"]
meta = {r["key"]: r["value"] for r in json.load(open(D / "model_meta.json"))}; ALPHA, K = float(meta["local_alpha"]), int(meta["local_k"])
tr23, va24 = E.between("2000-01-01", "2023-12-31", True), E.between("2023-12-31", "2024-12-31", True)
te = s[s.sale_date > "2024-12-31"].copy().reset_index(drop=True)

preds = {}
for seed in (42, 7, 2026):
    P = dict(objective="regression_l1", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=seed) | tuned
    m = E.fit_es(tr23, va24, P); n = m.best_iteration
    pool = s[s.sale_date > "2023-12-31"].copy(); pool["r"] = pool.y_defl.values - m.predict(E.X(pool), num_iteration=n)
    preds[seed] = m.predict(E.X(te), num_iteration=n) + te.log_idx.values + ALPHA * E.correction(pool, te, K)
    print(f"seed {seed}: {n} trees, median error {E.met(te, preds[seed])['mdape']:.4%}", flush=True)
avg = np.mean([preds[k] for k in preds], axis=0)

def score(mask, p):
    d = te[mask]; r = E.met(d, p[mask]); return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()}

p = preds[42]; yr, mo = te.sale_date.dt.year.values, te.sale_date.dt.month.values; nb = te.new_build.astype(bool).values
cohorts = {
    "all": score(np.ones(len(te), bool), p),
    "sold_2025": score(yr == 2025, p), "sold_2026_jan_aug": score(yr == 2026, p),
    "sold_2025_jan_aug": score((yr == 2025) & (mo <= 8), p),
    "new_build": score(nb, p), "not_new_build": score(~nb, p),
    "sold_2025_not_new_build": score((yr == 2025) & ~nb, p),
}
share_nb = {str(y): round(float(nb[yr == y].mean()), 4) for y in (2025, 2026)}
months = te.groupby(te.sale_date.dt.to_period("M")).size(); monthly = {str(k): int(v) for k, v in months.items()}
seeds = {str(k): round(E.met(te, v)["mdape"], 5) for k, v in preds.items()} | {"average_of_3": round(E.met(te, avg)["mdape"], 5)}
res = dict(cohorts=cohorts, new_build_share=share_nb, sales_per_month=monthly, seeds=seeds,
           seed_within10={str(k): round(E.met(te, v)["within10"], 4) for k, v in preds.items()} | {"average_of_3": round(E.met(te, avg)["within10"], 4)})
json.dump(res, open(OUT / "eval_cohorts_seeds.json", "w"), indent=1); print(json.dumps(res, indent=1))

# accuracy breakdown on the dashboard: replace this script's rows, keep the rest
f = D / "accuracy_breakdown.csv"; rows = list(csv.reader(open(f)))
head, body = rows[0], [r for r in rows[1:] if r[0] not in ("year", "new_build")]
ape = np.abs(np.exp(p) - te.price.values) / te.price.values
add = []
for dim, name, mask in (("year", "Sold in 2025", yr == 2025), ("year", "Sold Jan-Aug 2026 (registered so far)", yr == 2026),
                        ("new_build", "New build", nb), ("new_build", "Not new build", ~nb)):
    add.append([dim, name, int(mask.sum()), round(float(np.median(ape[mask])), 5), round(float((ape[mask] <= .1).mean()), 4)])
with open(f, "w", newline="") as fh: w = csv.writer(fh); w.writerow(head); w.writerows(body + add)
