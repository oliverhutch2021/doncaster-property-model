"""Local corrections: shift each estimate by the model's recent misses nearby.

knn     the v4/v5 version: median residual of the k nearest sales from the last 12 months (at least 60 days old)
smooth  a weighted version: every recent sale within reach counts, weighted by distance (Gaussian, scale h km),
        age (halves every `half_life` months) and whether it is the same property type (weight `tw` if not);
        a weighted median, shrunk towards zero when there is little nearby evidence (n_eff / (n_eff + lam))"""
import numpy as np, pandas as pd
from sklearn.neighbors import BallTree
R = 6371.0

def _months(target):
    return [pd.Timestamp(m) for m in sorted(pd.unique(target.month))]

def knn(pool, target, k, lag_days=60, pool_months=12):
    out = np.zeros(len(target)); tr_ = np.radians(target[["lat", "lon"]].values)
    pdates, prad, pr = pool.sale_date.values, np.radians(pool[["lat", "lon"]].values), pool.r.values
    for m in _months(target):
        q = (target.month == m).values
        sel = (pdates < np.datetime64(m - pd.Timedelta(days=lag_days))) & (pdates >= np.datetime64(m - pd.DateOffset(months=pool_months)))
        if sel.sum() < k: continue
        _, ind = BallTree(prad[sel], metric="haversine").query(tr_[q], k=k); out[q] = np.median(pr[sel][ind], axis=1)
    return out

def smooth_parts(pool, target, settings, lag_days=60, pool_months=12, kmax=150):
    """For each (h, half_life, tw) in settings: weighted median and effective sample size per target row."""
    out = {st: (np.zeros(len(target)), np.zeros(len(target))) for st in settings}
    tr_ = np.radians(target[["lat", "lon"]].values); ttype = target.property_type.to_numpy(dtype=object)
    pdates, prad, pr, ptype = pool.sale_date.values, np.radians(pool[["lat", "lon"]].values), pool.r.values, pool.property_type.to_numpy(dtype=object)
    for m in _months(target):
        q = np.where((target.month == m).values)[0]
        sel = np.where((pdates < np.datetime64(m - pd.Timedelta(days=lag_days))) & (pdates >= np.datetime64(m - pd.DateOffset(months=pool_months))))[0]
        if len(sel) < 20: continue
        dist, ind = BallTree(prad[sel], metric="haversine").query(tr_[q], k=min(kmax, len(sel)))
        dkm = dist * R; j = sel[ind]
        age_m = (np.datetime64(m) - pdates[j]).astype("timedelta64[D]").astype(float) / 30.44
        same = ptype[j] == ttype[q][:, None]; vals = pr[j]
        order = np.argsort(vals, axis=1); sv = np.take_along_axis(vals, order, axis=1)
        for (h, hl, tw) in settings:
            w = np.exp(-(dkm / h) ** 2) * 0.5 ** (age_m / hl) * np.where(same, 1.0, tw)
            sw = np.take_along_axis(w, order, axis=1); cw = np.cumsum(sw, axis=1); tot = cw[:, -1:]
            pos = np.argmax(cw >= 0.5 * tot, axis=1)
            med = sv[np.arange(len(q)), pos]
            neff = np.where(tot[:, 0] > 0, tot[:, 0] ** 2 / np.maximum((w ** 2).sum(axis=1), 1e-12), 0.0)
            out[(h, hl, tw)][0][q] = np.where(tot[:, 0] > 1e-9, med, 0.0); out[(h, hl, tw)][1][q] = neff
    return out

def smooth(pool, target, h, half_life, tw, lam, **kw):
    med, neff = smooth_parts(pool, target, [(h, half_life, tw)], **kw)[(h, half_life, tw)]
    return med * neff / (neff + lam)
