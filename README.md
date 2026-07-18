# hydrology-pipeline-v2

Production-grade rebuild of the UK Hydrology ingestion pipeline.
Medallion architecture on Azure: ADF (ingestion, orchestration) ->
ADLS Gen2 (bronze) -> Databricks + Delta (silver, gold).

See BUILD_PLAN.md for the build sequence. Transformation logic lives in
src/ and is covered by the test suite in tests/, run on every push by CI.
