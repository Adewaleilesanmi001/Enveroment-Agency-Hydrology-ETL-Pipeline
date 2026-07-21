# Build Record & Rebuild Guide

This document records how the pipeline was built, in what order, and why — detailed
enough that anyone (including future me) could rebuild it from an empty Azure
subscription. The original weekend plan became this record as the build completed.

## Phase 0 — Study the source first

Before any infrastructure: profile the API in a browser. This phase produced the four
discoveries that shaped the entire architecture (see root README, "The source drove
the design"). Key endpoints:

- Stations: `https://environment.data.gov.uk/hydrology/id/stations.json?search=<name>`
- Readings: `.../id/measures/{measureId}/readings.json?mineq-date=YYYY-MM-DD&_limit=N`

Reference station: **Bywell** (River Tyne), measure
`e786e60f-a0f1-4955-aa57-f22ba39c7427-level-i-900-m-qualified` — decode the suffix:
level, instantaneous, 900s period (15 min ⇒ 96/day), metres, qualified series.
Upstream context stations: Reaverhill (North Tyne), Haydon Bridge (South Tyne).

**Lesson of the phase:** every hour spent profiling saved a design mistake. The
publication cadence, the revision lifecycle, the flow lag and the hyphenated GUIDs
were all found here, before a line of infrastructure existed.

## Phase 1 — Foundations (≈90 min)

| Step | Detail | Why |
|---|---|---|
| Resource group | `rg-hydrology-prod`, UK South | one folder for everything |
| **Budget alert first** | £20/month, email at 80% | cost seatbelt before anything billable |
| Storage account | Standard, LRS, **hierarchical namespace ON** | HNS is what makes it ADLS Gen2 |
| Containers | `bronze`, `silver`, `gold`, `meta` | medallion + control files |
| Watermark seed | `meta/watermark.json` = `{"last_loaded": "<start>"}` | the pipeline's memory |
| Data Factory | V2, Git configured later | orchestration |
| Repo | scaffold pushed, CI green before proceeding | quality gate exists from day one |

Account note: a free Azure account was **upgraded to pay-as-you-go** (credit is
retained) because free-trial subscriptions carry near-zero compute quotas with no
increase path.

## Phase 2 — Ingestion (ADF)

Built: two linked services, three datasets, the `pl_ingest_hydrology` pipeline
(Lookup → Copy), daily 00:00 trigger, failure alert. Full object-level documentation
lives in `adf/README.md`.

Incidents worth remembering (details in root README, "Incidents & lessons"):
the misfiled expression in the compression field; the green run that wrote 1 row
from 347 KB; the architectural switch to raw-JSON bronze. **Verification standard
set here: check bytes and rows, never trust status colour alone.**

## Phase 3 — Transformation (Databricks)

- Classic VM clusters were blocked by subscription quota → **serverless compute**
  (better outcome: instant start, per-second billing, no cluster management).
- Serverless refused account-key storage access → **Unity Catalog**: one storage
  credential (workspace managed identity, granted Storage Blob Data Contributor on
  the account) + one external location per container. Result: **no keys in code**.
- Notebooks (documented in `notebooks/README.md`) run the chain:
  explode → station key → schema → quarantine → dedup → interpolate → **MERGE** →
  flat-line check → gold → watermark advance.
- Repo synced via a Git folder (PAT with `repo` scope); notebooks commit through
  branch → PR → CI → merge, same as any code.

Verification milestones achieved in this phase: dedup collapse **5,314 → 4,371**,
idempotency **4,371 = 4,371** across a double merge, flat-line detector's first live
findings (**30 alerts = 3 episodes**), gold completeness matching the observed
per-day profile.

## Phase 4 — Corrections found by testing the design forward

1. **Lookback added** to the ingestion URL (`addDays(watermark, -35)`) after
   realising a forward-only watermark would permanently miss the EA's revisions.
2. **Watermark made data-derived** (max stored timestamp, written only after
   success) — a clock-based mark claims knowledge it doesn't have.
3. **Dedup ordering fixed** to prefer latest ingest (revisions supersede originals),
   with a test reproducing a revision — found because the docstring promised
   behaviour the code didn't implement.
4. **Partition date passed as a parameter** from orchestrator to notebook after the
   timezone mismatch (local-time trigger vs UTC-stamped folder). The quick fix
   (shift the schedule) was rejected because it silently breaks at the October
   clock change.

## Costs

Entire build: **under £10** (mostly absorbed by trial credit). Guardrails: budget
alert, serverless per-second billing, storage in pennies, $0.10/month for the alert
rule.

## Rebuild-from-zero checklist

Foundations table above → push repo, CI green → ADF per `adf/README.md` → Unity
Catalog credential + 4 external locations → notebooks per `notebooks/README.md` →
trigger + alert → verify with the four milestones in Phase 3.
