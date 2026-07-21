# Databricks Notebooks — Transformation Layer

Serverless compute, storage governed by Unity Catalog (credential
`cred_hydrology` = workspace managed identity; external locations `loc_bronze`,
`loc_silver`, `loc_gold`, `loc_meta` — one per container; no keys in code).
All notebooks live in this repo via a Git folder and change through branch → PR →
CI → merge, like any code. Business logic is imported from `src/transforms.py`
(pure functions, covered by the 11-test suite); notebooks are deliberately thin —
they do I/O and orchestration only.

## `nb_explore` — source profiling

Reads raw bronze, prints the inferred schema (note `ingest_date` appearing as a free
column from the Hive partition names), explodes `items`, and profiles per-day counts.
This notebook produced the completeness profile (96 on clean days, 94–95 where
telemetry dropped) and the doubled-day evidence of overlapping load windows.

## `nb_bronze_to_silver` — the refinery

Cell-by-cell contract:

1. **Setup** — `sys.path.append(<repo>)`; import the five transforms; define paths.
   Partition selection: `run_date` arrives as a **widget parameter from the
   orchestrator** (same expression that stamped the folder); when run manually with
   no value, the notebook defaults to the newest partition present. The read filters
   to that single partition — partition pruning keeps nightly compute constant
   regardless of history.
2. **Explode & key** — `F.explode("items")`; extract `station_id` with
   `regexp_extract(measure_id, r"measures/(.+?)-(?:level|flow)", 1)` — anchored on
   the measure suffix because **station GUIDs contain hyphens** (a first-hyphen split
   captures garbage; there is a test for this).
3. **Clean** — `enforce_schema` (types; `quality` carried, null-safe) → `validate`
   (invalid rows **quarantined** to `silver/quarantine`, never dropped) →
   `deduplicate` (row_number window ordered by `ingest_date DESC`, then non-null
   value — so **revisions supersede originals**; dropDuplicates would keep an
   arbitrary row) → `interpolate_short_gaps` (linear fill for gaps ≤ 4 intervals /
   1 hour, every filled row flagged `is_imputed`; longer gaps stay null on purpose).
4. **Create table** — first run only (`isDeltaTable` guard), Delta at
   `silver/readings`.
5. **MERGE** — `ON t.station_id = s.station_id AND t.date_time = s.date_time`,
   matched → update all, not matched → insert all. This one statement absorbs
   revisions, absorbs the lookback overlap, and makes re-runs idempotent.
6. **Idempotency check** — the merge run twice must leave the count unchanged
   (verified: **4,371 = 4,371**).
7. **Flat-line detection** — `detect_flatlines`: 24-reading (6-hour) sliding window
   per station; alert when the window is full and contains exactly one distinct
   value. Fires **once per window position** while flatness persists, so a run of
   length N produces N−23 alerts (a 36-reading run ⇒ 13 alerts). First production
   contact: 30 alerts = 3 genuine low-flow episodes. Episode-grouping is the
   backlog refinement. Detection is post-merge by design: the pattern can span
   batches, and a flat-line is a smell, not a verdict — gate structural problems,
   surface contextual ones.
8–9. **Investigation cells** — group alerts by stuck value into episodes; display
   the raw readings around the first alert.
10. **Gold** — daily `min/max/mean(value)`, `reading_count`,
   `imputed_count`, `completeness = reading_count / 96` per station per day, Delta
   at `gold/daily_station_summary`. Completeness is the honesty metric: it surfaces
   structural gaps (absent rows) that interpolation cannot see.
11. **Watermark advance** — LAST cell on purpose: computes `max(date_time)` from
   silver (data-derived, not `utcnow()`) and writes `meta/watermark.json`. Any
   failure above stops the notebook, the mark never moves, and the next run
   self-heals through the merge.

## Known behaviours & backlog

- Gaps in this source are **structural** (missing rows), not null-valued — so
  interpolation currently fills nothing and completeness carries the signal.
  Materialising the expected 15-minute grid is the planned fix.
- Gold is rebuilt with overwrite (fine at current scale); incremental refresh
  scoped to affected dates is the planned refinement.
- Quality findings persist to tables but do not yet notify; routing a non-zero
  alert count into the existing ADF failure alert (deliberately fail the job) is
  the cheapest closure.
