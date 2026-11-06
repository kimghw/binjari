"""KTXA_RESERVE_SAME_TRAIN: 확보 목표 2건 이상을 모두 같은 열차로 잡는 모드."""

import pytest
from pydantic import ValidationError

from ktx_watcher import main as watcher_main
from ktx_watcher.config import KTXAConfig

BASE = {
    "KTXA_ORIGIN": "서울", "KTXA_DEST": "부산", "KTXA_DATE": "2026-11-07",
    "KTXA_TIMES": "09:00,10:00", "KTXA_PASSENGERS": "1",
    "KTXA_MODE": "reserve", "KTXA_PAYMENT_MODE": "false", "TEAMS_ENABLED": "false",
    "KTXA_USER": "user", "KTXA_PASS": "pass",
}


def make_config(**over):
    return KTXAConfig.model_validate({**BASE, **over})


def cand(depart):
    return {"origin": "서울", "dest": "부산", "date": "2026-11-07", "depart": depart,
            "seat_class": "일반실", "status": "예약가능", "status_kind": "reserve"}


@pytest.fixture(autouse=True)
def reset_state():
    watcher_main._RESERVED_DEPARTS.clear()
    watcher_main._CAND_NOTIFIED.clear()
    watcher_main._RESERVED_COUNT = 0
    watcher_main._SAME_TRAIN_DEPART = None
    yield


@pytest.fixture
def attempts(monkeypatch):
    """perform_search 결과를 테스트가 넣고, attempt_reservation 은 항상 성공한 것으로."""
    state = {"rows": [], "attempted": []}
    monkeypatch.setattr(watcher_main.search_mod, "perform_search", lambda client, config: list(state["rows"]))
    monkeypatch.setattr(watcher_main.reserve_mod, "attempt_reservation",
                        lambda client, config, best: state["attempted"].append(best["depart"]))
    return state


def test_same_train_requires_limit_of_two_or_more():
    with pytest.raises(ValidationError, match="KTXA_RESERVE_LIMIT"):
        make_config(KTXA_RESERVE_LIMIT="1", KTXA_RESERVE_SAME_TRAIN="true")
    with pytest.raises(ValidationError, match="KTXA_RESERVE_LIMIT"):
        make_config(KTXA_RESERVE_LIMIT="0", KTXA_RESERVE_SAME_TRAIN="true")
    assert make_config(KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true").ktxa_reserve_same_train is True
    assert make_config(KTXA_RESERVE_LIMIT="1").ktxa_reserve_same_train is False


def test_default_mode_moves_on_to_a_different_train(attempts):
    config = make_config(KTXA_RESERVE_LIMIT="2")
    attempts["rows"] = [cand("09:00"), cand("10:00")]
    assert watcher_main.run_once(None, config) is False      # 1/2 확보
    assert watcher_main.run_once(None, config) is True       # 2/2 — 다른 열차로
    assert attempts["attempted"] == ["09:00", "10:00"]


def test_same_train_mode_keeps_targeting_the_first_train(attempts):
    config = make_config(KTXA_RESERVE_LIMIT="2", KTXA_RESERVE_SAME_TRAIN="true", KTXA_TIMES="09:00")
    attempts["rows"] = [cand("09:00"), cand("10:00")]
    assert watcher_main.run_once(None, config) is False      # 첫 건: 아무 열차나 → 09:00
    assert watcher_main._SAME_TRAIN_DEPART == "09:00"

    attempts["rows"] = [cand("10:00")]                       # 다른 열차만 비어 있으면 건드리지 않는다
    assert watcher_main.run_once(None, config) is False
    assert attempts["attempted"] == ["09:00"]

    attempts["rows"] = [cand("10:00"), cand("09:00")]        # 같은 열차에 자리가 나면 그것만 잡는다
    assert watcher_main.run_once(None, config) is True       # 2/2 — 감시 종료
    assert attempts["attempted"] == ["09:00", "09:00"]
