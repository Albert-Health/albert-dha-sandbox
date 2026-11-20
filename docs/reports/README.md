# Phase 1 end-of-day reports (C1 / C2)

Reports for the medical team: the live end-of-day reports as standalone HTML, the same page with its data built in. Each one follows the medical team's
C1 / C2 checklist: can the scores run, Data Completeness, Framework Match, data quality, the C1–C2 selection effect,
sensitivity in known positives, and process KPIs.

| Report | Cohort | Source run |
|---|---|---|
| [C1_end_of_day_report.html](C1_end_of_day_report.html) | C1, complete-case known positives | VM `run all`, 20 Nov 2026 10:51 UTC, bundle 72efc39be6ba, ingest 1.4.2 |
| [C2_end_of_day_report.html](C2_end_of_day_report.html) | C2, random sample of known positives | same run |

- **Open in a browser:** GitHub shows an `.html` file as source, so download the file (or clone the repo) and open it.
  Charts load d3 from cdnjs; offline, text and tables still show.
- Every number comes from the enclave's COPY block in [`logs/enclave/2026-11-20.log`](../../logs/enclave/2026-11-20.log).
  The tables' data is in [`data/`](data/) (one JSON per report).
- Aggregates only. Counts under 10 show as "<10". A rate is hidden when its count, or the rest of its group, is under
  10, and so is a count that would give that back ("all but <10").
- Status, note and "handling" columns are the project team's reading of the numbers, not pipeline output.
- Open decisions referred to as D5, D6, D7, D29–D36 are listed in [`docs/gap.md`](../gap.md) §2 and in the Phase 1
  Decision Pack.
- These files are exported from the live Albert Health reports and updated in git when the reports change.
