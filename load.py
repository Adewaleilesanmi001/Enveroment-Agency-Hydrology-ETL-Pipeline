import sqlite3

from logger_setup import get_logger
logger = get_logger(__name__)

import os
from dotenv import load_dotenv
load_dotenv()

# Database name
DB_PATH = os.getenv('DB_PATH') 


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


