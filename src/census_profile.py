"""Census 2021 profile of each Doncaster neighbourhood (LSOA), with Doncaster and England for comparison (dashboard v32).

Tables from Nomis bulk downloads (src/fetch_data.sh): TS054 tenure, TS067 highest qualification, TS068 students,
TS007A age, TS045 cars or vans. Shares are of households (tenure, cars) or of usual residents (the rest).
Average age uses the middle of each five-year band (87.5 for 85 and over). Cars per household counts "3 or more"
as 3, so it is a slight undercount where many households have three or more.

Output: outputs/dash2/census.csv (one row per Doncaster LSOA, plus 'Doncaster' and 'England')."""
import io, pathlib, zipfile
import numpy as np, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]; RAW = ROOT / "data/raw/census2021"; D = ROOT / "outputs/dash2"
LA, ENG = "E08000017", "E92000001"


def table(t, level):
    with zipfile.ZipFile(RAW / f"census2021-{t}.zip") as z:
        df = pd.read_csv(io.BytesIO(z.read(f"census2021-{t}-{level}.csv")))
    df = df.rename(columns={"geography code": "geo", "geography": "name"}).set_index("geo")
    df.columns = [c.split(": ", 1)[-1] if ": " in c else c for c in df.columns]
    return df


def profile(level):
    ten, qual, stu, age, car = (table(t, level) for t in ("ts054", "ts067", "ts068", "ts007a", "ts045"))
    out = pd.DataFrame(index=ten.index); out["name"] = ten["name"]
    hh = ten["Total: All households"]
    out["households"] = hh
    out["owned_pct"] = 100 * ten["Owned"] / hh
    out["social_rented_pct"] = 100 * ten["Social rented"] / hh
    out["private_rented_pct"] = 100 * ten["Private rented"] / hh
    out["degree_pct"] = 100 * qual["Level 4 qualifications and above"] / qual["Total: All usual residents aged 16 years and over"]
    out["no_qual_pct"] = 100 * qual["No qualifications"] / qual["Total: All usual residents aged 16 years and over"]
    out["students_pct"] = 100 * stu["Student"] / stu["Total: All usual residents aged 5 years and over"]
    bands = [c for c in age.columns if c.startswith("Aged ")]
    mids = [87.5 if "85" in c and "over" in c else (2.0 if "4 years and under" in c else (int(c.split()[1]) + int(c.split()[3])) / 2) for c in bands]
    out["mean_age"] = (age[bands] * mids).sum(axis=1) / age["Total"]
    out["age65_pct"] = 100 * age[[c for c in bands if any(f"Aged {a}" in c for a in (65, 70, 75, 80, 85))]].sum(axis=1) / age["Total"]
    tot = car["Total: All households"]
    out["cars_per_household"] = (car["1 car or van in household"] + 2 * car["2 cars or vans in household"] + 3 * car["3 or more cars or vans in household"]) / tot
    out["no_car_pct"] = 100 * car["No cars or vans in household"] / tot
    return out


lsoa = profile("lsoa")
don = sorted(g for g in lsoa.index if str(lsoa.at[g, "name"]).startswith("Doncaster "))
la, ctry = profile("ltla").loc[[LA]], profile("ctry").loc[[ENG]]
out = pd.concat([lsoa.loc[don], la.assign(name="Doncaster"), ctry.assign(name="England")])
out.index.name = "geo"
for c in out.columns:
    if c not in ("name", "households"): out[c] = out[c].round(2 if c == "cars_per_household" else 1)
out.to_csv(D / "census.csv")
print(f"wrote {D / 'census.csv'}: {len(don)} Doncaster LSOAs + Doncaster + England")
print(out.loc[[LA, ENG]].T.to_string())
