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

    # Patch the health check too: unit tests must not depend on the live API
    with patch('extract.check_api_reachable', return_value=True):
        with patch('extract.requests.get', return_value=fake_response):
            with patch('extract.TARGET_PARAMETERS', ["DISSOLVED OXYGEN", "CONDUCTIVITY"]):
                measures = extract_measures()

    assert len(measures) == 2
    params = [m["parameter"] for m in measures]
    assert "DISSOLVED OXYGEN" in params
    assert "CONDUCTIVITY" in params
    assert "TEMPERATURE" not in params


def test_exact_parameter_matching_no_substring_false_positives():
    """OXYGEN must NOT match inside DISSOLVED OXYGEN: matching is exact, not substring.

    Regression test for the TARGET_PARAMETERS parsing fix: when targets were a
    raw comma-separated string, `in` performed substring matching and a target
    of OXYGEN would wrongly capture DISSOLVED OXYGEN measures.
    """

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
            ]
        }]
    }

    with patch('extract.check_api_reachable', return_value=True):
        with patch('extract.requests.get', return_value=fake_response):
            with patch('extract.TARGET_PARAMETERS', ["OXYGEN"]):
                measures = extract_measures()

    assert measures == []


def test_raises_connection_error_when_api_unreachable():
    """Fail fast: if the health check fails, raise ConnectionError before any extraction."""

    with patch('extract.check_api_reachable', return_value=False):
        with pytest.raises(ConnectionError):
            extract_measures()
