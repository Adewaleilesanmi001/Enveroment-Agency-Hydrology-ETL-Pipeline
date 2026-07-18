# Hydrology Pipeline v2 — Azure End-to-End Rebuild
### Weekend build plan (Fri eve → Sun) with Tuesday interview as the deadline

**The rule for this weekend:** everything you build, you can defend. Every step below ends with a "you can now say" line — that sentence is what the build buys you in the interview.

**Cost guardrails (read first):**
- Databricks: use the **14-day Azure Databricks trial** (free DBUs; you still pay the VM). Create a **single-node cluster**, smallest VM available (e.g. Standard_F4 / DS3 v2), **auto-terminate at 10 minutes**. Never leave it running.
- ADF: debug runs and a handful of triggered runs cost pennies.
- ADLS: gigabytes of parquet = pennies.
- Expected total for the weekend: **under £10** if the cluster auto-terminates. Set a **£20 budget alert** on the subscription (Cost Management → Budgets) before anything else.

---

## Friday evening (60–90 min) — Foundations

1. **Resource group:** `rg-hydrology-prod` in UK South.
2. **Storage:** ADLS Gen2 account (hierarchical namespace ON), containers: `bronze`, `silver`, `gold`, `meta`.
3. **Databricks workspace** (trial tier) + **Data Factory** instance in the same resource group.
4. **Explore the API in the browser** — refresh your memory of the real thing:
   - Base: `https://environment.data.gov.uk/hydrology/`
   - Stations: `/id/stations?observedProperty=waterLevel&_limit=50`
   - Readings: `/id/measures/{measureId}/readings?mineq-date=2026-07-01&_limit=500`
   - Confirm for yourself: 15-minute cadence → **96 readings/station/day**. Note pagination (`_limit`, `_offset`) and date filters (`mineq-date`, `max-date`) — these power your incremental load.
5. **GitHub:** create repo `hydrology-pipeline-v2` (or a `v2/` branch of the existing repo), push this scaffold, confirm CI goes green on the included tests.

**You can now say:** "The API filters readings by date, which is what makes incremental loading possible — each run only requests data since the last watermark."

---

## Saturday — Ingestion + Bronze (the ADF day)

### Morning: watermark + ingestion design
1. In `meta` container create `watermark.json`: `{"last_loaded": "2026-07-10T00:00:00Z"}` (start ~a week back so first runs are small).
2. ADF pipeline `pl_ingest_hydrology`:
   - **Lookup** activity → reads `watermark.json`.
   - **Copy** activity → REST **linked service** to the Hydrology API; relative URL built with `@concat(...)` injecting the watermark into `mineq-date`; sink = `bronze` container as **Parquet**, path `bronze/readings/ingest_date=YYYY-MM-DD/`.
   - **Copy/Web** activity → writes the new watermark (pipeline start time) back to `meta/watermark.json` **only on success**.
3. Pick **3–5 stations** to keep volume sane; parameterise station/measure IDs so scaling to hundreds is "add config, not code" (interview line!).

### Afternoon: run + schedule
4. Debug-run until parquet lands in bronze. Inspect a file (ADF preview or Databricks).
5. **Scheduled trigger:** daily **00:00 UK**. This resolves the Airflow/ADF question permanently: **the answer is ADF scheduled triggers.**
6. Add a **failure alert**: Azure Monitor alert rule on pipeline-failed metric → email.

**You can now say:** "ADF reads a watermark from the lake, calls the API for readings since that timestamp, lands them as parquet in bronze partitioned by ingest date, and only advances the watermark on success — so a failed run just re-runs, nothing is skipped or duplicated."

---

## Sunday — Silver + Gold (the Databricks day)

### Morning: silver notebook `nb_bronze_to_silver`
1. Read new bronze parquet.
2. Enforce schema: explicit types for `station_id`, `measure_id`, `dateTime` (timestamp), `value` (double).
3. Validate: drop/quarantine null keys and impossible values; count what you quarantine.
4. **Deduplicate** on `station_id + dateTime`.
5. **MERGE INTO** Delta table `silver.readings` matching on `station_id` AND `dateTime`: matched → update, not matched → insert. **Run the pipeline twice and prove row counts don't change — screenshot it.** That screenshot is your idempotency proof.
6. **Interpolation:** for gaps ≤ 4 intervals (1 hour), linear interpolation via Spark window functions; longer gaps left null and **flagged** in an `is_imputed` / `gap_length` column. (This is more defensible than v1: you now impute only short gaps and mark everything imputed.)

### Afternoon: gold + wiring + quality
7. Gold notebook `nb_silver_to_gold`: daily aggregates per station (min/max/mean level, reading count, completeness % = count/96), written as Delta to `gold`.
8. **Flat-line detector** (your war story, productionised): a check that flags any station whose value variance over a rolling 6-hour window is zero → writes to a `quality_alerts` Delta table. *The v1 incident is now a v2 feature — gold interview material.*
9. Wire ADF: after the Copy activity, a **Databricks Notebook activity** runs silver, then gold. One pipeline, end to end.
10. Full run: trigger manually → API → bronze → silver → gold. Verify counts (~96/station/day).
11. Sync notebook code into the repo (Databricks Repos or export), push, CI green.

**You can now say:** "Re-runs are idempotent — I've verified it: same-day double runs produce identical silver counts because loads are Delta merges on station and timestamp, not appends. And after an incident where a source flat-lined for six hours without tripping volume alerts, v2 monitors value variance, not just row counts."

---

## Monday — Freeze + drill (NO new features)

- Morning: update README with an architecture diagram (Mermaid is fine) and the design decisions.
- Rotate the OpenWeather key on the old repo if still pending.
- Evening: **full technical mock with Claude.** You'll answer every question from something you built 24 hours earlier.

## After Tuesday — Phase 2 hardening backlog
- Great-Expectations-style data tests in the pipeline; schema-drift alerts
- Key Vault for secrets; managed identity between ADF/Databricks/ADLS
- CI deploy of notebooks; ADF ARM template export into the repo (`adf/` folder)
- Scale-out: config-driven station list to 50+ stations
- Cost dashboard + SLA doc — then this repo headlines every application

---

## Scaffold contents (this folder)
- `src/transforms.py` — pure PySpark transformation functions (dedup, schema, interpolation, flat-line detection) importable by notebooks AND testable in CI
- `tests/test_transforms.py` — pytest suite proving dedup, idempotent merge keys, interpolation limits, flat-line detection
- `.github/workflows/ci.yml` — runs the suite on every push
- `notebooks/` — outlines for the two Databricks notebooks (fill in during Sunday)
- `adf/README.md` — checklist for exporting your ADF pipeline JSON into the repo

Push this today, get CI green, then start Friday-evening steps.
