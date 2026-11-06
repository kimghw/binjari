"""main.py 의 예외 분류: 브라우저 소실은 같은 객체로 복구할 수 없으니 즉시 종료 대상."""

from ktx_watcher import main as watcher_main


class TargetClosedError(Exception):
    pass


def test_browser_loss_is_detected_by_type_or_message():
    assert watcher_main._browser_lost(
        TargetClosedError("BrowserContext.new_page: Target page, context or browser has been closed"))
    assert watcher_main._browser_lost(Exception("Connection closed while reading from the driver"))
    assert watcher_main._browser_lost(Exception("Target closed"))


def test_ordinary_timeouts_are_not_browser_loss():
    assert not watcher_main._browser_lost(Exception("Locator.click: Timeout 4000ms exceeded."))
    assert not watcher_main._browser_lost(ValueError("bad value"))
