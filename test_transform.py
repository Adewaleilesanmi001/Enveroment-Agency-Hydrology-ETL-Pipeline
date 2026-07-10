"""Tests for transform.py"""

import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch, Mock
from transform import transform


def _mock_measure():
    return {
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


def test_transform_returns_three_dataframes():
    """Should return dim_station, dim_measure, fact."""

    with patch('transform.extract_measures', return_value=[_mock_measure()]):
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

    # Z-suffixed timestamp parses to a real datetime (not None), on all Python versions
    assert fact_df["measured_timestamp"].iloc[0] is not None

    # Quality text maps to integer code
    assert fact_df["measured_quality"].iloc[0] == 1

    # Check foreign keys exist
    assert "station_id" in fact_df.columns
    assert "parameter_id" in fact_df.columns
    assert fact_df["station_id"].iloc[0] == 1
    assert fact_df["parameter_id"].iloc[0] == 1


def test_malformed_timestamp_becomes_none_instead_of_crashing():
    """Defensive parsing: a garbage timestamp is logged and set to None; the run completes."""

    with patch('transform.extract_measures', return_value=[_mock_measure()]):
        with patch('transform.extract_readings', return_value=[
            {"timestamp": "not-a-real-date", "value": 7.2, "quality": "Unchecked"}
        ]):
            dim_station, dim_measure, fact_df = transform()

    assert len(fact_df) == 1
    assert pd.isna(fact_df["measured_timestamp"].iloc[0])
    assert fact_df["measured_value"].iloc[0] == 7.2
    assert fact_df["measured_quality"].iloc[0] == 0


def test_unknown_quality_value_maps_to_minus_one():
    """Quality values outside the known mapping become -1 (unknown), never NaN."""

    with patch('transform.extract_measures', return_value=[_mock_measure()]):
        with patch('transform.extract_readings', return_value=[
            {"timestamp": "2024-01-01T10:00:00Z", "value": 5.0, "quality": "Estimated"}
        ]):
            dim_station, dim_measure, fact_df = transform()

    assert fact_df["measured_quality"].iloc[0] == -1
