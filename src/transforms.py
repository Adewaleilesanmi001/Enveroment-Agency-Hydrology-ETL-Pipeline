"""Core transformation logic for the Hydrology pipeline (silver layer).

Pure functions on Spark DataFrames so the same code runs in Databricks
notebooks and in CI under plain pyspark. No I/O in this module — reading
bronze and writing Delta happens in the notebooks.
"""

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

READING_SCHEMA = T.StructType(
    [
        T.StructField("station_id", T.StringType(), nullable=False),
        T.StructField("measure_id", T.StringType(), nullable=True),
        T.StructField("date_time", T.TimestampType(), nullable=False),
        T.StructField("value", T.DoubleType(), nullable=True),
        # EA per-reading quality flag: Unchecked -> Good/Estimated/Suspect after QA
        T.StructField("quality", T.StringType(), nullable=True),
    ]
)

INTERVAL_SECONDS = 15 * 60  # API cadence: one reading per 15 minutes
MAX_INTERPOLATION_GAP = 4   # interpolate gaps up to 4 intervals (1 hour)
FLATLINE_WINDOW_READINGS = 24  # 24 readings * 15 min = 6 hours


def enforce_schema(df: DataFrame) -> DataFrame:
    """Cast incoming bronze columns to the canonical silver schema."""
    quality_col = (
        F.col("quality").cast("string")
        if "quality" in df.columns
        else F.lit(None).cast("string")
    )
    return df.select(
        F.col("station_id").cast("string").alias("station_id"),
        F.col("measure_id").cast("string").alias("measure_id"),
        F.col("date_time").cast("timestamp").alias("date_time"),
        F.col("value").cast("double").alias("value"),
        quality_col.alias("quality"),
    )


def validate(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Split rows into (valid, quarantined).

    Quarantine rather than silently drop, so bad data is visible.
    """
    is_valid = (
        F.col("station_id").isNotNull()
        & F.col("date_time").isNotNull()
    )
    return df.filter(is_valid), df.filter(~is_valid)


def deduplicate(df: DataFrame) -> DataFrame:
    """One row per (station_id, date_time); keep the latest-seen value."""
    w = Window.partitionBy("station_id", "date_time").orderBy(
        F.col("value").isNull().asc()  # prefer non-null values
    )
    return (
        df.withColumn("_rn", F.row_number().over(w))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )


def interpolate_short_gaps(df: DataFrame) -> DataFrame:
    """Linearly interpolate missing values in gaps of up to
    MAX_INTERPOLATION_GAP consecutive intervals per station.

    Longer gaps stay null. All imputed rows are flagged is_imputed=true
    so downstream consumers can distinguish measured from estimated.
    """
    w = Window.partitionBy("station_id").orderBy("date_time")

    prev_val = F.last("value", ignorenulls=True).over(
        w.rowsBetween(Window.unboundedPreceding, -1)
    )
    next_val = F.first("value", ignorenulls=True).over(
        w.rowsBetween(1, Window.unboundedFollowing)
    )
    prev_ts = F.last(
        F.when(F.col("value").isNotNull(), F.col("date_time")), ignorenulls=True
    ).over(w.rowsBetween(Window.unboundedPreceding, -1))
    next_ts = F.first(
        F.when(F.col("value").isNotNull(), F.col("date_time")), ignorenulls=True
    ).over(w.rowsBetween(1, Window.unboundedFollowing))

    gap_seconds = F.col("_next_ts").cast("long") - F.col("_prev_ts").cast("long")
    gap_intervals = (gap_seconds / INTERVAL_SECONDS) - 1
    frac = (
        (F.col("date_time").cast("long") - F.col("_prev_ts").cast("long"))
        / gap_seconds
    )
    interpolated = F.col("_prev_val") + frac * (F.col("_next_val") - F.col("_prev_val"))

    can_interpolate = (
        F.col("value").isNull()
        & F.col("_prev_val").isNotNull()
        & F.col("_next_val").isNotNull()
        & (gap_intervals <= MAX_INTERPOLATION_GAP)
    )

    return (
        df.withColumn("_prev_val", prev_val)
        .withColumn("_next_val", next_val)
        .withColumn("_prev_ts", prev_ts)
        .withColumn("_next_ts", next_ts)
        .withColumn("is_imputed", can_interpolate)
        .withColumn(
            "value",
            F.when(can_interpolate, interpolated).otherwise(F.col("value")),
        )
        .drop("_prev_val", "_next_val", "_prev_ts", "_next_ts")
    )


def detect_flatlines(df: DataFrame) -> DataFrame:
    """Return one row per (station, window-end) where the value has been
    identical for FLATLINE_WINDOW_READINGS consecutive readings.

    Volume-based alerts miss this failure mode: rows keep arriving, but
    they carry a stuck value. A real river is never flat for 6 hours.
    """
    w = (
        Window.partitionBy("station_id")
        .orderBy("date_time")
        .rowsBetween(-(FLATLINE_WINDOW_READINGS - 1), 0)
    )
    return (
        df.filter(F.col("value").isNotNull())
        .withColumn("_n", F.count("value").over(w))
        .withColumn("_distinct_vals", F.size(F.collect_set("value").over(w)))
        .filter(
            (F.col("_n") == FLATLINE_WINDOW_READINGS)
            & (F.col("_distinct_vals") == 1)
        )
        .select(
            "station_id",
            F.col("date_time").alias("window_end"),
            F.col("value").alias("stuck_value"),
        )
    )
