# Databricks notebooks (build these Sunday)

## nb_bronze_to_silver
1. Read new bronze parquet for the run date
2. from src.transforms import * (sync this repo via Databricks Repos)
2b. Derive station_id from measure_id with F.regexp_extract("measure_id", r"measures/(.+?)-(?:level|flow)", 1)  # GUIDs contain hyphens - do not cut at first hyphen
3. enforce_schema -> validate (log quarantine counts) -> deduplicate -> interpolate_short_gaps
4. MERGE INTO silver.readings ON station_id AND date_time
5. Run detect_flatlines on the merged window -> append to silver.quality_alerts

## nb_silver_to_gold
1. Read silver.readings for affected dates
2. Aggregate per station/day: min/max/mean value, reading count, completeness = count/96.0
3. MERGE into gold.daily_station_summary
