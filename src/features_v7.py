"""Candidate features for version 7. Both use only information available before the sale.

  epc_hist : the home's energy-certificate history as a stand-in for condition and who owned it. From certificates
             lodged before the sale: why the latest one was done (marketed sale, non-marketed sale, rental, new
             dwelling, other), its tenure (owner-occupied, private or social rented), whether any certificate in the
             5 years before was for a rental, how old the latest one is, how many there are, and the energy score
             change since the previous certificate (a jump suggests a refurbishment).
  premium  : how far the home's previous sale was from the model. A sale 6% above the model last time suggests the
             home has something the data can't see. Each sale gets a residual from a model WITHOUT last-sale features,
             trained on 2015-2023 with folds grouped by home, so no residual comes from a model that saw any sale of
             that home. Sales after 2023 use the model trained on all of 2015-2023. Each sale then takes its
             previous sale's residual (previous sales from 2015 on; earlier ones have no residual).
Output: data/processed/model_frame_v7.parquet"""
import json, pathlib, sys, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.model_selection import GroupKFold
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from epc_match import load_epc
ROOT = pathlib.Path(__file__).resolve().parents[1]; P_ = ROOT / "data/processed"; OUT = ROOT / "outputs"
s = pd.read_parquet(P_ / "model_frame_v5.parquet").sort_values(["sale_date", "unique_id"]).reset_index(drop=True); n0 = len(s)
keep = set(pd.read_csv(OUT / "train_keep_ids.csv").iloc[:, 0])

# ---------- energy-certificate history ----------
REASON = {"marketed sale": 0, "non-marketed sale": 1, "rental": 2, "new dwelling": 3}
def reason_code(t):
    t = str(t).strip().lower()
    if t in REASON: return REASON[t]
    if t.startswith("rental"): return 2
    return 4 if t not in ("", "nan", "none") else np.nan
def tenure_code(t):
    t = str(t).strip().lower()
    return 0.0 if t.startswith("owner") else 1.0 if "private" in t else 2.0 if "social" in t else np.nan
EPC_H = ["epc_reason", "epc_tenure_n", "epc_rental_5y", "epc_age_y", "epc_n", "sap_jump"]
def epc_history(e, targets):
    """targets: DataFrame with dwelling and t (the date the features are 'as of'); certificates strictly before t."""
    e = e.dropna(subset=["dwelling", "lodgement_date"]).sort_values("lodgement_date").copy()
    e["reason"] = e.transaction_type.map(reason_code); e["ten"] = e.epc_tenure.map(tenure_code)
    e["rental"] = ((e.reason == 2) | (e.ten >= 1)).astype(float)
    e["n"] = e.groupby("dwelling").cumcount() + 1; e["prev_sap"] = e.groupby("dwelling").sap_current.shift()
    e["lt"] = e.lodgement_date + pd.Timedelta(days=1)          # merge_asof 'backward' includes equal times: shift to make it strictly before
    e["dwelling"] = e.dwelling.astype(str)
    e["rt"] = e["lt"].where(e.rental == 1); e["rt"] = e.groupby("dwelling").rt.ffill()   # latest rental certificate up to each certificate
    t = targets[["dwelling", "t"]].reset_index().sort_values("t", kind="stable")
    t["dwelling"] = t.dwelling.astype(str)
    m = pd.merge_asof(t, e[["dwelling", "lt", "lodgement_date", "reason", "ten", "n", "sap_current", "prev_sap", "rt"]].sort_values("lt", kind="stable"),
                      left_on="t", right_on="lt", by="dwelling", direction="backward")
    m = m.set_index("index").sort_index()
    out = pd.DataFrame(index=targets.index)
    out["epc_reason"] = m.reason; out["epc_tenure_n"] = m.ten
    out["epc_rental_5y"] = pd.Series(np.where(m.lodgement_date.isna(), np.nan, ((m.t - m.rt).dt.days <= 5 * 365.25).astype(float)), index=m.index)   # aligned by index, like the rest
    out["epc_age_y"] = (m.t - m.lodgement_date).dt.days / 365.25; out["epc_n"] = m.n
    out["sap_jump"] = m.sap_current - m.prev_sap
    return out

