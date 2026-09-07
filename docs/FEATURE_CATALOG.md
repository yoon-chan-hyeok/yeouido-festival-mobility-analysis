# Feature Catalog

`data/public/actual_hourly_feature_table.csv`는 실제 자료를 시간대별로 결합한 공개용 분석 패널입니다.

| Feature group | Columns | Meaning |
|---|---|---|
| Time | `hour`, `is_event_window` | 시간대와 18~23시 분석 구간 여부 |
| OD demand | `event_departure_bus_od_cnts`, `normal_departure_bus_od_cnts`, `departure_bus_od_cnts_diff` | 여의도 출발 버스 추정 통행량 |
| OD duration | `event_departure_bus_avg_duration_min`, `normal_departure_bus_avg_duration_min`, `departure_bus_duration_diff_min` | `od_cnts` 가중평균 이동시간 |
| Stay population | `event_stay_cnts`, `normal_stay_cnts`, `stay_cnts_diff` | 여의동 시간대별 체류인구 관측치 합계 |
| Transit demand | `event_bus_boardings_proxy`, `event_subway_boardings_proxy` and normal/difference fields | 선정한 정류장·역의 교통카드 거래내역 기반 승차 집계 |
| Bus supply | `event_tpss_stop_count`, `normal_tpss_stop_count`, `tpss_stop_count_diff` | 여의도 GIS 정류장 ID의 정차횟수 합계 |
| Stress | `event_boardings_per_stop_count`, `normal_boardings_per_stop_count`, `demand_supply_stress_index` | 승차 관측치와 정차횟수로 만든 처리 부담 지표 |

## 사용 시 주의

- 소스별 정상 토요일 날짜 구성이 다릅니다.
- 승차 관측치와 OD 통행량은 자료 생성 방식과 모집단이 다릅니다.
- 승차 건수는 전체 행사 방문객이나 고유 이용자 수와 다릅니다. 제공기관의 거래내역 집계 정의는 [데이터 출처](DATA_PROVENANCE.md)에서 확인할 수 있습니다.
- 24개 시간대만으로 학습 성능을 주장하지 않습니다.
- 결측 이동시간은 해당 시간대 OD 통행량이 없거나 유효 이동시간을 계산할 수 없는 경우입니다.
