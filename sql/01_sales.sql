-- 01_sales.sql : clean Land Registry Price Paid Data for Doncaster (1995-2026)
-- Keep standard residential sales (category A), drop 'Other' property type,
-- normalise postcodes and build an address key for repeat-sales matching.
CREATE OR REPLACE TABLE sales_raw AS
SELECT * FROM read_csv(['data/raw/ppd_doncaster.csv', 'data/raw/ppd_doncaster_1995_2014.csv'],
                       header = true, union_by_name = true, all_varchar = true);

CREATE OR REPLACE TABLE sales AS
SELECT
    unique_id,
    CAST(price_paid AS INTEGER)                                   AS price,
    CAST(deed_date AS DATE)                                       AS sale_date,
    upper(trim(postcode))                                         AS postcode,
    split_part(upper(trim(postcode)), ' ', 1)                     AS district,      -- e.g. DN4
    upper(trim(postcode))[1:length(upper(trim(postcode))) - 2]    AS sector,        -- e.g. DN4 7
    property_type,                                                                  -- D/S/T/F
    new_build = 'Y'                                               AS new_build,
    estate_type                                                   AS tenure,        -- F freehold, L leasehold
    upper(trim(coalesce(saon, ''))) AS saon,
    upper(trim(coalesce(paon, ''))) AS paon,
    upper(trim(coalesce(street, ''))) AS street,
    upper(trim(coalesce(town, '')))   AS town,
    -- one key per dwelling: flat/house number + street + postcode
    upper(trim(coalesce(saon,''))) || '|' || upper(trim(coalesce(paon,''))) || '|' ||
    upper(trim(coalesce(street,''))) || '|' || upper(trim(postcode)) AS address_key
FROM sales_raw
WHERE transaction_category = 'A'
  AND property_type IN ('D','S','T','F')
  AND postcode IS NOT NULL AND trim(postcode) <> ''
  AND CAST(price_paid AS INTEGER) BETWEEN 10000 AND 2000000;
