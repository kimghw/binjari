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
import re
import time as _time
from typing import Any, Dict

from ..browser import Page, TimeoutError as PWTimeoutError

from ..config import KTXAConfig
from ..dom import read_page_state
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


def _select_reservation_anchor(page: Page, target: Dict[str, Any]):
    """Resolve one unchanged search row and one seat-class action, or stop.

    Row numbers can shift after a refresh, and a departure string can also be
    another train's arrival time. Keep the complete row identity from the search
    snapshot and check its first time separately. A stale snapshot requires a
    fresh search; selecting another available train is never a fallback.
    """
    state = read_page_state(page, inputs={
        "origin": S.ORIGIN_INPUT, "dest": S.DEST_INPUT, "date": S.DATE_INPUT,
    }, include_text=False)
    fields = state["inputs"]
    if "/ticket/search/list" not in state["url"]:
        raise ReservationFailed("예약 대상 검색 결과 페이지가 아닙니다")
    for key in ("origin", "dest"):
        expected = target.get(f"_query_{key}", target.get(key))
        if not expected or (fields.get(key) or "").strip() != expected.strip():
            raise ReservationFailed(f"예약 직전 조회 {key} 불일치 — 다시 조회해야 합니다")
    page_date = re.match(r"\d{4}-\d{2}-\d{2}", fields.get("date") or "")
    if not page_date or page_date.group() != target.get("date"):
        raise ReservationFailed("예약 직전 조회 날짜 불일치 — 다시 조회해야 합니다")

    raw = target.get("_raw") or ""
    departure = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", raw)
    if not departure or f"{int(departure[1]):02d}:{departure[2]}" != target.get("depart"):
        raise ReservationFailed("예약 대상 출발시각을 확인할 수 없습니다")
    identity = "".join(raw.split())
    if not identity:
        raise ReservationFailed("예약 대상 열차 정보가 없습니다")

    # A text-based locator re-resolves the same row even if row positions move.
    identity_pattern = re.compile(r"^\s*" + r"\s*".join(map(re.escape, identity)) + r"\s*$")
    row = page.locator("li.tckList").filter(has_text=identity_pattern)
    matches = row.count()
    if matches != 1:
        raise ReservationFailed(f"예약 대상 열차 일치 행 {matches}개 — 다시 조회해야 합니다")

    if "row_origin" in target or "row_dest" in target:
        stations = row.locator(".data_box h3 > span").evaluate_all(
            "els => els.slice(0, 2).map(el => (el.textContent || '').trim())"
        )
        expected_stations = [target.get("row_origin"), target.get("row_dest")]
        if (not all(expected_stations) or stations != expected_stations
                or stations != [target.get("origin"), target.get("dest")]):
            raise ReservationFailed("예약 직전 열차의 실제 출발역·도착역 불일치")

    seat_class = target.get("seat_class")
    if seat_class not in ("일반실", "특실"):
        raise ReservationFailed(f"지원하지 않는 예약 좌석 등급: {seat_class!r}")
    boxes = row.locator(".price_box")
    classes = boxes.evaluate_all("els => els.map(el => el.className)")
    general_indices = [i for i, cls in enumerate(classes) if "gen" in cls.split()]
    if not classes or len(general_indices) > 1:
        raise SiteLayoutChanged("예약 대상 좌석 등급 구성을 확인할 수 없습니다")
    general_index = general_indices[0] if general_indices else 0
    if seat_class == "일반실":
        box_index = general_index
    else:
        special_indices = [i for i in range(len(classes)) if i != general_index]
        if len(special_indices) != 1:
            raise SiteLayoutChanged("예약 대상 특실을 한 곳으로 특정할 수 없습니다")
        box_index = special_indices[0]
    box = boxes.nth(box_index)
    kind = (target.get("status_kind") or "reserve").lower()
    if kind == "waitlist":
        anchor = box.locator("a").filter(has_text="예약대기")
    elif kind == "standing":
        anchor = box.locator("a").filter(has_text="입석")
    elif kind == "reserve":
        if "sold_out" in classes[box_index].split():
            raise ReservationFailed("예약 대상 좌석이 매진되었습니다")
        anchor = box.locator("a").filter(has_text="원").filter(
            has_not_text=re.compile(r"매진(?!임박)"),
        )
    else:
        raise ReservationFailed(f"지원하지 않는 예약 동작: {kind!r}")
    anchor = anchor.filter(visible=True)
    if anchor.count() != 1:
        raise ReservationFailed("예약 대상 좌석 버튼을 한 곳으로 특정할 수 없습니다")
    return anchor


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

    status_kind = (target.get("status_kind") or "reserve").lower()
    LOGGER.info("status_kind=%s — 예매/예약대기/입석 분기", status_kind)

    # Validate the target again immediately before selecting its seat.
    if (target.get("_query_origin", target.get("origin")),
        target.get("_query_dest", target.get("dest")), target.get("date")) != (
        config.ktxa_origin, config.ktxa_dest, config.ktxa_date.isoformat(),
    ):
        raise ReservationFailed("예약 대상과 현재 감시 조건이 다릅니다")
    chosen = _select_reservation_anchor(page, target)

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
