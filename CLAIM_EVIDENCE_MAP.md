# Claim-Evidence Map

| Claim | Status | Evidence file | Recalculation code | Important caveat |
|---|---|---|---|---|
| Event and control dates are the same weekday | verified | `config.json`, `release_validation.json` | `validate_release.py` | 2023-09-30 is sensitivity-only because of the holiday period |
| Yeouido departure bus travel time increased during 18-23 | verified descriptive result | `actual_od_event_vs_saturday.csv` | `load_od_panel`, `compare_od` | descriptive comparison, not causal effect; waiting time is not separately observed |
| Event-window bus boarding observations increased | verified descriptive result | `actual_bus_boarding_event_vs_saturday.csv` | `load_bus_panel`, `compare_sum` | one-time-card observations; exact-name Yeouido GIS scope |
| Event-window subway boarding observations increased | verified descriptive result | `actual_subway_boarding_event_vs_saturday.csv` | `load_subway_panel`, `compare_sum` | configured four-station scope; one-time-card observations |
| Event-window TPSS stop counts decreased | verified descriptive result | `actual_tpss_event_vs_saturday.csv` | `load_tpss_panel`, `compare_sum` | exact GIS stop-ID subset; cause is not identified |
| Event-window stay population was higher | verified descriptive result | `actual_stay_event_vs_saturday.csv` | `load_stay_panel`, `compare_sum` | hourly observation sum, not unique people |
| Demand increased while stop-count supply decreased | supported as concurrent descriptive pattern | `actual_demand_supply_change.svg`, bus/TPSS CSVs | `make_figures` | different source definitions; not a causal mechanism proof |
| Restoring stop counts to the normal-Saturday level would still leave event-window burden above normal | verified arithmetic stress test | `actual_supply_recovery_stress_test.csv`, `supply_recovery_stress_test.json` | `build_supply_recovery_scenario` | hypothetical index calculation, not bus-count optimization or observed policy effect |
| Gongdeok, Dangsan, and Noryangjin are proposed as external transfer hubs | operating hypothesis only | presentation concept summarized in `README.md` | none | hub optimality, fleet size, capacity, cost, and travel-time benefit are not validated |
| OD, stay, boarding proxies, and stop counts were combined into an hourly feature panel | verified artifact | `actual_hourly_feature_table.csv` | `build_hourly_feature_table` | source-specific control groups differ; descriptive feature engineering only |
| A defensible event-level predictive benchmark cannot yet be reported | verified data-readiness decision | `model_readiness.json`, `MODEL_SELECTION.md` | `inventory_local_source_dates`, `build_model_readiness_report` | the selected analysis panel has two dates; local files overlap for 14 calendar dates, but contain only one event Saturday and one normal Saturday |
| Road control, detours, or non-stop operations caused the TPSS decrease | not tested | none | none | no policy-operation dataset was joined |
| Seoul planned route detours, selected non-stop operations, concentrated bus dispatch, and additional subway service for the event | externally documented operating plan | `DATA_PROVENANCE.md` | none | policy plan, not proof of realized service or cause of the observed TPSS change |
| Shuttle hubs or additional dispatch counts are optimal | not tested | none | none | scenarios in old materials are outside this validated release |
| A monetary policy benefit was achieved | not tested | none | none | no observed post-policy outcome or confirmed cost calculation |
