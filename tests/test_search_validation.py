from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ktx_watcher.korail import (
    GuardBlocked, QueryConditionMismatch, SearchResultUnavailable, SiteLayoutChanged,
)
from ktx_watcher.korail import search
from ktx_watcher.browser import sync_playwright


def config(**overrides):
    values = {
        "ktxa_origin": "서울", "ktxa_dest": "부산", "ktxa_date": date(2026, 11, 7),
        "ktxa_times": [time(9)], "ktxa_tolerance_min": 30,
        "ktxa_time_window": (time(9), time(13)),
        "ktxa_include_srt": False,
        "passenger_counts": lambda: {"어른": 1, "경로": 1},
    }
    return SimpleNamespace(**(values | overrides))


@pytest.mark.parametrize("hour,minute,expected", [
    (8, 59, False), (9, 0, True), (9, 31, True), (10, 0, True),
    (12, 30, True), (13, 0, True), (13, 1, False),
])
def test_explicit_window_covers_entire_interval(hour, minute, expected):
    assert search._is_candidate_time(time(hour, minute), config()) is expected


@pytest.mark.parametrize("hour,minute,expected", [
    (8, 29, False), (8, 30, True), (9, 0, True), (9, 30, True), (9, 31, False),
])
def test_without_window_uses_time_tolerance(hour, minute, expected):
    cfg = config(ktxa_time_window=None)
    assert search._is_candidate_time(time(hour, minute), cfg) is expected


@pytest.mark.parametrize("overrides,expected", [
    ({"ktxa_time_window": (time(10, 15), time(13))}, 10),
    ({"ktxa_time_window": None}, 8),
    ({"ktxa_time_window": None, "ktxa_times": [time(14), time(9, 15)]}, 8),
    ({"ktxa_time_window": None, "ktxa_times": [time(0, 10)]}, 0),
    ({"ktxa_time_window": None, "ktxa_times": []}, 0),
])
def test_search_start_hour_includes_earliest_allowed_departure(overrides, expected):
    assert search._search_start_hour(config(**overrides)) == expected


def valid_state():
    return {"origin": "서울", "dest": "부산", "date": "2026-11-07(토) 09:00",
            "passengers": "총 2명"}


def test_matching_conditions_are_accepted():
    assert search._condition_errors(valid_state(), config()) == []


@pytest.mark.parametrize("updates,error_key", [
    ({"origin": "대전"}, "origin"),
    ({"dest": "대구"}, "dest"),
    ({"date": "2026-11-08(일) 09:00"}, "date"),
    ({"date": "2026-11-07(토) 00:00"}, "hour"),
    ({"date": "2026-11-07(토) 09:30"}, "hour"),
    ({"passengers": "총 1명"}, "passengers"),
    ({"passengers": None}, "passengers"),
])
def test_wrong_or_unreadable_conditions_are_rejected(updates, error_key):
    errors = search._condition_errors(valid_state() | updates, config())
    assert any(error.startswith(error_key + ":") for error in errors)


def test_empty_rows_are_distinct_from_dom_parse_error(monkeypatch):
    monkeypatch.setattr(search, "_parse_result_rows", lambda page: [])
    assert search._read_rows(object()) == []
    original = ValueError("unexpected result structure")
    monkeypatch.setattr(search, "_parse_result_rows", Mock(side_effect=original))
    with pytest.raises(SiteLayoutChanged, match="DOM parse failed") as caught:
        search._read_rows(object())
    assert caught.value.__cause__ is original
    assert not isinstance(caught.value, GuardBlocked)


def test_guard_confirm_failure_retains_explicit_block_classification(monkeypatch):
    notice = {"message": "미허가 도구 CODE: -8002", "code": "-8002"}
    page = SimpleNamespace(context=SimpleNamespace())
    monkeypatch.setattr(search, "inspect_guard_notice", lambda page: notice)
    record = Mock()
    monkeypatch.setattr(search, "record_guard", record)
    monkeypatch.setattr(search, "dismiss_macro_notice", Mock(return_value=False))
    with pytest.raises(GuardBlocked, match="dismiss failed") as caught:
        search._check_guard(page, "submit")
    assert caught.value.explicit is True
    record.assert_called_once_with(page, notice, "submit")


def test_popup_guard_survives_until_query_checks_it(monkeypatch):
    page = SimpleNamespace(context=SimpleNamespace(
        _pending_guard_notices=[{"message": "CODE: -8003", "code": "-8003"}],
    ))
    monkeypatch.setattr(search, "inspect_guard_notice", lambda page: None)
    assert search._check_guard(page, "submit") is True
    assert search._check_guard(page, "submit") is False


