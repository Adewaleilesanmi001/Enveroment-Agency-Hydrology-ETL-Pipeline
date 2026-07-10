import requests
from typing import List, Dict

from logger_setup import get_logger
logger = get_logger(__name__)

import os
from dotenv import load_dotenv
load_dotenv()

# Base URL for HIPPER_PARK ROAD BRIDGE_E_202312
BASE_URL = os.getenv('BASE_URL')

# Target parameters (match API's uppercase 'parameter' field).
# Parsed into a real list so matching is exact, not substring:
# previously "OXYGEN" would have wrongly matched inside "DISSOLVED OXYGEN".
TARGET_PARAMETERS = [p.strip() for p in os.getenv('TARGET_PARAMETERS', '').split(',') if p.strip()]

# Filter parameters for API
FILTER_PARAMS = {"_limit": 10, "_sort": "-dateTime"}


"""
Extract module - Functions for extraction.
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

    # CHECK API FIRST - fail fast with a clear error rather than half-running
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

            # Exact match against the configured target list
            if param_name in TARGET_PARAMETERS:
                # Use notation field - official measure ID from API

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


"""
Extract module - Helper function for extracting measure readings.
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
