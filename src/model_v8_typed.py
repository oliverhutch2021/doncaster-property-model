"""Confidence for homes typed in by hand.

The confidence model learned from sales, where missing certificate details usually mean an unusual home (no certificate
match), which is hard to value. A home typed in by hand is usually ordinary, with the details simply not entered, so the
model overstates its error (on 2025-26: predicted 20% typical error, actual 11%). This rescales the confidence for
typed-in homes, calibrated on 2024 exactly like the main ranges:

  2024   the backtest model for 2024 (trained to 2022, early-stopped on 2023) values 2024 homes with their certificate
         details blanked except floor area; scale = actual median error / predicted, and the 80% range's 10th and 90th
         percentiles of error / scaled prediction
  test   the dashboard model on 2025-26 homes blanked the same way (and with nothing but type), checked with that scaling
Output: outputs/confidence_typed.json (merged into confidence.json and model_meta by src/export_v8.py)"""
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.neighbors import BallTree
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / "outputs"
sys.path.insert(0, str(ROOT / "src"))
import model_v8_backtest as B, correction as C
from model_v8_confidence import CX
CERT = ["rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas", "plot_m2", "plot_epc_homes",
        "plot_uprns", "plot_m2_per_home", "wall_type", "ceiling_m", "floor_level_n", "top_floor", "heated_rooms", "glazed_area_n", "fireplaces", "wall_insulated",
        "loft_mm", "glazing", "elec_heating", "heat_pump", "woodburner", "low_energy_light", "solar_pv", "epc_reason", "epc_tenure_n", "epc_rental_5y", "epc_age_y",
        "epc_n", "sap_jump", "prev_defl", "years_since_prev", "prev_nb"]

def spread_and_corr(pool, te, K=40, ALPHA=0.5):
    corr = ALPHA * C.knn(pool, te, K); sp = np.zeros(len(te))
    tr_ = np.radians(te[["lat", "lon"]].values); pdates, prad, pr = pool.sale_date.values, np.radians(pool[["lat", "lon"]].values), pool.r.values
    for mo in sorted(te.month.unique()):
        q = (te.month == mo).values; mo = pd.Timestamp(mo)
        sel = (pdates < np.datetime64(mo - pd.Timedelta(days=60))) & (pdates >= np.datetime64(mo - pd.DateOffset(months=12)))
        _, ind = BallTree(prad[sel], metric="haversine").query(tr_[q], k=K); v = pr[sel][ind]
        sp[q] = np.median(np.abs(v - np.median(v, axis=1, keepdims=True)), axis=1)
    return corr, sp

def masked(model, d, blank, offset, corr, sp, n_iter, Xf):
    m = d.copy()
    for c in blank: m[c] = np.nan
    p = model.predict(Xf(m), num_iteration=n_iter) + offset + corr
    m["pred_log"] = p; m["corr"] = corr; m["local_spread"] = sp
    return m, p

if __name__ == "__main__":
    conf = lgb.Booster(model_file=str(OUT / "model/confidence_v8.txt"))
    # ---------- 2024: the backtest model for that year ----------
    Y = 2024; s = B.s; idx = B.index_for(Y); li = np.log(s.month.map(idx).values.astype(float))
    d = s.copy(); d["log_idx"] = li; d["y_defl"] = d.y - li
    d["prev_defl"] = np.log(d.prev_price) - np.log(pd.Series(d.prev_date.values.astype("datetime64[M]")).map(idx).values.astype(float))
    cleaned = d.unique_id.isin(B.keep) | (d.sale_date.dt.year >= 2025)
    tr = d[(d.sale_date <= f"{Y - 2}-12-31") & cleaned]; va = d[(d.sale_date.dt.year == Y - 1) & cleaned]
    dt = lgb.Dataset(B.X(tr), tr.y_defl, categorical_feature=["property_type"])
    m = lgb.train(B.P, dt, 8000, valid_sets=[lgb.Dataset(B.X(va), va.y_defl, reference=dt)], callbacks=[lgb.early_stopping(150, verbose=False)])
    pool = d[(d.sale_date.dt.year >= Y - 1) & (d.sale_date.dt.year <= Y)].copy(); pool["r"] = pool.y_defl.values - m.predict(B.X(pool), num_iteration=m.best_iteration)
    te = d[(d.sale_date.dt.year == Y) & d.floor_area.notna()].copy()
    corr, sp = spread_and_corr(pool, te)
    mt, p = masked(m, te, CERT, te.log_idx.values, corr, sp, m.best_iteration, B.X)
    sig = conf.predict(CX(mt)); r = np.log(te.price.values) - p
    scale = float(np.median(np.abs(r)) / np.median(sig)); z = r / (sig * scale)
    q10, q90 = float(np.quantile(z, .10)), float(np.quantile(z, .90))
    print(f"2024, typed in (area only): actual median abs error {np.median(np.abs(r)):.3f}, predicted {np.median(sig):.3f} -> scale {scale:.3f}; range [{q10:.2f}, {q90:.2f}]")
    # ---------- check on 2025-26 with the dashboard model ----------
    import export_v7 as E
    mB = E.fit_es(E.between("2000-01-01", "2023-12-31", True), E.between("2023-12-31", "2024-12-31", True), B.P); n = mB.best_iteration
    s7 = E.s; t2 = s7[(s7.sale_date > "2024-12-31") & s7.floor_area.notna()].copy(); pool2 = s7[s7.sale_date > "2023-12-31"].copy()
    pool2["r"] = pool2.y_defl.values - mB.predict(E.X(pool2), num_iteration=n)
    corr2, sp2 = spread_and_corr(pool2, t2); res = dict(scale=scale, q10=q10, q90=q90, test={})
    for name, blank in [("area only", CERT), ("nothing but type", CERT + ["floor_area"])]:
        mt2, p2 = masked(mB, t2, blank, t2.log_idx.values, corr2, sp2, n, E.X)
        sg = conf.predict(CX(mt2)) * scale; r2 = np.log(t2.price.values) - p2; ape = np.abs(np.exp(p2) - t2.price.values) / t2.price.values
        cov = float(np.mean((r2 >= sg * q10) & (r2 <= sg * q90)))
        res["test"][name] = dict(mdape=float(np.median(ape)), typical_error_predicted=float(np.median(np.exp(sg) - 1)), coverage=cov,
                                 width_median=float(np.median(np.exp(sg * q90) - np.exp(sg * q10))))
        print(f"2025-26, typed in ({name}): median error {np.median(ape):.3f} | predicted typical error {np.median(np.exp(sg) - 1):.3f} | 80% range holds {cov:.1%}")
    json.dump(res, open(OUT / "confidence_typed.json", "w"), indent=1)
