"""확보 기록 영구저장 (2026-11-07).

1건 결제 후 워처가 재시작(사람 또는 웹서버 AI 복구)되면 메모리 카운터가 0 으로 돌아가 초과 구매하던 문제.
같은 여정(날짜·구간·인원 구성)이면 파일에서 이어서 세고, 목표를 이미 채웠으면 감시를 시작하지 않는다.
"""

import json

import pytest

from ktx_watcher import main as watcher_main
from ktx_watcher.config import KTXAConfig

BASE = {
    "KTXA_ORIGIN": "서울", "KTXA_DEST": "부산", "KTXA_DATE": "2026-11-21",
    "KTXA_TIMES": "09:00", "KTXA_PASSENGERS": "2", "KTXA_PASSENGER_TYPE": "어른:1,어린이:1",
    "KTXA_MODE": "reserve", "KTXA_PAYMENT_MODE": "false", "TEAMS_ENABLED": "false",
    "KTXA_USER": "user", "KTXA_PASS": "pass",
}


def make_config(**over):
    return KTXAConfig.model_validate({**BASE, **over})


def reset_mem():
    """재시작 흉내: 메모리 상태만 비운다 (파일은 그대로)."""
    watcher_main._RESERVED_DEPARTS.clear()
    watcher_main._RESERVED_COUNT = 0
    watcher_main._SAME_TRAIN_DEPART = None


@pytest.fixture(autouse=True)
def _clean():
    reset_mem()
    yield
    reset_mem()


def test_mark_reserved_persists_and_restart_continues():
    cfg = make_config(KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true")
    assert watcher_main._mark_reserved(cfg, "13:13", None) is False     # 1/2
    saved = json.loads(watcher_main._RESERVED_STATE_PATH.read_text(encoding="utf-8"))
    assert saved["count"] == 1 and saved["same_train_depart"] == "13:13"

    reset_mem()                                                         # 워처 재시작
    watcher_main._load_reserved_state(cfg)
    assert watcher_main._RESERVED_COUNT == 1
    assert watcher_main._SAME_TRAIN_DEPART == "13:13"
    assert watcher_main._goal_already_met(cfg) is False

    assert watcher_main._mark_reserved(cfg, "13:13", None) is True      # 2/2 — 종료
    reset_mem()
    watcher_main._load_reserved_state(cfg)
    assert watcher_main._goal_already_met(cfg) is True                  # 또 재시작해도 시작 안 함


def test_different_trip_starts_fresh():
    cfg = make_config(KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true")
    watcher_main._mark_reserved(cfg, "13:13", None)
    for other in (
        make_config(KTXA_DATE="2026-11-28", KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true"),
        make_config(KTXA_DEST="대전", KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true"),
        make_config(KTXA_PASSENGERS="1", KTXA_PASSENGER_TYPE="어른", KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true"),
    ):
        reset_mem()
        watcher_main._load_reserved_state(other)
        assert watcher_main._RESERVED_COUNT == 0 and not watcher_main._RESERVED_DEPARTS


def test_raising_limit_continues_from_saved_count():
    cfg2 = make_config(KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true")
    watcher_main._mark_reserved(cfg2, "13:13", None)
    watcher_main._mark_reserved(cfg2, "13:13", None)
    cfg4 = make_config(KTXA_RESERVE_LIMIT="4", KTXA_RESERVE_SAME_TRAIN="true")
    reset_mem()
    watcher_main._load_reserved_state(cfg4)
    assert watcher_main._reserve_goal(cfg4) == (2, 4)
    assert watcher_main._goal_already_met(cfg4) is False


def test_default_mode_counts_distinct_trains():
    cfg = make_config(KTXA_RESERVE_LIMIT="2", KTXA_TIMES="09:00,10:00")
    watcher_main._mark_reserved(cfg, "09:00", None)
    reset_mem()
    watcher_main._load_reserved_state(cfg)
    assert watcher_main._reserve_goal(cfg) == (1, 2)
    assert watcher_main._mark_reserved(cfg, "10:00", None) is True
    assert watcher_main._goal_already_met(cfg) is True


def test_missing_or_broken_file_is_ignored():
    cfg = make_config(KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true")
    watcher_main._load_reserved_state(cfg)                               # 파일 없음
    assert watcher_main._RESERVED_COUNT == 0
    watcher_main._RESERVED_STATE_PATH.write_text("{not json", encoding="utf-8")
    watcher_main._load_reserved_state(cfg)
    assert watcher_main._RESERVED_COUNT == 0


# ── 웹서버: 상태 노출 + 초기화 API ──────────────────────────────────────────

def test_server_exposes_and_resets_reserved_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import web_server as ws
    path = tmp_path / "reserved_state.json"
    monkeypatch.setattr(ws, "RESERVED_STATE_PATH", path)
    monkeypatch.setattr(ws, "_watcher_running", lambda: False)
    client = TestClient(ws.app)

    assert client.get("/api/watcher/status").json()["reserved"] is None
    path.write_text(json.dumps({"signature": "x", "count": 1, "departs": ["13:13"]}), encoding="utf-8")
    assert client.get("/api/watcher/status").json()["reserved"]["count"] == 1

    r = client.post("/api/watcher/reserved/reset")
    assert r.status_code == 200 and r.json() == {"ok": True, "existed": True}
    assert not path.exists()
    assert client.post("/api/watcher/reserved/reset").json() == {"ok": True, "existed": False}

    monkeypatch.setattr(ws, "_watcher_running", lambda: True)
    assert client.post("/api/watcher/reserved/reset").status_code == 409
