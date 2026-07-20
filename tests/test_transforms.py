"""Tests for silver-layer transformation logic.

Runs in CI under plain pyspark (local[2]) — no Azure required.
"""

import datetime as dt

import pytest
from pyspark.sql import SparkSession

from src.transforms import (
    FLATLINE_WINDOW_READINGS,
    deduplicate,
    detect_flatlines,
    enforce_schema,
    interpolate_short_gaps,
    validate,
)


@pytest.fixture(scope="session")
def spark():
    spark = (
        SparkSession.builder.master("local[2]")
        .appName("hydrology-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    yield spark
    spark.stop()


def ts(minute_offset: int) -> dt.datetime:
    base = dt.datetime(2026, 7, 1, 0, 0, 0)
    return base + dt.timedelta(minutes=15 * minute_offset)


def make_df(spark, rows):
    return spark.createDataFrame(
        rows, "station_id string, measure_id string, date_time timestamp, value double"
    )


def test_enforce_schema_casts_types(spark):
    df = spark.createDataFrame(
        [("s1", "m1", "2026-07-01 00:00:00", "1.5")],
        "station_id string, measure_id string, date_time string, value string",
    )
    out = enforce_schema(df)
    assert dict(out.dtypes)["date_time"] == "timestamp"
    assert dict(out.dtypes)["value"] == "double"


def test_validate_quarantines_null_keys(spark):
    df = make_df(
        spark,
        [
            ("s1", "m1", ts(0), 1.0),
            (None, "m1", ts(1), 2.0),
            ("s1", "m1", None, 3.0),
        ],
    )
    valid, quarantined = validate(df)
    assert valid.count() == 1
    assert quarantined.count() == 2


def test_deduplicate_keeps_one_row_per_station_timestamp(spark):
    df = make_df(
        spark,
        [
            ("s1", "m1", ts(0), 1.0),
            ("s1", "m1", ts(0), 1.0),  # exact duplicate
            ("s1", "m1", ts(0), None),  # null dup — non-null must win
            ("s2", "m1", ts(0), 9.0),
        ],
    )
    out = deduplicate(df)
    assert out.count() == 2
    s1 = out.filter("station_id = 's1'").collect()[0]
    assert s1["value"] == 1.0


def test_deduplicate_is_idempotent(spark):
    """Merge-key logic: applying dedup twice changes nothing."""
    df = make_df(spark, [("s1", "m1", ts(i % 3), float(i)) for i in range(9)])
    once = deduplicate(df)
    twice = deduplicate(once)
    assert once.count() == twice.count() == 3


def test_interpolates_short_gap_linearly(spark):
    # values 1.0, gap of 2 readings, 4.0 -> expect 2.0 and 3.0
    df = make_df(
        spark,
        [
            ("s1", "m1", ts(0), 1.0),
            ("s1", "m1", ts(1), None),
            ("s1", "m1", ts(2), None),
            ("s1", "m1", ts(3), 4.0),
        ],
    )
    out = interpolate_short_gaps(df).orderBy("date_time").collect()
    assert out[1]["value"] == pytest.approx(2.0)
    assert out[2]["value"] == pytest.approx(3.0)
    assert out[1]["is_imputed"] is True
    assert out[0]["is_imputed"] is False


def test_does_not_interpolate_long_gap(spark):
    # 6 missing readings > MAX_INTERPOLATION_GAP (4) -> stay null
    rows = [("s1", "m1", ts(0), 1.0)]
    rows += [("s1", "m1", ts(i), None) for i in range(1, 7)]
    rows += [("s1", "m1", ts(7), 8.0)]
    out = interpolate_short_gaps(make_df(spark, rows)).orderBy("date_time").collect()
    assert all(r["value"] is None for r in out[1:7])
    assert all(r["is_imputed"] is False for r in out[1:7])


def test_detects_six_hour_flatline(spark):
    # 24 consecutive identical readings = 6h stuck value -> one alert
    rows = [("s1", "m1", ts(i), 2.5) for i in range(FLATLINE_WINDOW_READINGS)]
    alerts = detect_flatlines(make_df(spark, rows))
    assert alerts.count() == 1
    a = alerts.collect()[0]
    assert a["stuck_value"] == 2.5


def test_no_flatline_alert_for_varying_values(spark):
    rows = [
        ("s1", "m1", ts(i), 2.5 + (i % 2) * 0.01)
        for i in range(FLATLINE_WINDOW_READINGS * 2)
    ]
    assert detect_flatlines(make_df(spark, rows)).count() == 0


def test_enforce_schema_carries_quality_flag(spark):
    df = spark.createDataFrame(
        [("s1", "m1", "2026-07-01 00:00:00", "1.5", "Unchecked")],
        "station_id string, measure_id string, date_time string, value string, quality string",
    )
    out = enforce_schema(df)
    assert out.collect()[0]["quality"] == "Unchecked"


def test_enforce_schema_adds_null_quality_when_absent(spark):
    df = spark.createDataFrame(
        [("s1", "m1", "2026-07-01 00:00:00", "1.5")],
        "station_id string, measure_id string, date_time string, value string",
    )
    out = enforce_schema(df)
    assert "quality" in out.columns
    assert out.collect()[0]["quality"] is None



def test_deduplicate_prefers_latest_ingest(spark):
    """A revised reading (later ingest) must supersede the original."""
    rows = [
        ("s1", "m1", ts(0), 1.0, "2026-07-19"),   # original
        ("s1", "m1", ts(0), 2.0, "2026-07-20"),   # revised, later load
    ]
    df = spark.createDataFrame(
        rows,
        "station_id string, measure_id string, date_time timestamp, "
        "value double, ingest_date string",
    )
    out = deduplicate(df).collect()
    assert len(out) == 1
    assert out[0]["value"] == 2.0
