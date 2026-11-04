"""Korail SPA reservation flow.

scope: 결제 *직전* 단계까지만. 실제 결제(카드 결제) 자동화는 본 variant 밖.

흐름:
  1. ensure_logged_in: /ticket/login 으로 가서 redirect 되는지 확인.
     안 되어 있으면 자격증명 입력 후 로그인.
  2. attempt_reservation: 결과 row 의 '예약하기' 클릭 → 후속 확정 버튼 한 번 클릭 →
     '결제하기' / '예약완료' 키워드 보이면 통과.
"""

from __future__ import annotations

import logging
import time as _time
from typing import Any, Dict

from ..browser import Page, TimeoutError as PWTimeoutError

from ..config import KTXAConfig
from . import CaptchaDetected, LoginError, ReservationFailed, SiteLayoutChanged, UserActionRequired
from . import selectors as S
from .client import (
    KorailSPAClient,
    dismiss_all_popups,
    dismiss_macro_notice,
    human_click,
    human_pause,
    human_type,
    safe_goto,
)

LOGGER = logging.getLogger("ktx_watcher_spa.korail.reserve")


def _is_logged_in(page: Page) -> bool:
    url = page.url or ""
    if "/ticket/login" in url and page.locator(S.LOGIN_ID_INPUT).count() > 0:
        return False
    return page.locator(".gnb_login_y").count() > 0


def ensure_logged_in(
    client: KorailSPAClient,
    config: KTXAConfig,
) -> None:
    page = client.main_page()

    # 1) 메인 → 잠시 머무름 (자연스러운 세션 시그널)
    safe_goto(page, S.MAIN_URL, timeout_ms=30_000)
    human_pause(1.0, 2.0)

    # 2)~6) 로그인 시도 — '복호화오류' (사이트 암호화 키 만료/깨짐, 2026-08-18 실측)
    # 는 페이지 새로고침 후 재입력하면 해소되는 일시 오류라 1회 재시도한다.
    for attempt in range(2):
        safe_goto(page, S.LOGIN_URL, timeout_ms=30_000)
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        human_pause(1.0, 2.0)

        if "/ticket/login" not in (page.url or ""):
            LOGGER.info("이미 로그인 상태 (url=%s)", page.url)
            return

        LOGGER.info("로그인 시도%s: user=%s***",
                    f" (재시도 {attempt})" if attempt else "", config.ktxa_user[:4])

        # 3) 보안 키보드 해제
        try:
            keysec = page.locator(S.LOGIN_KEYSEC_CHECK)
            if keysec.count() > 0 and keysec.first.is_checked():
                keysec.first.uncheck(timeout=3000)
                human_pause(0.3, 0.6)
        except Exception:
            pass

        dismiss_macro_notice(page)

        # 4) ID/PW 입력 (사람-유사 typing)
        try:
            id_input = page.locator(S.LOGIN_ID_INPUT).first
            pw_input = page.locator(S.LOGIN_PW_INPUT).first
            id_input.fill("")
            pw_input.fill("")
            human_type(id_input, config.ktxa_user)
            human_pause(0.3, 0.6)
            human_type(pw_input, config.ktxa_pass)
        except PWTimeoutError as e:
            raise SiteLayoutChanged(f"로그인 입력 selector 실패: {e}") from e

        human_pause(0.5, 1.0)

        # 5) 제출
        try:
            human_click(page.locator(S.LOGIN_SUBMIT).first)
        except PWTimeoutError as e:
            raise SiteLayoutChanged(f"로그인 제출 실패: {e}") from e

        # 6) redirect 대기
        for _ in range(30):
            _time.sleep(0.5)
            if "/ticket/login" not in (page.url or ""):
                LOGGER.info("로그인 성공 (url=%s)", page.url)
                return
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        dismiss_macro_notice(page)

        if "/ticket/login" not in (page.url or ""):
            break

        # 에러 메시지 추출 시도
        err = ""
        for sel in (".ReactModal__Content .tit", ".ReactModal__Content", ".error_msg"):
            try:
                t = page.locator(sel).first.inner_text(timeout=500)
                if t and t.strip():
                    err = t.strip().replace("\n", " ")[:200]
                    break
            except Exception:
                pass
        if "통신 중 에러" in err:
            raise CaptchaDetected(f"Korail 매크로 차단 (로그인 단계): {err}")
        if "복호화" in err and attempt == 0:
            LOGGER.warning("로그인 복호화오류 — 안내 닫고 새로고침 후 재시도: %s", err)
            try:
                page.locator("button:has-text('확인')").first.click(timeout=2000)
            except Exception:
                pass
            human_pause(1.5, 2.5)
            continue
        raise LoginError(f"로그인 후에도 /ticket/login (err={err!r})")

    LOGGER.info("로그인 성공 (url=%s)", page.url)


