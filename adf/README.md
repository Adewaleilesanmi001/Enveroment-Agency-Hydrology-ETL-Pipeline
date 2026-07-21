# Azure Data Factory — Ingestion Layer

Everything in the factory, object by object, including the run-time expressions and
the gotchas that cost time. Factory: `adf-hydrology-wal` (UK South).

## Object model

ADF composes five object types: **linked service** (how to connect) → **dataset**
(what exactly is pointed at, in what format) → **activity** (one action) →
**pipeline** (the recipe, with parameters) → **trigger** (when it runs). The design
pattern throughout: **static structure in definitions, dynamic values injected at
run time** via `@` expressions and parameters.

## Linked services

| Name | Type | Config |
|---|---|---|
| `ls_adls` | ADLS Gen2 | account key auth (Key Vault is on the backlog; the Databricks side is already keyless via Unity Catalog) |
| `ls_hydrology_api` | REST | Base URL `https://environment.data.gov.uk/hydrology/` (trailing slash required — relative URLs are concatenated directly), Anonymous auth |

## Datasets

| Name | Type | Purpose |
|---|---|---|
| `ds_watermark` | JSON on `ls_adls`, path `meta/watermark.json` | read by the Lookup; JSON format so `firstRow.last_loaded` is addressable by name |
| `ds_api_readings` | REST on `ls_hydrology_api`, **parameter `relativeUrl`**, connection Relative URL = `@dataset().relativeUrl` | the URL is fully assembled by the pipeline per run |
| `ds_bronze_raw` | JSON on `ls_adls`, **parameter `ingestDate`** | sink. Directory = `@concat('readings/ingest_date=', dataset().ingestDate)`, File = `@concat('readings-', dataset().ingestDate, '.json')` |

The `ingest_date=` folder naming is the **Hive partition convention**: Spark reads it
as a free, prunable column.

## Pipeline `pl_ingest_hydrology`

**Parameter:** `measureId` (string) — default is the Bywell 15-min level measure.
One recipe serves any measure; scaling is config, not code.

**Activity 1 — `LookupWatermark`** (Lookup): source `ds_watermark`, first row only.

**Activity 2 — `CopyToBronze`** (Copy, chained on success):

- Source: `ds_api_readings`, with `relativeUrl` set to:

```
@concat('id/measures/', pipeline().parameters.measureId,
        '/readings.json?mineq-date=',
        formatDateTime(addDays(activity('LookupWatermark').output.firstRow.last_loaded, -35), 'yyyy-MM-dd'),
        '&_limit=5000')
```

Decoded: measure path + this run's measure + readings-since filter where the date is
**watermark minus 35 days** (the lookback — sized to the EA's measured revision lag,
so late-published/corrected readings are re-fetched and upserted downstream) +
`_limit=5000` sized to the ~36-day window (a smaller cap would silently truncate).

- Sink: `ds_bronze_raw`, `ingestDate` = `@formatDateTime(utcNow(),'yyyy-MM-dd')`.
- **Mapping: none** — deliberately. Bronze lands the payload byte-for-byte; parsing
  happens in Spark where it is version-controlled and tested.

**Planned Activity 3** — Databricks Notebook activity running the silver notebook,
passing base parameter `run_date` = `@formatDateTime(utcNow(),'yyyy-MM-dd')` — the
**same expression as the sink**, so the folder writer and the notebook reader cannot
disagree (see the timezone incident in the root README).

## Trigger

`trg_daily_midnight`: Schedule, every 1 day at 00:00, timezone
Dublin/Edinburgh/Lisbon/London (auto-adjusts for DST), **no end date**, started on
creation. A trigger exists in the live factory only after **Publish all**.

## Alerting

Azure Monitor rule `alert-pipeline-failed`: signal *Failed pipeline runs metrics*
> 0, evaluated every minute, action group `ag-email-wal` (email). Cost ≈ $0.10/month.

## Gotchas encountered (kept so nobody repeats them)

1. **Expression in the wrong field** — the dated-directory `@concat` pasted into
   Compression Type produced `Failed to convert ... in 'compressionCodec'`. Azure
   errors name the offending property in the first `Message=` clause; read that first.
2. **Silent one-row copy** — REST→parquet flattening ran green while collapsing the
   `items` array (347 KB in, 1 row out). Caught via throughput numbers. Root cause
   class: collection-reference/mapping fragility. Resolution: raw-JSON bronze.
3. **Parameter before expression** — `dataset().ingestDate` referenced before the
   parameter existed → "Parameter not found". Slots must exist before fillers.
4. **Leading-space column names** — `' measure_id'` ≠ `measure_id`; the mapping
   banner caught an invisible character.
5. **Trigger defaults** — the recurrence default is *every 15 minutes* and an end
   date was pre-ticked; both silently wrong for a nightly pipeline. Read every field.
