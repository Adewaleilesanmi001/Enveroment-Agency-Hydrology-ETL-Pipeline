from load import load_to_sqlite


from transform import transform
from logger_setup import get_logger
logger = get_logger(__name__)



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