def attempt_reservation(
    client: KorailSPAClient,
    config: KTXAConfig,
    target: Dict[str, Any],
) -> None:
    """결과 row 의 예약 버튼 클릭 → 확정 모달까지 진행.

    target: search.perform_search 가 만든 dict.
    """
    page = client.main_page()
    LOGGER.info(
        "예약 시도: %s→%s %s %s [%s]",
        target["origin"], target["dest"], target["date"],
        target["depart"], target["seat_class"],
    )

    is_first = "특실" in (target.get("seat_class") or "")
    seat_key = "특실" if is_first else "일반실"
    depart_str = target.get("depart", "")  # 'HH:MM'
    status_kind = (target.get("status_kind") or "reserve").lower()
    LOGGER.info("status_kind=%s — 예매/예약대기/입석 분기", status_kind)

    # ─── STEP 1: 결과 row 의 anchor 클릭 → row 선택 (파란 하이라이트) ───
    # status_kind 별 anchor text 다름:
    #   reserve  : "일반실23,700원5%적립"  (예약 가능 row 만 "일반실" 텍스트 있음)
    #   waitlist : "예약대기"               (매진된 row 는 priceBox text 가 짧음 — "일반실" 단어 없음)
    #   standing : "입석 + 좌석"            (동일)
    import re as _re
    if status_kind == "waitlist":
        loc = page.locator("a").filter(has_text="예약대기")
    elif status_kind == "standing":
        loc = page.locator("a").filter(has_text="입석")
    else:
        loc = (
            page.locator("a")
            .filter(has_text=seat_key)
            .filter(has_text="원")
            .filter(has_not_text=_re.compile(r"매진(?!임)"))
        )
    n = loc.count()
    chosen = None
    for i in range(n):
        a = loc.nth(i)
        try:
            parent_text = a.evaluate(
                """el => {
                    let p = el;
                    for (let d = 0; d < 6 && p; d++) {
                        if (p.textContent && /\\d{1,2}:\\d{2}/.test(p.textContent)) {
                            return p.textContent;
                        }
                        p = p.parentElement;
                    }
                    return '';
                }"""
            ) or ""
            if depart_str and depart_str in parent_text:
                chosen = a
                LOGGER.info("예약 row 선택: snippet=%r", parent_text[:120])
                break
        except Exception:
            continue

    if chosen is None and n > 0:
        chosen = loc.first
        LOGGER.warning("depart 매칭 실패 → 첫 번째 가용 anchor 사용")

    if chosen is None:
        raise SiteLayoutChanged("예약 가능한 가격 anchor 미발견")

    try:
        human_click(chosen)
    except PWTimeoutError as e:
        raise SiteLayoutChanged(f"row 가격 anchor 클릭 실패: {e}") from e
    human_pause(0.8, 1.4)
    dismiss_all_popups(client.context)

    # ─── STEP 2: 하단 status_kind 별 액션 버튼 클릭 ───
    if status_kind == "waitlist":
        book_sel, book_label = S.WAITLIST_BUTTON, "예약대기신청"
    elif status_kind == "standing":
        book_sel, book_label = S.STANDING_BUTTON, "입석+좌석 예매"
    else:
        book_sel, book_label = S.BOOK_NOW_BUTTON, "예매"

    book_btn = page.locator(book_sel).first
    if book_btn.count() == 0:
        raise SiteLayoutChanged(f"{book_label} 버튼 미발견 — row 선택이 안 됐을 수도 (selector={book_sel})")

    try:
        if book_btn.is_disabled():
            raise UserActionRequired(f"{book_label} 버튼이 비활성 — row 선택 상태가 풀렸을 수 있음")
    except UserActionRequired:
        raise
    except Exception:
        pass

    try:
        human_click(book_btn)
        LOGGER.info("'%s' 버튼 클릭 (selector=%s)", book_label, book_sel)
    except PWTimeoutError as e:
        raise SiteLayoutChanged(f"{book_label} 버튼 클릭 실패: {e}") from e

    # 예매 클릭 직후 popup window (이용안내, 본인인증 안내 등) 여러 번 뜰 수 있음.
    # 1초 간격으로 3회 polling 하면서 모든 popup 의 '확인' 자동 클릭.
    for poll_i in range(6):
        _time.sleep(1.0)
        dismissed = dismiss_all_popups(client.context)
        if dismissed:
            LOGGER.info("popup dismiss iter=%d, count=%d", poll_i, dismissed)

    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    human_pause(1.5, 2.5)

    # ─── STEP 3: 결제 직전 페이지 도달 확인 ───
    try:
        html = page.content()
    except Exception:
        html = ""
    url = page.url or ""
    LOGGER.info("예매 클릭 후 url=%s", url)

    if status_kind == "waitlist":
        success_kw = ("예약대기 신청", "예약대기신청", "대기 신청", "대기번호", "대기 등록", "대기등록")
        ok_label = "✅ 예약대기 신청 단계 도달"
    elif status_kind == "standing":
        success_kw = ("결제하기", "결제 수단", "예약 완료", "예약완료", "신용카드", "카드번호", "입석")
        ok_label = "✅ 입석+좌석 예매 단계 도달"
    else:
        success_kw = ("결제하기", "결제 수단", "예약 완료", "예약완료", "신용카드", "카드번호")
        ok_label = "✅ 결제 직전 단계 도달 — 예약 흐름 정상 통과"

    if any(kw in html for kw in success_kw):
        LOGGER.info(ok_label)
        return

    # 성공 키워드도 없고 URL 도 안 바뀜 — 예약 미성립 (직전 dismiss 된 모달이 원인 안내였을 가능성).
    # 정상 return 하면 main 이 좌석 hold 로 오판하고 결제 단계까지 진행하므로 반드시 실패로 알린다.
    LOGGER.warning("%s 클릭 후 성공 키워드 미감지 — url=%s", book_label, url)
    raise ReservationFailed(f"{book_label} 클릭 후 예약 성립 확인 실패 (url={url})")


__all__ = ["ensure_logged_in", "attempt_reservation"]
