-- 02_location.sql : attach coordinates, neighbourhood (LSOA 2021) and IMD 2025 scores
CREATE OR REPLACE TABLE postcodes AS
SELECT postcode, CAST(latitude AS DOUBLE) AS lat, CAST(longitude AS DOUBLE) AS lon,
       lsoa21, msoa21, lsoa_name, ward, terminated
FROM read_csv('data/raw/postcodes.csv', header = true, all_varchar = true)
-- a postcode can appear twice (live + terminated record): keep one row, preferring the live one
QUALIFY row_number() OVER (PARTITION BY postcode ORDER BY terminated, lsoa21 NULLS LAST) = 1;

CREATE OR REPLACE TABLE imd AS
SELECT "LSOA code (2021)"                                   AS lsoa21,
       CAST("Index of Multiple Deprivation (IMD) Score" AS DOUBLE)                 AS imd_score,
       CAST("Index of Multiple Deprivation (IMD) Decile (where 1 is most deprived 10% of LSOAs)" AS INTEGER) AS imd_decile,
       CAST("Income Score (rate)" AS DOUBLE)                AS imd_income,
       CAST("Employment Score (rate)" AS DOUBLE)            AS imd_employment,
       CAST("Education, Skills and Training Score" AS DOUBLE) AS imd_education,
       CAST("Health Deprivation and Disability Score" AS DOUBLE) AS imd_health,
       CAST("Crime Score" AS DOUBLE)                        AS imd_crime,
       CAST("Barriers to Housing and Services Score" AS DOUBLE) AS imd_barriers,
       CAST("Living Environment Score" AS DOUBLE)           AS imd_living_env
FROM read_csv('data/raw/imd2025_file7.csv', header = true, all_varchar = true);

-- Town-centre reference point = centroid of DN1 postcodes in the data (data-driven, not hand-entered)
CREATE OR REPLACE TABLE centre AS
SELECT avg(lat) AS c_lat, avg(lon) AS c_lon FROM postcodes WHERE postcode LIKE 'DN1 %' AND lat IS NOT NULL;

CREATE OR REPLACE TABLE sales_loc AS
SELECT s.*, p.lat, p.lon, p.lsoa21, p.msoa21, p.ward,
       i.imd_score, i.imd_decile, i.imd_income, i.imd_employment, i.imd_education,
       i.imd_health, i.imd_crime, i.imd_barriers, i.imd_living_env,
       -- great-circle distance to centre, km
       2 * 6371 * asin(sqrt( pow(sin(radians(p.lat - c.c_lat)/2),2) +
           cos(radians(c.c_lat)) * cos(radians(p.lat)) * pow(sin(radians(p.lon - c.c_lon)/2),2) )) AS dist_centre_km
FROM sales s
LEFT JOIN postcodes p USING (postcode)
LEFT JOIN imd i USING (lsoa21)
CROSS JOIN centre c;
