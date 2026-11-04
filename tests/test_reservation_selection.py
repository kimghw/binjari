"""Local DOM regressions: a reservation must resolve exactly one intended seat."""

from datetime import date
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest

from ktx_watcher.browser import sync_playwright
from ktx_watcher.korail import ReservationFailed
from ktx_watcher.korail.reserve import _select_reservation_anchor, attempt_reservation


@pytest.fixture(scope="module")
def browser():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        pytest.skip("System Chrome is required for local DOM tests")
    with sync_playwright() as p:
        instance = p.chromium.launch(executable_path=str(chrome), headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.route("**/*", lambda route: route.fulfill(body="<html></html>", content_type="text/html"))
    page.goto("http://fixture.test/ticket/search/list")
    yield page
    page.close()


def row(train="KTX001", depart="09:30", arrive="12:00", *, status="일반실10,000원",
        special="특실20,000원", general_class="gen", origin="서울", dest="부산"):
    return (
        '<li class="tckList">'
        f'{train}<div class="data_box"><h3><span>{origin}</span> → '
        f'<span>{dest}</span>({depart} ~ {arrive})</h3></div>'
        f'<div class="price_box {general_class}"><a href="#" data-seat="general" '
        f'onclick="window.clicked.push(\'general\'); return false">{status}</a></div>'
        '<div class="price_box"><a href="#" data-seat="special" '
        f'onclick="window.clicked.push(\'special\'); return false">{special}</a></div></li>'
    )


def show(page, rows, *, origin="서울", dest="부산", day="2026-11-07", result_inputs=False):
    origin_attr = 'id="labelstart"' if result_inputs else 'name="txtGoStart"'
    dest_attr = 'id="labelend"' if result_inputs else 'name="txtGoEnd"'
    page.set_content(
        '<script>window.clicked=[];</script>'
        f'<input {origin_attr} value="{escape(origin)}">'
        f'<input {dest_attr} value="{escape(dest)}">'
        f'<input id="startDate" value="{day}(토) 09:00"><ul>{rows}</ul>'
    )


def target(page, index=0, **overrides):
    result = {
        "origin": "서울", "dest": "부산", "date": "2026-11-07",
        "depart": "09:30", "seat_class": "일반실", "status_kind": "reserve",
        "_raw": page.locator("li.tckList").nth(index).text_content(),
        "_row_index": index,
    }
    result.update(overrides)
    return result


def test_matching_arrival_is_not_departure(page):
    show(page, row(depart="07:00", arrive="09:30"))
    with pytest.raises(ReservationFailed, match="출발시각"):
        _select_reservation_anchor(page, target(page))
    assert page.evaluate("window.clicked") == []


def test_missing_target_does_not_select_first_available(page):
    show(page, row())
    wanted = target(page)
    show(page, row(train="KTX099", depart="10:00"))
    cfg = SimpleNamespace(ktxa_origin="서울", ktxa_dest="부산", ktxa_date=date(2026, 11, 7))
    client = SimpleNamespace(main_page=lambda: page)
    with pytest.raises(ReservationFailed, match="일치 행 0개"):
        attempt_reservation(client, cfg, wanted)
    assert page.evaluate("window.clicked") == []


def test_ambiguous_identical_rows_stop(page):
    show(page, row() + row())
    with pytest.raises(ReservationFailed, match="일치 행 2개"):
        _select_reservation_anchor(page, target(page))
    assert page.evaluate("window.clicked") == []


@pytest.mark.parametrize("field,value", [("origin", "용산"), ("dest", "대전"), ("day", "2026-11-08")])
def test_changed_query_conditions_stop(page, field, value):
    show(page, row())
    wanted = target(page)
    show(page, row(), **{field: value})
    with pytest.raises(ReservationFailed, match="불일치"):
        _select_reservation_anchor(page, wanted)
    assert page.evaluate("window.clicked") == []


def test_reordered_rows_keep_train_identity(page):
    show(page, row())
    wanted = target(page)
    show(page, row(train="KTX999", depart="08:00") + row())
    anchor = _select_reservation_anchor(page, wanted)
    assert "KTX001" in anchor.evaluate("el => el.closest('li').textContent")


@pytest.mark.parametrize("seat,expected", [("일반실", "general"), ("특실", "special")])
def test_waitlist_stays_in_requested_seat_class(page, seat, expected):
    show(page, row(status="예약대기", special="예약대기", general_class="sold_out_wait"))
    wanted = target(page, seat_class=seat, status_kind="waitlist")
    anchor = _select_reservation_anchor(page, wanted)
    anchor.click()
    assert page.evaluate("window.clicked") == [expected]


def test_stale_availability_requires_fresh_search(page):
    show(page, row())
    wanted = target(page)
    show(page, row(status="일반실매진", general_class="sold_out"))
    with pytest.raises(ReservationFailed, match="일치 행 0개"):
        _select_reservation_anchor(page, wanted)
    assert page.evaluate("window.clicked") == []


def test_two_seat_actions_are_ambiguous(page):
    duplicate = row()
    duplicate = duplicate.replace('</a></div>', '</a><a href="#">추가10,000원</a></div>', 1)
    show(page, duplicate)
    with pytest.raises(ReservationFailed, match="버튼을 한 곳"):
        _select_reservation_anchor(page, target(page))
    assert page.evaluate("window.clicked") == []


def test_result_page_input_ids_and_actual_station_validation(page):
    show(page, row(), result_inputs=True)
    wanted = target(page, row_origin="서울", row_dest="부산")
    anchor = _select_reservation_anchor(page, wanted)
    assert anchor.get_attribute("data-seat") == "general"


def test_adjacent_station_row_cannot_masquerade_as_requested_route(page):
    show(page, row(origin="청량리", dest="부전"), result_inputs=True)
    wanted = target(page, row_origin="서울", row_dest="부산")
    with pytest.raises(ReservationFailed, match="실제 출발역"):
        _select_reservation_anchor(page, wanted)
    assert page.evaluate("window.clicked") == []


def test_opted_in_srt_row_keeps_query_and_actual_stations_separate(page):
    show(page, row(train="SRT301", origin="수서"), result_inputs=True)
    wanted = target(page, origin="수서", row_origin="수서", row_dest="부산",
                    _query_origin="서울", _query_dest="부산")
    anchor = _select_reservation_anchor(page, wanted)
    assert "수서" in anchor.evaluate("el => el.closest('li').textContent")