def test_guard_retry_rejects_changed_conditions_before_click(monkeypatch):
    page = Mock()
    monkeypatch.setattr(search, "_query_state", lambda page: valid_state() | {
        "date": "2026-11-08(일) 09:00",
    })
    click = Mock()
    monkeypatch.setattr(search, "human_click", click)
    with pytest.raises(QueryConditionMismatch, match="before guard retry"):
        search._requery_after_guard(page, config=config(), where="test")
    click.assert_not_called()
    page.locator.assert_not_called()


def test_guard_retry_revalidates_after_click(monkeypatch):
    page = Mock()
    page.locator.return_value.filter.return_value.first.is_visible.return_value = True
    states = iter([valid_state(), valid_state() | {"dest": "대구"}])
    monkeypatch.setattr(search, "_query_state", lambda page: next(states))
    monkeypatch.setattr(search, "human_pause", lambda *args: None)
    monkeypatch.setattr(search, "_check_guard", lambda *args: False)
    click = Mock()
    read = Mock()
    monkeypatch.setattr(search, "human_click", click)
    monkeypatch.setattr(search, "_read_rows", read)
    with pytest.raises(QueryConditionMismatch, match="after guard retry"):
        search._requery_after_guard(page, config=config(), where="test")
    click.assert_called_once()
    read.assert_not_called()


def test_empty_retry_without_new_notice_is_not_explicit_block(monkeypatch):
    page = Mock()
    page.locator.return_value.filter.return_value.first.is_visible.return_value = True
    monkeypatch.setattr(search, "_query_state", lambda page: valid_state())
    monkeypatch.setattr(search, "human_pause", lambda *args: None)
    monkeypatch.setattr(search, "human_click", Mock())
    monkeypatch.setattr(search, "_check_guard", lambda *args: False)
    monkeypatch.setattr(search, "_read_rows", lambda page: [])
    with pytest.raises(SearchResultUnavailable):
        search._requery_after_guard(page, config=config(), where="test")


@pytest.mark.parametrize("row,include_srt,expected", [
    ({"origin": "서울", "dest": "부산"}, False, True),
    ({"origin": "서울", "dest": "부산"}, True, True),
    ({"origin": "청량리", "dest": "부전"}, False, False),
    ({"origin": "청량리", "dest": "부전"}, True, False),
    ({"origin": "수서", "dest": "부산"}, False, False),
    ({"origin": "수서", "dest": "부산"}, True, True),
    ({"origin": "수서", "dest": "부전"}, True, False),
    ({"origin": None, "dest": "부산"}, False, False),
    ({"origin": "서울", "dest": None}, False, False),
])
def test_only_requested_route_or_opted_in_suseo_is_allowed(row, include_srt, expected):
    cfg = config(ktxa_include_srt=include_srt)
    assert search._route_matches(row, cfg) is expected


@pytest.mark.parametrize("requested", ["서울", "용산"])
def test_suseo_destination_requires_opt_in_too(requested):
    row = {"origin": "부산", "dest": "수서"}
    cfg = config(ktxa_origin="부산", ktxa_dest=requested)
    assert search._route_matches(row, cfg) is False
    cfg.ktxa_include_srt = True
    assert search._route_matches(row, cfg) is True


@pytest.fixture(scope="module")
def query_page():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        pytest.skip("System Chrome required for local query-state DOM fixtures")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(chrome), headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def test_query_state_reads_search_form_inputs(query_page):
    query_page.set_content(
        '<input name="txtGoStart" value="서울"><input name="txtGoEnd" value="부산">'
        '<input id="startDate" value="2026-11-07(토) 09:00">'
        '<a class="data btn_pop">총 2명</a>'
    )
    state = search._query_state(query_page)
    assert state["origin"] == "서울"
    assert state["dest"] == "부산"
    assert state["passengers"] == "총 2명"
    assert search._condition_errors(state, config()) == []


def test_query_state_reads_result_inputs_over_empty_or_stale_label(query_page):
    query_page.set_content(
        '<input id="labelstart" value="서울"><input id="labelend" value="부산">'
        '<input id="startDate" value="2026-11-07(토) 09:00">'
        '<a class="data btn_pop" style="display:none">총 1명</a>'
        '<div class="selectAreaWrap"><a class="btn_recom">'
        '<input id="labelple" value="총 2명"></a></div>'
    )
    state = search._query_state(query_page)
    assert state["origin"] == "서울"
    assert state["dest"] == "부산"
    assert state["passengers"] == "총 2명"
    assert search._condition_errors(state, config()) == []
