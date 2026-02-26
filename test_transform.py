"""Tests for transform.py"""

import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch, Mock
from transform import transform


def test_transform_returns_three_dataframes():
    """Should return dim_station, dim_measure, fact."""
    
    # Mock the extraction
    mock_station = {
        "parameter": "DISSOLVED OXYGEN",
        "measure_notation": "TEST-001",
        "unit": "mg/l",
        "measure_url": "http://test.url",
        "label": "TEST_STATION",
        "river_name": "TEST_RIVER",
        "date_open": "2023-12-01",
        "status": "Active",
        "station_url": "http://station.url"
    }




    # mock_measures = {"parameter": "Oxygen", "unit": "mg/l", "measure_notation": "O1", "measure_url": "http://o1"}
    
    
    with patch('transform.extract_measures', return_value=[mock_station]):
        with patch('transform.extract_readings', return_value=[
            {"timestamp": "2024-01-01T10:00:00Z", "value": 8.5, "quality": "Checked"}
        ]):
            dim_station, dim_measure, fact_df = transform()
    
    # Check types
    assert isinstance(dim_station, pd.DataFrame)
    assert isinstance(dim_measure, pd.DataFrame)
    assert isinstance(fact_df, pd.DataFrame)
    
    # Check rows created
    assert len(dim_station) == 1
    assert len(dim_measure) == 1
    assert len(fact_df) == 1
    
    # Column is 'measured_value', not 'value'
    assert fact_df["measured_value"].iloc[0] == 8.5
    
    # Check foreign keys exist
    assert "station_id" in fact_df.columns
    assert "parameter_id" in fact_df.columns
    assert fact_df["station_id"].iloc[0] == 1
    assert fact_df["parameter_id"].iloc[0] == 1



