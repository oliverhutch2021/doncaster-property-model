-- 03_repeat_sales.sql : previous sale of the same dwelling (used for condition calibration, NOT as a model feature)
CREATE OR REPLACE TABLE sales_seq AS
SELECT *,
       lag(price)     OVER w AS prev_price,
       lag(sale_date) OVER w AS prev_date,
       lag(new_build) OVER w AS prev_new_build,
       row_number()   OVER w AS sale_seq
FROM sales_loc
WINDOW w AS (PARTITION BY address_key ORDER BY sale_date, unique_id);
