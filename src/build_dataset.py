"""Run the SQL pipeline in DuckDB and print row-count checks after every step."""
import duckdb, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "data/processed/doncaster.duckdb"))
import os; os.chdir(ROOT)
for f in sorted((ROOT / "sql").glob("0*.sql")):
    con.execute(f.read_text())
    print("ran", f.name)
q = lambda s: con.execute(s).fetchall()
print("raw rows:", q("select count(*) from sales_raw"))
print("clean rows:", q("select count(*) from sales"))
print("after location join (must equal clean):", q("select count(*) from sales_loc"))
print("missing coords:", q("select count(*) from sales_loc where lat is null"))
print("missing IMD:", q("select count(*) from sales_loc where imd_score is null"))
print("repeat-sale rows:", q("select count(*) from sales_seq where prev_price is not null"))
print("by year 2015+:", q("select year(sale_date), count(*) from sales_seq where sale_date>='2015-01-01' group by 1 order by 1"))