if __name__ == "__main__":
    e = load_epc()[["dwelling", "lodgement_date", "transaction_type", "epc_tenure", "sap_current"]]
    h = epc_history(e, s.loc[s.dwelling.notna(), ["dwelling"]].assign(t=s.sale_date)).reindex(s.index)
    for c in EPC_H: s[c] = h[c].values
    print("EPC history:", {c: f"{s[c].notna().mean():.0%}" for c in EPC_H}, "| latest certificate for a rental:", f"{(s.epc_reason == 2).mean():.1%}")

    # ---------- last-sale premium ----------
    BASE = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education", "imd_health", "imd_crime",
            "imd_barriers", "imd_living_env", "lvl_sector_type", "lvl_lsoa", "n_sector_type", "property_type", "tenure", "new_build"]
    EPC = ["floor_area", "rooms", "age_year", "bungalow", "built_form_code", "extensions", "sap_current", "sap_potential", "sap_gap", "mains_gas"]
    NOPREV = (BASE + EPC + ["knn_lvl", "knn_dist", "knn_ppsqm", "plot_m2", "plot_epc_homes", "plot_uprns", "plot_m2_per_home",
              "lvl_street_type", "n_street_type", "lvl_postcode", "n_postcode", "wall_type", "ceiling_m", "floor_level_n", "top_floor",
              "heated_rooms", "glazed_area_n", "fireplaces", "wall_insulated", "loft_mm", "glazing", "elec_heating", "heat_pump", "woodburner",
              "low_energy_light", "solar_pv"])
    def X(d):
        x = d[NOPREV].copy(); x["property_type"] = d.property_type.map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
        x["tenure"] = (d.tenure == "L").astype(int); x["new_build"] = d.new_build.astype(int); return x.astype(float)
    P = dict(objective="regression_l1", learning_rate=0.08, num_leaves=31, min_data_in_leaf=40, feature_fraction=0.8, lambda_l2=1.0,
             bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=7)
    NT = 900
    def residuals(s, train_end):
        """Residual of every sale from a no-last-sale model: grouped out-of-fold up to train_end, plain prediction after it."""
        r = np.full(len(s), np.nan); inside = (s.sale_date <= train_end).values; fit_ok = inside & s.unique_id.isin(keep).values
        idx_in = np.where(inside)[0]; Xin = X(s.iloc[idx_in]); g = s.address_key.values[idx_in]
        for a, b in GroupKFold(5).split(Xin, groups=g):
            tr = idx_in[a][fit_ok[idx_in[a]]]
            m = lgb.train(P, lgb.Dataset(X(s.iloc[tr]), s.y_defl.values[tr], categorical_feature=["property_type"]), NT)
            r[idx_in[b]] = s.y_defl.values[idx_in[b]] - m.predict(Xin.iloc[b])
        tr = np.where(fit_ok)[0]
        m = lgb.train(P, lgb.Dataset(X(s.iloc[tr]), s.y_defl.values[tr], categorical_feature=["property_type"]), NT)
        out = np.where(~inside)[0]; r[out] = s.y_defl.values[out] - m.predict(X(s.iloc[out]))
        return r, m
    s["resid_np"], m_np = residuals(s, pd.Timestamp("2023-12-31"))
    key = s.drop_duplicates(["address_key", "sale_date"]).set_index(["address_key", "sale_date"]).resid_np
    s["prev_resid"] = [key.get((a, d), np.nan) if pd.notna(d) else np.nan for a, d in zip(s.address_key, s.prev_date)]
    have = s.prev_resid.notna()
    print(f"previous sale with a residual: {have.mean():.1%} of sales ({(have & s.prev_defl.notna()).sum() / s.prev_defl.notna().sum():.0%} of those with a last sale)")
    c = s[have & s.resid_np.notna()]
    print("correlation of a home's residual with its previous sale's residual:", round(float(np.corrcoef(c.resid_np, c.prev_resid)[0, 1]), 3),
          "| by years since:", {f"{a}-{b}": round(float(np.corrcoef(g.resid_np, g.prev_resid)[0, 1]), 3) for a, b in [(0, 2), (2, 5), (5, 12)]
                                 for g in [c[(c.years_since_prev >= a) & (c.years_since_prev < b)]]})
    assert len(s) == n0
    s.to_parquet(P_ / "model_frame_v7.parquet")
    m_np.save_model(str(P_ / "noprev_model_to2023.txt"))
    print("saved", P_ / "model_frame_v7.parquet")
