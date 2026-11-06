"""결과 목록 렌더 대기 + 빈 목록 새로고침 재조회 (2026-11-06 '0행 → 오탐 중단' 대응).

reload·열차종류 탭·가드 재조회 직후 React 가 목록을 그리기 전에 읽으면 0행이 나온다.
행이 뜰 때까지 기다렸다 읽고, 그래도 비면(차단 안내·'열차 없음' 마커 없음) 새로고침 1회.
대기 중 뒤늦게 뜬 차단 안내는 `_await_result` 가 기록·분류한다 (Codex 교차 검토 반영).
"""

from datetime import date, time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ktx_watcher.korail import GuardBlocked, SearchResultUnavailable
from ktx_watcher.korail import search


def config(**overrides):
    values = {
        "ktxa_origin": "서울", "ktxa_dest": "부산", "ktxa_date": date(2026, 11, 7),
        "ktxa_times": [time(9)], "ktxa_tolerance_min": 30,
        "ktxa_time_window": (time(9), time(13)),
        "ktxa_include_srt": False, "ktxa_train_type": "KTX",
        "ktxa_seat_class": "일반실", "ktxa_seated_only": True,
        "passenger_counts": lambda: {"어른": 1, "경로": 1},
    }
    return SimpleNamespace(**(values | overrides))


def valid_state():
    return {"origin": "서울", "dest": "부산", "date": "2026-11-07(토) 09:00",
            "passengers": "총 2명"}


# 수서 출발 행: include_srt=false 면 경로 불일치로 후보에서 빠진다 (좌석 파싱까지 안 감).
ROW = {"origin": "수서", "dest": "부산", "depart": "09:00", "depart_time": time(9),
       "train_name": "KTX", "depart_raw": "09:00 KTX", "_row_index": 0,
       "general_status": "", "first_status": ""}


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(search, "human_pause", lambda *args: None)
    monkeypatch.setattr(search, "_query_state", lambda page: valid_state())
    monkeypatch.setattr(search, "_check_guard", lambda *args: False)   # 테스트별로 덮어쓴다


# ── _wait_result_list / _await_result ──────────────────────────────────────

def test_wait_result_list_reports_dom_state():
    page = Mock()
    page.wait_for_function.return_value.json_value.return_value = "rows"
    assert search._wait_result_list(page, where="t") == "rows"
    page.wait_for_function.return_value.json_value.return_value = "garbage"
    assert search._wait_result_list(page, where="t") is None
    page.wait_for_function.side_effect = search.PWTimeoutError("timeout")
    assert search._wait_result_list(page, where="t") is None


def test_wait_result_list_does_not_mask_browser_loss_as_timeout():
    page = Mock()
    page.wait_for_function.side_effect = RuntimeError("Target page, context or browser has been closed")
    with pytest.raises(RuntimeError):
        search._wait_result_list(page, where="t")


def test_await_result_classifies_guard_that_appeared_during_wait(monkeypatch):
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: None)
    stages = []
    monkeypatch.setattr(search, "_check_guard", lambda page, stage: stages.append(stage) or True)
    assert search._await_result(Mock(), stage="t") == (None, True)
    assert stages == ["t"]


def test_await_result_skips_guard_check_when_rows_are_present(monkeypatch):
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: "rows")
    monkeypatch.setattr(search, "_check_guard", Mock(side_effect=AssertionError("must not be called")))
    assert search._await_result(Mock(), stage="t") == ("rows", False)


# ── _settle_rows ───────────────────────────────────────────────────────────

def test_settle_rows_returns_non_empty_rows_untouched(monkeypatch):
    wait = Mock()
    monkeypatch.setattr(search, "_wait_result_list", wait)
    rows = [ROW]
    assert search._settle_rows(Mock(), config(), rows, where="t") is rows
    wait.assert_not_called()


def test_settle_rows_rereads_once_list_renders(monkeypatch):
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: "rows")
    monkeypatch.setattr(search, "_read_rows", lambda page: [ROW])
    refresh = Mock()
    monkeypatch.setattr(search, "_requery_when_empty", refresh)
    assert search._settle_rows(Mock(), config(), [], where="t") == [ROW]
    refresh.assert_not_called()


def test_settle_rows_keeps_real_no_data_marker(monkeypatch):
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: "empty")
    monkeypatch.setattr(search, "_read_rows", lambda page: [])
    monkeypatch.setattr(search, "_empty_marker_visible", lambda page: True)
    refresh = Mock()
    monkeypatch.setattr(search, "_requery_when_empty", refresh)
    assert search._settle_rows(Mock(), config(), [], where="t") == []
    refresh.assert_not_called()


