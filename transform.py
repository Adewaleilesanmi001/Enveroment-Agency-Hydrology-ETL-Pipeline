import pandas as pd
from datetime import datetime
from typing import Tuple

from extract import extract_measures, extract_readings

from logger_setup import get_logger
logger = get_logger(__name__)

"""
Transform module - Enrich and structure data for star schema.
"""

def transform() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        """Execute pipeline and return all readings."""
        # Discover all matching measures
        # logger.info("Discovering measures...")
        measures = extract_measures() # Storing the extract_measures returned dictionary

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

            # checking if there readings in the  measure
            if not readings:
                logger.info(f"TRANSFORM: No reading for {measure.get('parameter')}")
                continue

            for reading in readings:
                # Transform timestap to ISO timestamp
                raw_timestamp = reading.get("timestamp")
                if raw_timestamp and isinstance(raw_timestamp, str):
                    
                    try:
                        # Successfully convert
                        transformed_timestamp = datetime.fromisoformat(raw_timestamp)
                    except ValueError:
                        # If the format is wrong (e.g. "invalid-date"), log it and use None
                        logger.warning(f"TRANSFORM: Incorrect timestamp format: {raw_timestamp}. Setting to None.")
                        transformed_timestamp = None
                else:
                    # If timestamp is missing entirely, use None
                    logger.warning(f"TRANSFORM: Timestamp missing for {measure.get('parameter')}. Setting to None.")
                    transformed_timestamp = None     


                date_open = measure.get("date_open")
                if date_open and isinstance(date_open, str):
                    
                    try:
                        # Successfully convert
                        date_open = datetime.fromisoformat(date_open)
                    except ValueError:
                        # If the format is wrong (e.g. "invalid-date"), log it and use None
                        logger.warning(f"TRANSFORM: Incorrect timestamp format: {date_open}. Setting to None.")
                        date_open = None
                else:
                    # If timestamp is missing entirely, use None
                    logger.warning(f"TRANSFORM: Timestamp missing for {measure.get('label')}. Setting to None.")
                    date_open = None    
            
                enriched_reading = {

                    # Station_info metadata
                    "station_name": measure.get("label").strip(),
                    "river_name": measure.get("river_name").strip(),
                    "date_opened": date_open,
                    "status": measure.get("status").strip().lower(),
                    "station_url": measure.get("station_url").strip(),

                    # Measure metadata
                    "parameter": measure.get("parameter").strip(),      
                    "unit": measure.get("unit").strip(),               
                    "measure_notation": measure.get("measure_notation"),   
                    "measure_url" : url.strip(),

                    # Reading data
                    "measured_timestamp": transformed_timestamp,
                    "measured_value": reading.get("value"),
                    "measured_quality": reading.get("quality").strip().lower()
                    
                }
                all_readings.append(enriched_reading)
            
            logger.info(f"  -> Transformed {len(readings)} readings for {measure.get('parameter')} ({measure.get('unit')})")
        
        logger.info(f"TRANSFORM: Total readings Transformed: {len(all_readings)}")

        df = pd.DataFrame(all_readings)
        logger.info(f"TRANSFORM: Created DataFrame with shape: {df.shape}")

        # return df
    

        # ================================================================
        # Dimension DataFrame
        # ================================================================ 
        logger.info(f"TRANSFORM: Dimension DataFrame dim_station")

        dim_station = df[["station_name", "river_name", "date_opened", "status", "station_url" ]].copy().drop_duplicates().reset_index(drop=True)
        dim_station['station_id']  = dim_station.index + 1 
        # Reorder columns
        dim_station = dim_station[['station_id', "station_name", "river_name", "date_opened", "status", "station_url" ]]
        logger.info(f"TRANSFORM: dim_station transformed ")

    
        logger.info(f"TRANSFORM: Dimension DataFrame dim_measure") 
        dim_measure = df[["parameter", "unit", "measure_notation", "measure_url"]].copy().drop_duplicates().reset_index(drop=True)
        dim_measure['parameter_id']  = dim_measure.index + 1 
        # Reorder columns
        dim_measure = dim_measure[['parameter_id', "parameter", "unit", "measure_notation", "measure_url"]]
        logger.info(f"TRANSFORM: dim_measure transformed ")


        # ================================================================
        # Fact DataFrame
        # ================================================================
        all_df = df.copy()

        logger.info(f"TRANSFORM: Fact DataFrame") 

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
        fact_df = all_df[['station_id', 'parameter_id', "measured_timestamp", "measured_value", "measured_quality" ]].copy()
        fact_df['fact_id']  = fact_df.index + 1 

        # Replace text with integer codes
        quality_mapping = {'unchecked': 0, 'checked': 1}
        fact_df['measured_quality'] = fact_df['measured_quality'].map(quality_mapping)

        # Reorder columns
        fact_df = fact_df[["fact_id",'station_id', 'parameter_id', "measured_timestamp", "measured_value", "measured_quality"]]
        logger.info(f"TRANSFORM: Fact_df transformed ")

        return dim_station, dim_measure, fact_df

    
    except ValueError as e:
        logger.error(f"TRANSFORM: failed: {e}")
        raise
