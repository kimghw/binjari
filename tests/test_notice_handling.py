from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ktx_watcher.korail import client


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(client, "HUMANIZE", False)


def test_optional_notice_checkbox_failure_still_closes(monkeypatch):
    monkeypatch.setattr(client, "read_page_state", lambda page: {
        "body": "공지: 오늘 그만보기 창닫기", "modals": [],
    })
    clicked = []

    def click(page, selector, timeout=2000):
        clicked.append(selector)
        if selector == client.S.NOTICE_MODAL_HIDE_TODAY_CHECKBOX:
            raise client.PWTimeoutError("checkbox was intercepted")
        return True

    monkeypatch.setattr(client, "_click_visible", click)
    assert client.dismiss_notice_modal(object()) is True
    assert client.S.NOTICE_MODAL_DISMISS_BUTTON in clicked


@pytest.mark.parametrize("text", ["안내 메시지: 날짜를 선택하세요", "안내 메세지: 점검 시간입니다"])
def test_generic_notice_is_not_guard(monkeypatch, text):
    monkeypatch.setattr(client, "read_page_state", lambda page: {
        "body": text, "modals": [text],
    })
    click = Mock()
    monkeypatch.setattr(client, "_click_visible", click)
    assert client.inspect_guard_notice(object()) is None
    assert client.dismiss_macro_notice(object()) is False
    click.assert_not_called()


@pytest.mark.parametrize("text,code", [
    ("안내 메시지\n미허가 도구 사용 시 이용 제한\nCODE: -8002", "-8002"),
    ("CODE: -8003", "-8003"),
    ("비정상적인 접속으로 이용이 제한됩니다", ""),
])
def test_guard_detected_even_when_confirm_click_fails(monkeypatch, text, code):
    monkeypatch.setattr(client, "read_page_state", lambda page: {
        "body": text, "modals": [text],
    })
    monkeypatch.setattr(client, "_click_visible", Mock(side_effect=client.PWTimeoutError("blocked")))
    evidence = client.inspect_guard_notice(object())
    assert evidence == {"message": text, "code": code}
    assert client.dismiss_macro_notice(object(), notice=evidence) is False
    # The caller retains the evidence even though dismissal was unsuccessful.
    assert evidence["code"] == code


def test_guard_popup_body_and_bounded_message(monkeypatch):
    text = "header " * 300 + "개발자도구 사용 제한 CODE: -8002" + " details" * 300
    monkeypatch.setattr(client, "read_page_state", lambda page: {
        "body": text, "modals": [],
    })
    evidence = client.inspect_guard_notice(object())
    assert evidence["code"] == "-8002"
    assert "개발자도구" in evidence["message"]
    assert len(evidence["message"]) <= 1200


def test_read_failure_is_not_reported_as_no_guard(monkeypatch):
    monkeypatch.setattr(client, "read_page_state", Mock(side_effect=RuntimeError("navigation race")))
    with pytest.raises(RuntimeError, match="navigation race"):
        client.inspect_guard_notice(object())


def test_failed_attach_cleans_driver_and_preserves_error(monkeypatch):
    driver = SimpleNamespace(
        chromium=SimpleNamespace(connect_over_cdp=Mock(side_effect=RuntimeError("attach failed"))),
        stop=Mock(),
    )
    monkeypatch.setattr(client, "sync_playwright", lambda: SimpleNamespace(start=lambda: driver))
    browser_client = client.KorailSPAClient("ws://127.0.0.1:9444/example")
    with pytest.raises(RuntimeError, match="attach failed"):
        browser_client.start()
    driver.stop.assert_called_once()
    assert browser_client._pw is None
    assert browser_client._browser is None


def test_popup_guard_retains_evidence_before_failed_confirm(monkeypatch):
    callbacks = {}
    context = SimpleNamespace(on=lambda event, callback: callbacks.setdefault(event, callback))
    popup = SimpleNamespace(
        opener=lambda: object(), wait_for_load_state=lambda *args, **kwargs: None,
        url="https://www.korail.com/popup",
    )
    notice_text = "미허가 도구 CODE: -8002"
    monkeypatch.setattr(client, "read_page_state", lambda page: {
        "body": notice_text, "modals": [],
    })
    ordering = []

    def record(page, notice, stage):
        ordering.append("record")
        return {**notice, "stage": stage}

    def fail_click(*args, **kwargs):
        ordering.append("click")
        raise client.PWTimeoutError("confirmation intercepted")

    monkeypatch.setattr(client, "record_guard", record)
    monkeypatch.setattr(client, "_click_visible", fail_click)
    monkeypatch.setattr(client.time, "sleep", lambda delay: None)
    client.attach_context_popup_guard(context)
    callbacks["page"](popup)
    assert ordering == ["record", "click"]
    assert context._pending_guard_notices == [{"message": notice_text, "code": "-8002"}]
    assert context._guard_events[0]["stage"] == "popup"
