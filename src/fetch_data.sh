#!/usr/bin/env bash
# Download the open datasets used by the model into data/raw/.
# All sources are published under the Open Government Licence (or ODbL for postcodes.io-derived ONS data).
set -euo pipefail
cd "$(dirname "$0")/../data/raw"
# HM Land Registry Price Paid Data, Doncaster district
curl -sS -o ppd_doncaster.csv "https://landregistry.data.gov.uk/app/ppd/ppd_data.csv?district=DONCASTER&min_date=2015-01-01&limit=all&header=true"
curl -sS -o ppd_doncaster_1995_2014.csv "https://landregistry.data.gov.uk/app/ppd/ppd_data.csv?district=DONCASTER&min_date=1995-01-01&max_date=2014-12-31&limit=all&header=true"
# English Indices of Deprivation 2025, File 7
curl -sS -o imd2025_file7.csv "https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv"
# ONS Price Index of Private Rents (16 Sep 2026 edition)
curl -sS -o pipr.xlsx "https://www.ons.gov.uk/file?uri=/economy/inflationandpriceindices/datasets/priceindexofprivaterentsukmonthlypricestatistics/16september2026/priceindexofprivaterentsukmonthlypricestatistics.xlsx"
python3 - <<'PY'
import openpyxl, csv
ws = openpyxl.load_workbook('pipr.xlsx', read_only=True)['Table 1']; it = ws.iter_rows(values_only=True)
next(it); next(it); hdr = next(it)
with open('pipr_doncaster.csv', 'w', newline='') as f:
    w = csv.writer(f); w.writerow(hdr); w.writerows(r for r in it if r[1] == 'E08000017')
PY
# Energy Performance Certificates (manual step: needs a free GOV.UK One Login)
#   1. Go to https://get-energy-performance-data.communities.gov.uk and sign in.
#   2. Domestic certificates -> local authority "Doncaster" -> all dates -> download.
#   3. Save the certificates CSV as data/raw/epc_doncaster.csv; after src/build_dataset.py, run src/epc_match.py
# Environment Agency: Risk of Flooding from Rivers and Sea (NaFRA2) - Postcodes in Areas at Risk
mkdir -p flood && curl -sSL -o flood/RoFRS_Postcodes_in_Areas_at_Risk.zip "https://environment.data.gov.uk/api/file/download?fileDataSetId=97781741-2982-4802-af2e-313fe3fd8f7e&fileName=RoFRS_Postcodes_in_Areas_at_Risk.zip"
unzip -oq flood/RoFRS_Postcodes_in_Areas_at_Risk.zip -d flood/rofrs
# DfT NaPTAN: all stops and stations, England
mkdir -p naptan && curl -sS -o naptan/naptan_all.csv "https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv"
# DfE Get Information about Schools (all establishments incl. closed) and Ofsted outcomes at 31 March 2026
mkdir -p schools && curl -sS -o schools/edubasealldata.csv "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata$(date +%Y%m%d).csv"
curl -sS -o schools/ofsted_mar2026.csv "https://assets.publishing.service.gov.uk/media/6a3502ec0bea238415c9a2ab/State-funded_schools_inspections_and_outcomes_as_at_31_March_2026.csv"
# ONS boundaries: Doncaster LSOA 2021 (super generalised, with rural-urban class) and wards May 2026
mkdir -p boundaries; B=https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services
curl -sS -G "$B/LSOA_2021_EW_BSC_V4_RUC/FeatureServer/0/query" --data-urlencode "where=LSOA21NM LIKE 'Doncaster %'" --data-urlencode "outFields=*" --data-urlencode "outSR=4326" --data-urlencode "f=geojson" -o boundaries/lsoa21_doncaster_bsc.geojson
curl -sS -G "$B/WD_MAY_2026_UK_BGC/FeatureServer/0/query" --data-urlencode "where=LAD26NM = 'Doncaster'" --data-urlencode "outFields=WD26CD,WD26NM,LAD26NM" --data-urlencode "outSR=4326" --data-urlencode "f=geojson" -o boundaries/wards2026_doncaster_bgc.geojson
# OpenStreetMap: Geofabrik South Yorkshire extract (ODbL)
mkdir -p osm && curl -sS -o osm/south-yorkshire-261008.osm.pbf "https://download.geofabrik.de/europe/united-kingdom/england/south-yorkshire-latest.osm.pbf"
# OS Open UPRN (address points) - filter to the Doncaster area
mkdir -p uprn && curl -sSL -o uprn/osopenuprn_csv.zip "https://api.os.uk/downloads/v1/products/OpenUPRN/downloads?area=GB&format=CSV&redirect"
unzip -p uprn/osopenuprn_csv.zip "$(unzip -Z1 uprn/osopenuprn_csv.zip | grep -i '\.csv$' | head -1)" | awk -F, 'NR==1 || ($2>=430000 && $2<=490000 && $3>=380000 && $3<=440000)' > uprn/uprn_doncaster_bbox.csv
# HM Land Registry INSPIRE Index Polygons for Doncaster (the download page sets a session cookie first)
mkdir -p inspire && curl -sSL -c /tmp/lr.cj -b /tmp/lr.cj -o /dev/null "https://use-land-property-data.service.gov.uk/datasets/inspire/download"
curl -sSL -c /tmp/lr.cj -b /tmp/lr.cj -o inspire/Doncaster.zip "https://use-land-property-data.service.gov.uk/datasets/inspire/download/Doncaster_Metropolitan_Borough_Council.zip" && unzip -oq inspire/Doncaster.zip -d inspire
# VOA Council Tax stock of properties 2025 (band x type x bedrooms, and band x build period, by LSOA)
mkdir -p voa && for f in 6a0ad444c75cc34a8ff8f397/CTSOP1.1.zip 6a0ad462229555d0fe8266f4/CTSOP3.1.zip 6a0ad479f7c2e79c33db907d/CTSOP4.1.zip; do curl -sSL -o voa/$(basename $f) "https://assets.publishing.service.gov.uk/media/$f" && unzip -oq voa/$(basename $f) -d voa/$(basename $f .zip); done
# OS OpenMap Local building outlines (SE and SK grid squares)
mkdir -p osmap && for t in SE SK; do curl -sSL -o osmap/oml_$t.zip "https://api.os.uk/downloads/v1/products/OpenMapLocal/downloads?area=$t&format=ESRI%C2%AE+Shapefile&redirect" && unzip -oqj osmap/oml_$t.zip "*/data/${t}_Building.*" -d osmap; done
# UK House Price Index full file (HM Land Registry / ONS), for src/compare_methods.py
mkdir -p ukhpi && curl -sSL -o ukhpi/UK-HPI-full-file-2026-07.csv "https://publicdata.landregistry.gov.uk/market-trend-data/house-price-index-data/UK-HPI-full-file-2026-07.csv"
# Postcode coordinates and LSOA codes from postcodes.io
cd ../.. && python3 src/fetch_postcodes.py
