# Release Manifest

## Included code

- `run_all.py`: full pipeline with local raw data
- `reproduce_public.py`: regenerate figures, stress test, and project page from included aggregates and summary
- `src/io_utils.py`: CSV, DBF, and shapefile readers
- `src/spatial.py`: Yeouido polygon and bus-stop extraction
- `src/pipeline.py`: source loading, joining, auditing, comparison, and SVG generation
- `src/portfolio_page.py`: shared HTML renderer for the public and raw-data pipelines
- `validate_release.py`: release consistency checks
- `tests/test_pipeline.py`: half-hour parser and scenario regression tests

## Included documentation

- `README.md`
- `docs/DATA_DICTIONARY.md`
- `docs/data_dictionary.csv`
- `docs/CORRECTIONS.md`
- `docs/METHODOLOGY.md`
- `docs/FEATURE_CATALOG.md`
- `docs/MODEL_SELECTION.md`
- `docs/DATA_PROVENANCE.md`
- `CLAIM_EVIDENCE_MAP.md`
- `RELEASE_MANIFEST.md`
- `NOTICE.md`, `LICENSE`
- `index.html`: generated static portfolio summary
- `.github/workflows/validate.yml`: public-data reproduction and release validation CI

## Included actual aggregate outputs

- `outputs/tables/actual_*.csv`
- `outputs/tables/join_audit.csv`
- `outputs/tables/join_exclusion_reasons.csv`
- `outputs/figures/actual_*.svg`
- `outputs/reports/actual_reanalysis_summary.json`
- `outputs/reports/raw_source_audit.json`
- `outputs/reports/supply_recovery_stress_test.json`
- `outputs/reports/model_readiness.json`
- `outputs/tables/actual_hourly_feature_table.csv`
- `outputs/tables/actual_supply_recovery_stress_test.csv`
- `data/public/actual_*.csv`

## Excluded

- Raw SKT OD and stay-population rows
- Raw bus/subway/TPSS rows
- Original notebook and backup notebook
- Old `seoul_new_data/outputs`
- PDFs, PPTX files, legacy HTML files, and unverified policy-scenario calculations
- Synthetic examples, local absolute paths, and personal identifiers

## Reproduction contract

`reproduce_public.py` uses the included `data/public` aggregates and `outputs/reports/actual_reanalysis_summary.json`. It requires no raw files or external Python packages. The full `run_all.py` pipeline expects the original workspace data one directory above the repository. A clean full rebuild is performed with `FORCE_REBUILD=1`. Both pipelines write outputs inside this repository.

Bus and subway boarding values come from transit-card transaction aggregates in the selected station scope. The provider's source definitions and the correction of an earlier fare-media description are documented in `docs/DATA_PROVENANCE.md` and `docs/CORRECTIONS.md`.

The supply-recovery stress test is generated from corrected bus and TPSS aggregates. It is included because its assumptions and formulas are explicit; legacy fleet-size, shuttle-capacity, cost, and benefit calculations remain excluded.