def test_settle_rows_refreshes_when_list_stays_empty(monkeypatch):
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: None)
    monkeypatch.setattr(search, "_read_rows", lambda page: [])
    monkeypatch.setattr(search, "_empty_marker_visible", lambda page: False)
    refresh = Mock(return_value=[ROW])
    monkeypatch.setattr(search, "_requery_when_empty", refresh)
    budget = {"refresh": 1}
    assert search._settle_rows(Mock(), config(), [], where="t", budget=budget) == [ROW]
    refresh.assert_called_once()
    assert budget == {"refresh": 0}


def test_settle_rows_respects_exhausted_refresh_budget(monkeypatch):
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: None)
    monkeypatch.setattr(search, "_read_rows", lambda page: [])
    monkeypatch.setattr(search, "_empty_marker_visible", lambda page: False)
    refresh = Mock()
    monkeypatch.setattr(search, "_requery_when_empty", refresh)
    assert search._settle_rows(Mock(), config(), [], where="t", budget={"refresh": 0}) == []
    refresh.assert_not_called()


def test_settle_rows_routes_guard_to_guard_retry(monkeypatch):
    """대기 결과가 모달이든 시간 초과든, 가드로 분류되면 가드 재조회로 간다."""
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: None)
    monkeypatch.setattr(search, "_check_guard", lambda *args: True)
    guard_retry = Mock(return_value=[ROW])
    monkeypatch.setattr(search, "_requery_after_guard", guard_retry)
    assert search._settle_rows(Mock(), config(), [], where="t") == [ROW]
    guard_retry.assert_called_once()


def test_settle_rows_closes_notice_modal_then_classifies_second_modal(monkeypatch):
    states = iter(["modal", "modal"])
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: next(states))
    guards = iter([False, True])            # 첫 모달은 공지, 닫은 뒤 뜬 모달은 가드
    monkeypatch.setattr(search, "_check_guard", lambda page, stage: next(guards))
    dismiss = Mock(return_value=True)
    monkeypatch.setattr(search, "dismiss_notice_modal", dismiss)
    guard_retry = Mock(return_value=[ROW])
    monkeypatch.setattr(search, "_requery_after_guard", guard_retry)
    assert search._settle_rows(Mock(), config(), [], where="t") == [ROW]
    dismiss.assert_called_once()
    guard_retry.assert_called_once()


# ── _requery_when_empty ────────────────────────────────────────────────────

def test_empty_refresh_reloads_and_reads_after_render(monkeypatch):
    page = Mock()
    waits = []
    monkeypatch.setattr(search, "_wait_result_list",
                        lambda page, **kw: waits.append(kw["where"]) or "rows")
    monkeypatch.setattr(search, "_read_rows", lambda page: [ROW])
    assert search._requery_when_empty(page, config(), where="t") == [ROW]
    page.reload.assert_called_once()
    assert waits == ["t/empty-retry"]


def test_empty_refresh_hands_guard_after_reload_to_guard_retry(monkeypatch):
    page = Mock()
    monkeypatch.setattr(search, "_check_guard", lambda *args: True)
    guard_retry = Mock(return_value=[ROW])
    monkeypatch.setattr(search, "_requery_after_guard", guard_retry)
    assert search._requery_when_empty(page, config(), where="t") == [ROW]
    page.reload.assert_called_once()
    guard_retry.assert_called_once()


def test_empty_refresh_hands_late_guard_during_wait_to_guard_retry(monkeypatch):
    page = Mock()
    guards = iter([False, True])            # reload 직후엔 없고, 대기 중 뜸
    monkeypatch.setattr(search, "_check_guard", lambda page, stage: next(guards))
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: None)
    guard_retry = Mock(return_value=[ROW])
    monkeypatch.setattr(search, "_requery_after_guard", guard_retry)
    assert search._requery_when_empty(page, config(), where="t") == [ROW]
    guard_retry.assert_called_once()


# ── _requery_after_guard ───────────────────────────────────────────────────

def _guard_retry_page():
    page = Mock()
    page.locator.return_value.filter.return_value.first.is_visible.return_value = True
    return page


def test_guard_retry_waits_for_render_and_tries_again_when_empty(monkeypatch):
    monkeypatch.setattr(search, "human_click", Mock())
    waits = []
    monkeypatch.setattr(search, "_wait_result_list",
                        lambda page, **kw: waits.append(kw["where"]))
    reads = iter([[], [ROW]])
    monkeypatch.setattr(search, "_read_rows", lambda page: next(reads))
    assert search._requery_after_guard(_guard_retry_page(), config=config(), where="t") == [ROW]
    assert waits == ["t/retry-1", "t/retry-2"]


def test_guard_retry_still_reports_empty_list_after_all_attempts(monkeypatch):
    monkeypatch.setattr(search, "human_click", Mock())
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: None)
    monkeypatch.setattr(search, "_read_rows", lambda page: [])
    with pytest.raises(SearchResultUnavailable):
        search._requery_after_guard(_guard_retry_page(), config=config(), where="t")


