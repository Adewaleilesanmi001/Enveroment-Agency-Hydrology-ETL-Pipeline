"""Tests for extract.py"""

import pytest
from unittest.mock import Mock, patch
from extract import extract_measures, extract_readings


def test_extracts_only_target_parameters():
    """Should filter for DISSOLVED OXYGEN and CONDUCTIVITY only."""
    
    fake_response = Mock()
    fake_response.json.return_value = {
        "items": [{
            "label": "Test Station",
            "riverName": "Test River",
            "dateOpened": "2023-01-01",
            "status": [{"label": "Active"}],
            "@id": "http://test",
            "measures": [
                {"parameter": "DISSOLVED OXYGEN", "notation": "O1", "unitName": "mg/l", "@id": "http://o1"},
                {"parameter": "TEMPERATURE", "notation": "T1", "unitName": "C", "@id": "http://t1"},
                {"parameter": "CONDUCTIVITY", "notation": "C1", "unitName": "uS", "@id": "http://c1"},
            ]
        }]
    }
    
    with patch('extract.requests.get', return_value=fake_response):
        measures = extract_measures()
    
    assert len(measures) == 2
    params = [m["parameter"] for m in measures]
    assert "DISSOLVED OXYGEN" in params
    assert "CONDUCTIVITY" in params
    assert "TEMPERATURE" not in params