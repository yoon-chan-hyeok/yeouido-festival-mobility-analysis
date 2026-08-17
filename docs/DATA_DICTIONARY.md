# Data Dictionary

## Source-level dictionary

| Source | Relative path/pattern | Observation unit | Time unit | Spatial unit | Primary key or join key | Corrected use |
|---|---|---|---|---|---|---|
| SKT OD | `../raw_data/od_*/od_YYYYMMDD_1.csv` | origin-destination, demographic, mode, purpose combination | date and start/end hour | administrative dong OD pair | `origin_hdong_cd`, `dest_hdong_cd`, `date`, `start_time`, `end_time`, `modal` plus demographic/purpose fields | Yeouido arrival/departure traffic and `od_cnts`-weighted duration |
| SKT stay population | `../raw_data/stay_*/stay_YYYYMMDD_1.csv` | dong, hour, demographic, purpose combination | hourly | administrative dong | `hdong_cd`, `date`, `time`, `gender`, `age`, `purpose` | Yeouido hourly stay-count sum |
| Administrative-code reference | `../데이터분석 분야_데이터정의서/KIKmix_20230701.csv` | administrative-code to legal-dong mapping row | reference date 2023-07-01 | nationwide dong | `행정동코드`, `법정동코드` | verify Yeouido code `1156054000` and Seoul scope |
| Bus 30-minute usage | `../seoul_new_data/서울시 버스 30분 이용통계/.../202310/TBDM_TRANSIT_STAT_BUS_YYYYMMDD.csv` | station and half-hour count row | 30 minutes | Seoul bus station | source `STATION_ID`, normalized `STATION_NM`; GIS area selection uses exact normalized name | event/normal boarding comparison; source is treated as one-time-card observation, not total ridership |
| Subway 30-minute usage | `../seoul_new_data/서울시 지하철 30분단위 이용통계/.../202310/TBDM_TRANSIT_STAT_SUBWAY_YYYYMMDD.csv` | line, station and half-hour count row | 30 minutes | Seoul subway station | `STATION_ID`, `LINE_NM`, normalized `STATION_NM` | four configured Yeouido station boarding comparison; one-time-card observation |
| TPSS stop operation | `../tpss_sta_route_hturn_202310/*.csv` | date, route, station row with hourly wide columns | hourly | bus stop-route | `기준_날짜`, `노선_ID`, `정류장_ID` | sum stop counts only for exact GIS stop-ID matches |
| Bus-stop GIS | `../seoul_new_data/B405.../2019/TB_E_BUSSTOP_2019.{shp,dbf}` | bus-stop point | static 2019 snapshot | point in EPSG:5186 | `STN_IDN`; name fallback is used only for area-level bus counts | point-in-polygon extraction and TPSS exact-ID scope |
| Administrative-dong GIS | `../seoul_new_data/서울시 2017 행정동 지역경계 shp/...epsg5186.{shp,dbf}` | administrative-dong polygon | static 2017 snapshot | polygon in EPSG:5186 | `adm_dr_cd`, `adm_dr_nm` | define Yeouido polygon and select bus stops |

## Derived fields

| Field | Formula | Unit | Caveat |
|---|---|---|---|
| `weighted_duration` | `od_duration_avg * od_cnts` | person-minutes proxy | source OD is estimated mobility data |
| `avg_duration` | `sum(weighted_duration) / sum(od_cnts)` | minutes | pooled weighted average, not mean of row means |
| `target_minus_normal` | event value - normal-Saturday mean | source unit | normal dates differ by source availability |
| `target_over_normal` | event value / normal-Saturday mean | ratio | blank when denominator is zero |
| `is_event_window` | hour in 18 through 23 | binary | analyst-defined analysis window |
| `event_boardings_per_stop_count` | event bus boarding proxy / event TPSS stop count | boarding-observation per stop-count | cross-source descriptive index, not passenger load per vehicle |
| `demand_supply_stress_index` | event boardings-per-stop-count / normal boardings-per-stop-count | ratio | normal burden equals 1; descriptive only |
| `restored_stop_count` | max(event stop count, normal stop count) | stop-count index | hypothetical normal-supply restore, not added bus count |
| `stress_index_after_normal_supply_restore` | event demand / restored supply / normal load | ratio | stress-test output, not observed policy effect |

## Date groups

| Group | Dates | Use |
|---|---|---|
| Event | 2023-10-07 | fully held-out event Saturday |
| Primary OD/stay controls | 2023-09-02, 09-09, 09-16, 09-23, 10-14 | normal Saturdays excluding Chuseok period |
| Sensitivity OD/stay controls | primary controls plus 2023-09-30 | holiday-period robustness only |
| October transit controls | 2023-10-14, 10-21, 10-28 | bus, subway, TPSS normal Saturdays |
| Strict common control | 2023-10-14 | single-date cross-source check |

## Join policy

- No fuzzy matching is used in the corrected core pipeline.
- Bus usage rows are selected by exact normalized station name against GIS names. Duplicate GIS names remain valid for Yeouido-area totals but are not assigned to an arbitrary coordinate.
- TPSS uses exact station-ID equality.
- Missing and ambiguous matches remain excluded and are reported in `outputs/tables/join_audit.csv` and `join_exclusion_reasons.csv`.
- The 2017 dong boundary and 2019 bus-stop snapshot are older than the 2023 transport observations. This temporal mismatch is retained as a limitation.

## Public derived tables

| File | Unit | Purpose |
|---|---|---|
| `actual_hourly_feature_table.csv` | one row per hour | combine OD, stay population, transit boarding proxies, TPSS, and stress features |
| `actual_supply_recovery_stress_test.csv` | one row per hour | compare observed event burden with a normal-stop-count restore scenario |
| `actual_*_event_vs_saturday.csv` | one row per hour and source scope | event-versus-control comparisons used in figures and summaries |
