"""Monthly Doncaster house-price index (hedonic time-dummy method).

log(price) = month effect + LSOA effect + type/tenure/new-build effects + error
The month effects, exponentiated, give a quality-adjusted index (2015-01 = 1).
`fit_index(df)` only uses the rows it is given, so we can build an index that is
'known at valuation time' by passing sales up to a cut-off date."""
import numpy as np, pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsqr

def fit_index(df: pd.DataFrame) -> pd.Series:
    d = df.dropna(subset=["lsoa21"]).copy()
    d["month"] = d["sale_date"].values.astype("datetime64[M]")
    months = np.sort(d["month"].unique())
    blocks, names = [], []
    for col in ["month", "lsoa21", "property_type", "tenure"]:
        cats = pd.Categorical(d[col])
        m = sparse.csr_matrix((np.ones(len(d)), (np.arange(len(d)), cats.codes)), shape=(len(d), len(cats.categories)))
        blocks.append(m[:, 1:] if col != "month" else m)        # drop one level except month (no global intercept)
        names += [(col, c) for c in (cats.categories if col == "month" else cats.categories[1:])]
    blocks.append(sparse.csr_matrix(d["new_build"].astype(float).values.reshape(-1, 1)))
    X = sparse.hstack(blocks).tocsr()
    beta = lsqr(X, np.log(d["price"].values), atol=1e-10, btol=1e-10, iter_lim=5000)[0]
    month_eff = beta[: len(months)]
    idx = pd.Series(np.exp(month_eff - month_eff[0]), index=pd.to_datetime(months), name="index")
    # light smoothing: 3-month trailing mean (uses only past months)
    return idx.rolling(3, min_periods=1).mean()
