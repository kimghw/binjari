"""소요시간 상한 필터 — 'N시간 이상 걸리는 KTX 제외' (2026-11-06 요청).

시간표 조회 API(`max_duration_min`)와 워처 후보 필터(`KTXA_MAX_DURATION_MIN`)가 같은 기준을 쓴다.
소요시간을 못 읽는 행은 오제외를 막기 위해 통과시킨다.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from ktx_watcher.korail import search


def cfg(**overrides):
    return SimpleNamespace(**({"ktxa_max_duration_min": 0} | overrides))


# ── 워처 (search.py) ────────────────────────────────────────────────────────

def test_duration_from_row_text():
    assert search._duration_minutes("09:00 KTX 101 서울 부산 11:45 23,700원") == 165
    assert search._duration_minutes("23:30 KTX 서울 부산 01:10") == 100       # 자정 넘김
    assert search._duration_minutes("09:00 KTX 서울 부산") is None            # 도착 시각 없음
    assert search._duration_minutes("") is None


def test_watcher_drops_rows_over_limit_only_when_set():
    long_row = {"depart_raw": "09:00 KTX 서울 부산 12:10"}     # 190분
    short_row = {"depart_raw": "09:00 KTX 서울 부산 11:30"}    # 150분
    assert search._within_max_duration(long_row, cfg(ktxa_max_duration_min=180)) is False
    assert search._within_max_duration(short_row, cfg(ktxa_max_duration_min=180)) is True
    assert search._within_max_duration(long_row, cfg(ktxa_max_duration_min=0)) is True     # 0 = 제한 없음
    assert search._within_max_duration(long_row, SimpleNamespace()) is True                # 키 없는 config
    assert search._within_max_duration({"depart_raw": "09:00 KTX"}, cfg(ktxa_max_duration_min=60)) is True  # 못 읽으면 통과


def test_config_accepts_blank_and_rejects_negative():
    from ktx_watcher.config import KTXAConfig
    base = {"KTXA_ORIGIN": "서울", "KTXA_DEST": "부산", "KTXA_DATE": "2026-11-07",
            "KTXA_TIMES": "09:00", "KTXA_MODE": "search", "KTXA_USER": "u", "KTXA_PASS": "p"}
    assert KTXAConfig.model_validate(base).ktxa_max_duration_min == 0
    assert KTXAConfig.model_validate(base | {"KTXA_MAX_DURATION_MIN": ""}).ktxa_max_duration_min == 0
    assert KTXAConfig.model_validate(base | {"KTXA_MAX_DURATION_MIN": "180"}).ktxa_max_duration_min == 180
    with pytest.raises(Exception):
        KTXAConfig.model_validate(base | {"KTXA_MAX_DURATION_MIN": "-1"})


# ── 시간표 조회 (web_server.py) ─────────────────────────────────────────────

ROWS = [
    {"train_type": "KTX", "train_no": "101", "depart": "09:00", "arrive": "11:30"},   # 150분
    {"train_type": "KTX", "train_no": "103", "depart": "09:30", "arrive": "12:50"},   # 200분
    {"train_type": "KTX", "train_no": "105", "depart": "10:00", "arrive": ""},        # 소요 미상 → 통과
]
NOW = datetime(2026, 11, 6, 8, 0)


def test_timetable_duration_minutes():
    import web_server as ws
    assert ws._duration_minutes(ROWS[0]) == 150
    assert ws._duration_minutes({"depart": "23:30", "arrive": "01:10"}) == 100
    assert ws._duration_minutes(ROWS[2]) is None


def test_timetable_filter_by_max_duration():
    import web_server as ws
    req = ws.SearchRequest(origin="서울", dest="부산", date="2026-11-07", earliest_hour=6, max_duration_min=180)
    assert [r["train_no"] for r in ws._filter_rows(ROWS, req, NOW)] == ["101", "105"]
    req_all = ws.SearchRequest(origin="서울", dest="부산", date="2026-11-07", earliest_hour=6)
    assert [r["train_no"] for r in ws._filter_rows(ROWS, req_all, NOW)] == ["101", "103", "105"]


def test_timetable_filter_keeps_hour_and_train_no_behaviour():
    import web_server as ws
    # latest_hour=10 → 10:00 정각까지 포함, 열차번호 앞 0 은 무시
    req = ws.SearchRequest(origin="서울", dest="부산", date="2026-11-07", earliest_hour=9, latest_hour=10, train_no="0103")
    assert [r["train_no"] for r in ws._filter_rows(ROWS, req, NOW)] == ["103"]
    # latest_hour=9 → 09:00 까지만 → 09:30 출발(103) 제외
    req2 = ws.SearchRequest(origin="서울", dest="부산", date="2026-11-07", earliest_hour=9, latest_hour=9)
    assert [r["train_no"] for r in ws._filter_rows(ROWS, req2, NOW)] == ["101"]
