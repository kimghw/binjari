"""결제 응답 처리 (2026-11-07 00:35 실패 대응).

- 응답 모달을 무조건 '확인' 으로 닫지 않고 분류한다: 진행 확인 → 네, 오류 → 개입, 완료 → 확인.
- 완료 판정은 URL 로만 한다 (결제 폼 라벨 키워드로 판정하던 방식 제거).
- 개입이 필요한 종료에서는 Chrome 을 닫지 않는다.
"""

from ktx_watcher.korail import payment
from ktx_watcher import main as watcher_main


def test_complete_url_detection():
    assert payment._is_complete_url("https://www.korail.com/ticket/myticket/list")
    assert payment._is_complete_url("https://www.korail.com/ticket/payment/complete")
    assert not payment._is_complete_url("https://www.korail.com/ticket/payment/payment")
    assert not payment._is_complete_url("")


def test_modal_classification():
    assert payment._classify_payment_modal("정차역 수가 적어 가격이 높습니다. 계속 진행하시겠습니까?") == "proceed"
    assert payment._classify_payment_modal("카드 비밀번호를 확인하세요") == "error"
    assert payment._classify_payment_modal("카드사 점검 시간입니다") == "error"
    assert payment._classify_payment_modal("결제가 완료되었습니다") == "ok"
    assert payment._classify_payment_modal("안내 문구") == "unknown"
    # 진행 확인형이 오류 키워드를 함께 담아도 '네' 로 통과시킨다
    assert payment._classify_payment_modal("요금을 확인하세요. 계속 진행하시겠습니까?") == "proceed"


def test_keep_browser_open_flag(monkeypatch):
    monkeypatch.setattr(watcher_main, "_KEEP_BROWSER_OPEN", False)
    watcher_main._keep_browser_open("test")
    assert watcher_main._KEEP_BROWSER_OPEN is True
