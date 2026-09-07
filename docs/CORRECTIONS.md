# Corrections and release checks

## Corrected

1. Weekday mismatch
   - Previous comparison dates were Sundays while the event was Saturday.
   - The release config contains only Saturdays for control groups.
   - `validate_release.py` recalculates weekdays and fails if a configured normal date is not Saturday.

2. Holiday contamination
   - 2023-09-30 is separated from the primary control group.
   - A second sensitivity table includes it so the impact of this decision is visible.

3. Station matching
   - Arbitrary rank/cycle matching of duplicate station names is not used.
   - Duplicate names are restricted to area aggregates; coordinate-level attribution is excluded.
   - TPSS uses exact station IDs only.

4. Transit-card source definition, corrected on 2026-09-07
   - The previous release incorrectly restricted both bus and subway aggregates to single-use cards after misreading the parent dataset title.
   - The provider describes the 30-minute datasets as aggregates of transit transaction records. Its parent dataset lists general transit transactions and subway single-use-ticket records separately.
   - Documentation now describes boarding counts from transit-card transactions within the selected station scope. These counts are not unique riders or total festival visitors.
   - This correction changes the source description, not the data, calculations, or reported values. Official links are in `DATA_PROVENANCE.md`.

5. Stay-population wording
   - Sums across hours are labeled time-indexed observation sums, not unique visitors.

6. Legacy scenario separation
   - Presentation totals built from older station scopes are not reused as corrected results.
   - Shuttle vehicle counts, rotations, costs, and time-benefit assumptions are not included as measured outcomes.
   - The only new scenario is a transparent stop-count stress test generated from the corrected hourly aggregates.

7. Half-hour parsing
   - The first release candidate reused the 0-to-23 hour parser for the `HALF_HOUR` field.
   - This excluded every `HALF_HOUR=30` bus and subway row.
   - A dedicated parser now accepts both 0 and 30, and a unit test protects the two 30-minute bins.

8. Cross-source date availability
   - The first public release described the two selected comparison dates as if they were the only locally available cross-source dates.
   - A filename-level inventory found a 14-day common window from 2023-10-02 through 2023-10-15.
   - The model-readiness report now separates the two loaded comparison dates from the 14 locally available dates.
   - Predictive scores remain withheld because the common window contains one event Saturday and one normal Saturday, not because only two calendar dates exist.

## Not modified

The original notebook, PDFs, presentation files, old scripts, and `seoul_new_data/outputs` remain untouched. They may still contain older comparison dates, bbox stop lists, or policy scenarios. They are not part of this release candidate and must not be uploaded as validated results.

## Candidate-folder scan

`validate_release.py` checks the candidate README, config, public-data prefixes, required files, and output separation. The generated report is `outputs/reports/release_validation.json`.