def test_guard_retry_counts_guard_that_appeared_during_wait(monkeypatch):
    """즉시 감지엔 없다가 대기 중 뜬 가드도 '반복 차단' 으로 센다 — 안내 없는 빈 목록으로 보고하지 않는다."""
    monkeypatch.setattr(search, "human_click", Mock())
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: "modal")
    calls = []

    def check_guard(page, stage):
        calls.append(stage)
        return stage.startswith("t/retry-")      # 즉시 감지(t/retry-N 이 아닌 stage)는 False

    monkeypatch.setattr(search, "_check_guard", check_guard)
    monkeypatch.setattr(search, "_read_rows", Mock(side_effect=AssertionError("must not read")))
    with pytest.raises(GuardBlocked):
        search._requery_after_guard(_guard_retry_page(), config=config(), where="t")
    assert [c for c in calls if c.startswith("t/retry-")] == ["t/retry-1", "t/retry-2"]


# ── perform_search ─────────────────────────────────────────────────────────

def _result_page_client(cfg):
    page = Mock(url="https://www.korail.com/ticket/search/list")
    client = Mock()
    client.main_page.return_value = page
    client._verified_query = search._query_signature(cfg)
    return page, client


def _stub_perform_search(monkeypatch, *, reads, click_tab, refresh):
    monkeypatch.setattr(search, "_ROW_BASELINE", {})
    monkeypatch.setattr(search, "_set_passengers", lambda page, config: None)
    monkeypatch.setattr(search, "_ensure_srt_on_result", lambda page, config: False)
    monkeypatch.setattr(search, "_click_train_type_tab", click_tab)
    monkeypatch.setattr(search, "_wait_result_list", lambda page, **kw: None)
    monkeypatch.setattr(search, "_empty_marker_visible", lambda page: False)
    monkeypatch.setattr(search, "_requery_when_empty", refresh)
    monkeypatch.setattr(search, "_read_rows", lambda page: next(reads, []))
    monkeypatch.setattr(search, "_expand_more_until", lambda page, config, raw: raw)


def test_train_type_tab_is_reapplied_after_empty_refresh(monkeypatch):
    """탭 클릭 직후 0행 → 새로고침 재조회로 탭이 '전체' 로 돌아가면 KTX 탭을 다시 누른다."""
    cfg = config()
    page, client = _result_page_client(cfg)
    tab = {"active": False, "clicks": 0}

    def click_tab(page, train_type):
        if tab["active"]:
            return False
        tab["active"] = True
        tab["clicks"] += 1
        return True

    def refresh(page, config, *, where):
        tab["active"] = False          # reload 로 탭이 기본값(전체)으로 복귀
        search._REQUERY_COUNT += 1     # 실제 _requery_when_empty 가 올리는 카운터
        return [ROW, ROW]

    # reload 직후 10행 / 탭 직후 0행 / 대기 후에도 0행 / 탭 재적용 후 1행
    _stub_perform_search(monkeypatch, reads=iter([[ROW, ROW], [], [], [ROW]]),
                         click_tab=click_tab, refresh=refresh)
    assert search.perform_search(client, cfg) == []   # 수서 출발 행 → 경로 불일치, 후보 없음
    assert tab["clicks"] == 2
    page.reload.assert_called_once()                  # 이터레이션 시작 reload 1회만 (refresh 는 stub)


def test_train_type_tab_is_clicked_once_without_refresh(monkeypatch):
    """재조회가 없으면 탭 클릭 함수가 늘 True 여도 한 번만 누른다 (18:22 실측 3연속 클릭 회귀 방지)."""
    cfg = config()
    page, client = _result_page_client(cfg)
    clicks = []
    refresh = Mock()
    _stub_perform_search(monkeypatch, reads=iter([[ROW, ROW], [ROW]]),
                         click_tab=lambda page, train_type: clicks.append(train_type) or True,
                         refresh=refresh)
    assert search.perform_search(client, cfg) == []
    assert clicks == ["KTX"]
    refresh.assert_not_called()


def test_perform_search_refreshes_at_most_once_per_call(monkeypatch):
    """탭 뒤에도 계속 0행이면 새로고침은 한 번만 하고 SearchResultUnavailable 로 보고한다."""
    cfg = config()
    page, client = _result_page_client(cfg)
    clicks = []

    def refresh(page, config, *, where):
        search._REQUERY_COUNT += 1
        return [ROW, ROW]

    refresh = Mock(side_effect=refresh)
    _stub_perform_search(monkeypatch, reads=iter([[ROW, ROW]]),       # 그 뒤로는 전부 0행
                         click_tab=lambda page, train_type: clicks.append(train_type) or True,
                         refresh=refresh)
    with pytest.raises(SearchResultUnavailable):
        search.perform_search(client, cfg)
    assert refresh.call_count == 1
    assert clicks == ["KTX", "KTX"]       # 새로고침 뒤 한 번 재적용, 그 뒤 예산 소진으로 종료
