"""Feature engineering. Every 'local price level' feature only looks at sales that happened
BEFORE the sale being valued (closed='left' time windows) to avoid temporal leakage."""
import numpy as np, pandas as pd

NUM = ["lat", "lon", "dist_centre_km", "imd_score", "imd_income", "imd_employment", "imd_education",
       "imd_health", "imd_crime", "imd_barriers", "imd_living_env",
       "lvl_sector_type", "lvl_lsoa", "n_sector_type"]
CAT = ["property_type", "tenure", "new_build"]

def add_prior_levels(df: pd.DataFrame, y_col: str = "y_defl") -> pd.DataFrame:
    """Median index-adjusted log price of earlier sales in the same postcode sector & type (3 years),
    and in the same LSOA (3 years). NaN if fewer than 5 earlier sales."""
    df = df.sort_values("sale_date").copy()
    def roll(group_cols, name, min_n=5):
        out = pd.Series(np.nan, index=df.index); cnt = pd.Series(0.0, index=df.index)
        for _, g in df.groupby(group_cols, sort=False):
            s = g.set_index("sale_date")[y_col]
            r = s.rolling("1095D", closed="left")
            med, n = r.median().values, r.count().values
            out.loc[g.index] = np.where(n >= min_n, med, np.nan); cnt.loc[g.index] = n
        df[name] = out
        return cnt
    df["n_sector_type"] = roll(["sector", "property_type"], "lvl_sector_type")
    roll(["lsoa21"], "lvl_lsoa")
    return df

def matrix(df: pd.DataFrame) -> pd.DataFrame:
    X = df[NUM].copy()
    X["property_type"] = df["property_type"].map({"D": 0, "S": 1, "T": 2, "F": 3}).astype(int)
    X["tenure"] = (df["tenure"] == "L").astype(int)
    X["new_build"] = df["new_build"].astype(int)
    return X
