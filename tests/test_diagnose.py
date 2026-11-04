"""The diagnostic must never turn a reserve configuration into a booking."""

import json
from types import SimpleNamespace

import pytest

from ktx_watcher import diagnose
from ktx_watcher.config import KTXAConfig
from ktx_watcher.korail import GuardBlocked


def config():
    return KTXAConfig.model_validate({
        "KTXA_ORIGIN": "Seoul", "KTXA_DEST": "Busan", "KTXA_DATE": "2026-11-07",
        "KTXA_TIMES": "09:00", "KTXA_MODE": "reserve",
        "KTXA_USER": "private-user", "KTXA_PASS": "private-password",
        "KTXA_PAYMENT_MODE": True, "KTXA_TRANSFER_ENABLED": True,
        "KTXA_TRANSFER_SEND": True, "TEAMS_ENABLED": True,
    })


@pytest.mark.parametrize("blocked", [False, True])
def test_query_only_keeps_browser_and_records_failure(monkeypatch, tmp_path, blocked):
    monkeypatch.setenv("KTXA_PASS", "private-password")
    page = SimpleNamespace(url="https://www.korail.com/ticket/search/list", _guard_events=[])
    events = []

    class Launcher:
        def __init__(self, **kwargs):
            pass

        def ensure_running(self):
            return "http://localhost:9444"

        def shutdown_if_owned(self):
            pytest.fail("The diagnostic must leave Chrome open")

    class Client:
        def __init__(self, url):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("disconnected")

        def main_page(self):
            return page

    def query(client, cfg):
        assert cfg.ktxa_mode == "search"
        assert cfg.ktxa_user == cfg.ktxa_pass == ""
        assert not cfg.ktxa_payment_mode
        assert not cfg.ktxa_transfer_enabled
        assert not cfg.ktxa_transfer_send
        assert not cfg.teams_enabled
        if blocked:
            page._guard_events.append({"message": "-8002", "stage": "submit"})
            raise GuardBlocked("-8002 private-password", explicit=True)
        return [{"depart": "10:18", "seat_class": "general", "_raw": "private-password"}]

    def evidence(page, output, label):
        events.append(label)
        return {"screenshot": label + ".png"}

    monkeypatch.setattr(diagnose, "ChromeLauncher", Launcher)
    monkeypatch.setattr(diagnose, "KorailSPAClient", Client)
    monkeypatch.setattr(diagnose, "perform_search", query)
    monkeypatch.setattr(diagnose, "_page_evidence", evidence)
    monkeypatch.setattr(diagnose, "_parse_result_rows", lambda p: [])

    original = config()
    report = diagnose.run_diagnosis(original, tmp_path)
    assert original.ktxa_mode == "reserve"
    assert events == ["start", "end", "disconnected"]
    stored = (tmp_path / "report.json").read_text(encoding="utf-8")
    trace = (tmp_path / "trace.log").read_text(encoding="utf-8")
    assert "private-password" not in stored + trace
    assert "private-user" not in stored + trace
    assert json.loads(stored) == report
    if blocked:
        assert report["status"] == "error"
        assert report["error"]["type"] == "GuardBlocked"
        assert report["error"]["explicit"] is True
        assert report["guard_events"][0]["stage"] == "submit"
    else:
        assert report["status"] == "ok"
        assert report["candidates"] == [{"depart": "10:18", "seat_class": "general"}]


def test_redaction_does_not_break_json_numeric_values(monkeypatch):
    monkeypatch.setenv("PAY_CARD_PW2", "12")
    value = diagnose._sanitize({"count": 12, "message": "private PIN 12"}, diagnose.Redactor())
    assert value["count"] == 12
    assert "12" not in value["message"]


def test_short_payment_values_preserve_dates_and_times(monkeypatch):
    monkeypatch.setenv("PAY_CARD_MM", "11")
    monkeypatch.setenv("PAY_CARD_YY", "2026")
    monkeypatch.setenv("PAY_CARD_PW2", "04")
    monkeypatch.setenv("KTXA_PASS", "04")
    redact = diagnose.Redactor()
    text = "2026-11-04 09:04:11 query date=2026-11-07 time=11:04"
    assert redact(text) == text
    assert redact("PAY_CARD_PW2=04 password: 04 PIN 04") == (
        "PAY_CARD_PW2=[redacted] password: [redacted] PIN [redacted]"
    )
    value = diagnose._sanitize({"PAY_CARD_PW2": "04", "PAY_CARD_MM": "11",
                                "date": "2026-11-04", "count": 4}, redact)
    assert value == {"PAY_CARD_PW2": "[redacted]", "PAY_CARD_MM": "[redacted]",
                     "date": "2026-11-04", "count": 4}


def test_report_includes_popup_context_events_without_duplicates():
    shared = {"stage": "submit", "code": "-8002"}
    popup = {"stage": "popup", "code": "-8003"}
    page = SimpleNamespace(_guard_events=[shared],
                           context=SimpleNamespace(_guard_events=[shared, popup]))
    assert diagnose._guard_events(page) == [shared, popup]
