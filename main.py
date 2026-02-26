import requests
import pandas as pd
from datetime import datetime
import sqlite3
from typing import List, Dict, Tuple


from logger_setup import get_logger
logger = get_logger(__name__)

import os
from dotenv import load_dotenv
load_dotenv()

# Base URL for HIPPER_PARK ROAD BRIDGE_E_202312
BASE_URL = os.getenv('BASE_URL') 

# Target parameters (match API's uppercase 'parameter' field)
TARGET_PARAMETERS = os.getenv('TARGET_PARAMETERS') 

# Database name
DB_PATH = os.getenv('DB_PATH') 

# Filter parameters for API
FILTER_PARAMS = {"_limit": 10, "_sort": "-dateTime"} 

# Station Dimension (Fixed for HIPPER_PARK ROAD BRIDGE_E_202312)
# STATION_ID = "E64999A"
# STATION_NAME = "HIPPER_PARK ROAD BRIDGE_E_202312"
# RIVER_NAME = "HIPPER"
# DATE_OPENED = "2023-12-01"
# STATION_STATUS = "Active"

"""
Extract module - Fuction for extraction.
"""

def check_api_reachable(url: str) -> bool:
    """Quick check if API is up."""
    try:
        response = requests.head(url, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False



def extract_measures() -> List[Dict]:
    """Dynamically discover all measures matching target parameters."""
    logger.info("EXTRACT: Checking API availability...")

    # CHECK API FIRST
    if not check_api_reachable(BASE_URL):
        logger.error("EXTRACT: API is down - cannot connect")
        raise ConnectionError(f"Hydrology API unreachable at {BASE_URL}")
    
    logger.info("EXTRACT: API is reachable - proceeding with extraction")

    try:
        response = requests.get(BASE_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
        logger.info("EXTRACT: Connected to API")
        
        # Station is in items[0]
        station = data["items"][0]
        measures = station.get("measures", [])
        
        found_measures = []
        
        for measure in measures:
            # Get parameter name (API uses "parameter" field, uppercase)
            param_name = measure.get("parameter", "")
            
            # Check if this parameter is in our targets
            if param_name in TARGET_PARAMETERS:
                # Use notation field — official measure ID from API           
                
                measure_info = {
                    "parameter": param_name,
                    "measure_notation": measure.get("notation", ""), 
                    "unit": measure.get("unitName", "unknown"),
                    "period": measure.get("period", "unknown"),
                    "measure_url": measure.get("@id", ""),

                    # Include station info in each measure 
                    "label": station.get("label"),
                    "river_name": station.get("riverName"),
                    "date_open": station.get("dateOpened"),
                    "status": station['status'][0].get("label"),
                    "station_url": station.get("@id", "")
                }
                
                found_measures.append(measure_info)
                logger.info(f"EXTRACT: Found: {param_name} | ID: {measure_info.get('measure_notation')} | Unit: {measure_info.get('unit')}")

        logger.info(f"EXTRACT: Discovered {len(found_measures)} measures")
        return found_measures
       
    except requests.RequestException as e:
        logger.error(f"EXTRACT failed: {e}")
        raise


# print(extract_measures())
"""
Extract module - Helper function for extracting measure dat information.
"""

def extract_readings(measure_url: str) -> List[Dict]:
    """Fetch readings for a specific measure."""
    url = f"{measure_url}/readings.json"

    try:
        response = requests.get(url, params=FILTER_PARAMS, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        readings = []
        for item in data.get("items", []):
            readings.append({
                "timestamp": item.get("dateTime"),
                "value": item.get("value"),
                "quality": item.get("quality", "Unknown")
            })
        
        return readings
    
    except requests.RequestException as e:
        logger.error(f"EXTRACT: Fetch readings failed for {measure_url}: {e}")
        return []
    

# print(extract_readings('http://environment.data.gov.uk/hydrology/id/measures/E64999A-cond-i-subdaily-uS'))


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


"""
Loading function - Loading fuction for creating DB and tables.
"""
def create_tables(conn):
    """Create tables with explicit schema definitions."""
    cursor = conn.cursor()
    
    # Drop existing tables
    cursor.executescript("""
                   DROP TABLE IF EXISTS fact_readings;
                   DROP TABLE IF EXISTS dim_measures;
                   DROP TABLE IF EXISTS dim_stations;
                   """)
    


    logger.info("LOAD: Dropped existing tables")
    
    # Create dim_station
    cursor.execute("""
        CREATE TABLE dim_stations (
            station_id INTEGER PRIMARY KEY,
            station_name TEXT NOT NULL,
            river_name VARCHAR(50),
            date_opened TIMESTAMP NOT NULL,
            status VARCHAR(20) NOT NULL,
            "station_url" TEXT
        )
    """)
    logger.info("LOAD: Created dim_stations table")
    
    # Create dim_measure
    cursor.execute("""
        CREATE TABLE dim_measures (
            parameter_id INTEGER PRIMARY KEY,
            parameter VARCHAR(150) NOT NULL,
            unit VARCHAR(20),
            measure_notation TEXT UNIQUE,
            "measure_url" TEXT
        )
    """)
    logger.info("LOAD: Created dim_measures table")
    
    # Create fact_readings
    cursor.execute("""
        CREATE TABLE fact_readings (
            fact_id INTEGER PRIMARY KEY,
            station_id INTEGER NOT NULL,
            parameter_id INTEGER NOT NULL,
            measured_timestamp TIMESTAMP NOT NULL,
            measured_value NUMERIC(10,2),
            measured_quality INTEGER,
            FOREIGN KEY (station_id) REFERENCES dim_stations(station_id),
            FOREIGN KEY (parameter_id) REFERENCES dim_measures(parameter_id)
        )
    """)
    logger.info("LOAD: Created fact_readings table")
    
    conn.commit()


def load_to_sqlite(dim_station, dim_measure, fact_df, db_path=DB_PATH):
    """Load DataFrames into SQLite database with explicit schema."""
    logger.info(f"LOAD: Connecting to SQLite database: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        
        # Create tables with proper schema
        create_tables(conn)

               
        # Load dim_station
        dim_station.to_sql('dim_stations', conn, if_exists='append', index=False)
        logger.info(f"LOAD: Loaded {len(dim_station)} rows into dim_stations")

        # Load dim_measure
        dim_measure.to_sql("dim_measures", conn, if_exists='append', index=False)
        logger.info(f"LOAD: Loaded {len(dim_measure)} rows into dim_measures")
        
        # Load fact_readings
        fact_df.to_sql('fact_readings', conn, if_exists='append', index=False)
        logger.info(f"LOAD: Loaded {len(fact_df)} rows into fact_readings")        
        
        logger.info("LOAD: Successfully loaded all tables to SQLite")

        
    except sqlite3.Error as e:
        logger.error(f"LOAD: SQLite error: {e}")
        raise

    finally:
        conn.close()


# ================================================================
# Full ETL Run
# ================================================================
def run_pipeline():
    """Execute full ETL pipeline."""
    logger.info("Starting ETL pipeline...")

    dim_station, dim_measure, fact_df = transform()

    load_to_sqlite(dim_station, dim_measure, fact_df)
    logger.info("ETL pipeline completed successfully")


# Execute ETL
if __name__ == "__main__":
    run_pipeline()
