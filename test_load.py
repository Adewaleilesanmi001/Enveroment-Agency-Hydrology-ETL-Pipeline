"""Tests for load.py"""

import pytest
import pandas as pd
import sqlite3
import os
from datetime import datetime
from load import load_to_sqlite


def test_load_creates_database(tmp_path):
    """Should create SQLite file with tables."""
    
    db_path = tmp_path / "test.db"
    
    dim_s = pd.DataFrame({
        "station_id": [1],
        "station_name": ["Test"],
        "river_name": ["River"],
        "date_opened": [datetime.now()],
        "status": ["Active"],
        "station_url": ["http://test"]
    })
    
    dim_m = pd.DataFrame({
        "parameter_id": [1],
        "parameter": ["Oxygen"],
        "unit": ["mg/l"],
        "measure_notation": ["O1"],
        "measure_url": ["http://o1"]
    })
    
    fact = pd.DataFrame({
        "fact_id": [1],
        "station_id": [1],
        "parameter_id": [1],
        "measured_timestamp": [datetime.now()],
        "measured_value": [8.5],
        "measured_quality": ["Good"]
    })
    
    load_to_sqlite(dim_s, dim_m, fact, str(db_path))
    
    assert os.path.exists(db_path)
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    
    assert "dim_stations" in tables
    assert "dim_measures" in tables
    assert "fact_readings" in tables
    
    conn.close()