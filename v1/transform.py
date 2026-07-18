import pandas as pd
from datetime import datetime
from typing import Tuple

from extract import extract_measures, extract_readings

from logger_setup import get_logger
logger = get_logger(__name__)

"""
Transform module - Enrich and structure data for star schema.
"""


def clean(value, default=""):
    """Strip strings safely; return default for None/non-strings.

    API fields are not guaranteed present, so raw .strip() calls can raise
    AttributeError on None. Centralising the guard keeps the enrichment
    block readable and crash-proof.
    """
    return value.strip() if isinstance(value, str) else default


def parse_timestamp(raw, context: str):
    """Parse an ISO timestamp defensively.

    The EA API returns timestamps with a trailing 'Z' (Zulu/UTC), which
    datetime.fromisoformat rejects on Python versions before 3.11. Replacing
    'Z' with '+00:00' keeps parsing correct and version-safe. Malformed or
    missing values are logged and become None rather than crashing the run.
    """
    if raw and isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            logger.warning(f"TRANSFORM: Incorrect timestamp format: {raw}. Setting to None.")
            return None
    logger.warning(f"TRANSFORM: Timestamp missing for {context}. Setting to None.")
    return None


def transform() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        """Execute pipeline and return all readings."""
        # Discover all matching measures
        measures = extract_measures()

        if not measures:
            raise ValueError("TRANSFORM: No measures discovered; station_info cannot be empty")

        logger.info(f"TRANSFORM: Total measures found: {len(measures)}")

        # Fetch readings for ALL discovered measures
        all_readings = []
        for measure in measures:

            logger.info(f"TRANSFORM: Fetching readings for: {measure.get('parameter')} ({measure.get('unit')})")

            # Measure Url
            url = measure.get("measure_url")

            # checking if there is a full url for the measure
            if not url:
                logger.warning(f"TRANSFORM: Skipping measure {measure.get('parameter')} - missing URL")
                continue  # Skip this one and move to the next

            # Fetch the data
            readings = extract_readings(url)

            # checking if there are readings in the measure
            if not readings:
                logger.info(f"TRANSFORM: No reading for {measure.get('parameter')}")
                continue

            # Station opening date parses once per measure, not once per reading
            date_open = parse_timestamp(measure.get("date_open"), measure.get("label", "unknown station"))

            for reading in readings:
                transformed_timestamp = parse_timestamp(reading.get("timestamp"), measure.get("parameter", "unknown parameter"))

                enriched_reading = {

                    # Station_info metadata
                    "station_name": clean(measure.get("label")),
                    "river_name": clean(measure.get("river_name")),
                    "date_opened": date_open,
                    "status": clean(measure.get("status")).lower(),
                    "station_url": clean(measure.get("station_url")),

                    # Measure metadata
                    "parameter": clean(measure.get("parameter")),
                    "unit": clean(measure.get("unit")),
                    "measure_notation": measure.get("measure_notation"),
                    "measure_url": clean(url),

                    # Reading data
                    "measured_timestamp": transformed_timestamp,
                    "measured_value": reading.get("value"),
                    "measured_quality": clean(reading.get("quality"), "unknown").lower()

                }
                all_readings.append(enriched_reading)

            logger.info(f" -> Transformed {len(readings)} readings for {measure.get('parameter')} ({measure.get('unit')})")

        logger.info(f"TRANSFORM: Total readings Transformed: {len(all_readings)}")

        df = pd.DataFrame(all_readings)
        logger.info(f"TRANSFORM: Created DataFrame with shape: {df.shape}")

        # ================================================================
        # Dimension DataFrames
        # ================================================================
        logger.info("TRANSFORM: Dimension DataFrame dim_station")

        dim_station = df[["station_name", "river_name", "date_opened", "status", "station_url"]].copy().drop_duplicates().reset_index(drop=True)
        dim_station['station_id'] = dim_station.index + 1
        # Reorder columns
        dim_station = dim_station[['station_id', "station_name", "river_name", "date_opened", "status", "station_url"]]
        logger.info("TRANSFORM: dim_station transformed")

        logger.info("TRANSFORM: Dimension DataFrame dim_measure")
        dim_measure = df[["parameter", "unit", "measure_notation", "measure_url"]].copy().drop_duplicates().reset_index(drop=True)
        dim_measure['parameter_id'] = dim_measure.index + 1
        # Reorder columns
        dim_measure = dim_measure[['parameter_id', "parameter", "unit", "measure_notation", "measure_url"]]
        logger.info("TRANSFORM: dim_measure transformed")

        # ================================================================
        # Fact DataFrame
        # ================================================================
        all_df = df.copy()

        logger.info("TRANSFORM: Fact DataFrame")

        # Merge with dimensions to get surrogate keys
        all_df = all_df.merge(
            dim_station,
            on=["station_name", "river_name", "date_opened", "status", "station_url"],
            how="left")

        all_df = all_df.merge(
            dim_measure,
            on=["parameter", "unit", "measure_notation", "measure_url"],
            how="left")

        # Keep only fact columns
        fact_df = all_df[['station_id', 'parameter_id', "measured_timestamp", "measured_value", "measured_quality"]].copy()
        fact_df['fact_id'] = fact_df.index + 1

        # Replace text with integer codes; unmapped values become -1 ("unknown")
        # rather than NaN, so the quality column stays a clean integer and
        # unexpected API values are visible instead of silently null.
        quality_mapping = {'unchecked': 0, 'checked': 1}
        fact_df['measured_quality'] = fact_df['measured_quality'].map(quality_mapping).fillna(-1).astype(int)

        # Reorder columns
        fact_df = fact_df[["fact_id", 'station_id', 'parameter_id', "measured_timestamp", "measured_value", "measured_quality"]]
        logger.info("TRANSFORM: Fact_df transformed")

        return dim_station, dim_measure, fact_df

    except ValueError as e:
        logger.error(f"TRANSFORM: failed: {e}")
        raise
