"""Korail SPA 승차권 전달하기 흐름 — CDP-only.

결제/발권 완료 후 /ticket/myticket/list 의 '전달하기' 로 승차권을 다른 회원에게 전달한다.

**2단계 레이어** (CDP DOM probe 2026-07-07):
  step1 `.layerWrap.type_tckRelay_wrap`
    - 승차권 체크: input#ck_<승차권번호> (readonly — label[for^='ck_'] 클릭)
    - [승차권 전달] button.btn_bn-blue
  step2 (같은 wrap 이 type_m_pd-n 로 전환)
    - 탭: 코레일톡(기본 active) | 알림톡(SMS) | 카카오톡  (role=tab)
    - 수신자 radio name=hidPbpAcepPsMbFlg: 회원 Y(기본) / 비회원 N
    - 회원정보 select[name='acept']: 1=회원번호 2=이메일 3=휴대폰
    - 정보입력 input[name='memberData']   ← 회원번호
    - 이름     input[name='hidAcepPsNm'] + [조회]
    - 휴대폰   input[name='hidAcepPsTeln'] (maxlength=11, '-' 제외)
    - 동의     input#agree01
    - [전송하기] button.btn_bn-blue.full-btn

KTXA_TRANSFER_SEND=false (기본): 입력·동의까지만 하고 '전송하기' 직전 중단 (dry-run).
잘못 전달한 경우 회수: 승차권 구입이력 > 보낸내역.
"""

from __future__ import annotations

import logging
import time as _time

from ..browser import Page, TimeoutError as PWTimeoutError

from ..config import KTXAConfig
from . import SiteLayoutChanged, UserActionRequired
from .client import KorailSPAClient, human_pause, safe_goto

LOGGER = logging.getLogger("ktx_watcher_spa.korail.transfer")

MYTICKET_URL = "https://www.korail.com/ticket/myticket/list"
STEP_LAYER = ".layerWrap.type_tckRelay_wrap"
RECIPIENT_MEMBER_NO = "input[name='memberData']"
RECIPIENT_NAME = "input[name='hidAcepPsNm']"
RECIPIENT_PHONE = "input[name='hidAcepPsTeln']"
AGREE_LABEL = "label[for='agree01']"
AGREE_CHECKBOX = "input#agree01"
MEMBER_INFO_SELECT = "select[name='acept']"


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _click_visible_by_text(page: Page, text: str) -> bool:
    """정확히 text 인 visible button/a 클릭 (숨은 GNB 중복 회피)."""
    return bool(page.evaluate(
        """(text) => {
            const cands = [...document.querySelectorAll('button, a')].filter(b =>
                (b.textContent||'').trim() === text && (b.offsetWidth || b.offsetHeight));
            if (!cands.length) return false;
            cands[0].click();
            return true;
        }""",
        text,
    ))


def _fill_verified(page: Page, name_attr: str, value: str, label: str) -> None:
    """네이티브 value setter + input/change 이벤트로 입력 후 값 검증.

    실측 2026-07-07: 이 폼은 React 컨트롤드 인풋이라 키 입력(press_sequentially/
    keyboard.type)이 즉시 '' 로 되돌아감 — setter 방식만 state 에 반영된다.
    """
    r = page.evaluate(
        """([name, val]) => {
            const inp = [...document.querySelectorAll(`input[name='${name}']`)]
                .find(i => i.offsetWidth || i.offsetHeight);
            if (!inp) return 'NO_INPUT';
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            inp.focus();
            setter.call(inp, val);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            return 'set';
        }""",
        [name_attr, value],
    )
    if r != "set":
        raise SiteLayoutChanged(f"전달 입력 필드 미발견: {label} (name={name_attr})")
    human_pause(0.4, 0.8)
    cur = page.evaluate(
        """(name) => {
            const i = [...document.querySelectorAll(`input[name='${name}']`)]
                .find(i => i.offsetWidth || i.offsetHeight);
            return i ? i.value : null;
        }""",
        name_attr,
    )
    if cur != value:
        raise SiteLayoutChanged(f"전달 입력 검증 실패: {label} (현재 len={len(cur or '')})")
    LOGGER.info("전달 입력 OK: %s", label)


def open_transfer_popup(page: Page) -> None:
    """myticket/list 에서 '전달하기' 클릭 → step1 레이어 대기."""
    if "/myticket/list" not in (page.url or ""):
        safe_goto(page, MYTICKET_URL, timeout_ms=30_000)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except PWTimeoutError:
            pass
        human_pause(1.5, 2.5)

    try:
        body = page.locator("body").inner_text(timeout=3000)
    except Exception:
        body = ""
    if "발권하신 승차권이 없습니다" in body:
        raise UserActionRequired("전달할 승차권 없음 — 발권 내역이 비어 있음 (myticket/list)")

    if not _click_visible_by_text(page, "전달하기"):
        raise SiteLayoutChanged("'전달하기' 버튼 미발견 (myticket/list)")
    try:
        page.wait_for_selector(STEP_LAYER, timeout=8000)
    except PWTimeoutError:
        raise SiteLayoutChanged("승차권 전달하기 레이어(step1) 안 뜸")
    human_pause(0.6, 1.2)


def _select_ticket_and_advance(page: Page) -> None:
    """step1: 승차권 체크(label 클릭) → '승차권 전달' → step2 폼 대기."""
    r = page.evaluate(
        """() => {
            const wrap = [...document.querySelectorAll('.layerWrap.type_tckRelay_wrap')]
                .find(l => l.offsetWidth || l.offsetHeight);
            if (!wrap) return 'NO_LAYER';
            const lbl = wrap.querySelector("label[for^='ck_']");
            if (!lbl) return 'NO_TICKET';
            lbl.click();
            return 'OK:' + lbl.getAttribute('for');
        }"""
    )
    if not str(r).startswith("OK:"):
        raise SiteLayoutChanged(f"전달할 승차권 체크 실패: {r}")
    LOGGER.info("전달 대상 승차권 선택: %s", r)
    human_pause(0.5, 1.0)

    if not _click_visible_by_text(page, "승차권 전달"):
        raise SiteLayoutChanged("'승차권 전달' 버튼 미발견 (step1)")
    try:
        page.wait_for_selector(RECIPIENT_NAME, timeout=8000)
    except PWTimeoutError:
        raise SiteLayoutChanged("수신자 입력 폼(step2) 안 뜸")
    human_pause(0.6, 1.2)


def perform_transfer(client: KorailSPAClient, config: KTXAConfig) -> str:
    """발권된 승차권 전달. return: 'dry_run' | 'sent'."""
    member_no = _digits(config.ktxa_transfer_member_no)
    name = config.ktxa_transfer_name
    phone = _digits(config.ktxa_transfer_phone)
    missing = [k for k, v in (("MEMBER_NO", member_no), ("NAME", name), ("PHONE", phone)) if not v]
    if missing:
        raise UserActionRequired(
            f"KTXA_TRANSFER_{'/'.join(missing)} 미설정 — .env.ktx 에 수신자 정보를 채우세요"
        )

    page = client.main_page()
    open_transfer_popup(page)
    _select_ticket_and_advance(page)

    # 전달 방식: 코레일톡 탭(기본 active) · 수신자: 회원(기본 checked) — 그대로 사용.
    # 회원정보 = 회원번호 (select value 1)
    try:
        page.locator(MEMBER_INFO_SELECT).first.select_option(value="1", timeout=3000)
    except Exception as e:
        raise SiteLayoutChanged(f"회원정보 select(회원번호) 실패: {e}") from e
    human_pause(0.3, 0.6)

    _fill_verified(page, "memberData", member_no, "회원번호")
    _fill_verified(page, "hidAcepPsNm", name, "이름")
    _fill_verified(page, "hidAcepPsTeln", phone, "휴대폰")

    # 동의 체크 — visible label JS 클릭 (React 체크박스, 실측 동작 방식)
    agreed = page.evaluate(
        """() => {
            const cb = [...document.querySelectorAll('input#agree01')]
                .find(i => i.offsetWidth || i.offsetHeight) || document.querySelector('input#agree01');
            if (!cb) return 'NO_CB';
            if (cb.checked) return 'already';
            const lbl = [...document.querySelectorAll("label[for='agree01']")]
                .find(l => l.offsetWidth || l.offsetHeight);
            if (lbl) lbl.click(); else cb.click();
            return cb.checked ? 'checked' : 'FAIL';
        }"""
    )
    human_pause(0.3, 0.6)
    if agreed not in ("checked", "already"):
        raise SiteLayoutChanged(f"개인정보 동의 체크 실패 ({agreed})")
    LOGGER.info("전달 폼 입력 완료 (수신자 %s / 회원번호 %s*** / 휴대폰 %s***)",
                name, member_no[:4], phone[:3])

    page.screenshot(path="runs/transfer_filled.png", full_page=True)

    if not config.ktxa_transfer_send:
        LOGGER.info("KTXA_TRANSFER_SEND=false — '전송하기' 직전 중단 (dry-run). "
                    "스크린샷 runs/transfer_filled.png")
        return "dry_run"

    # 실제 전송: 조회 → 전송하기 → 확인 모달
    if _click_visible_by_text(page, "조회"):
        LOGGER.info("수신 회원 조회 클릭")
        human_pause(1.2, 2.0)
    if not _click_visible_by_text(page, "전송하기"):
        raise SiteLayoutChanged("'전송하기' 버튼 미발견")
    human_pause(1.0, 2.0)
    for _ in range(3):
        clicked = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll('.ReactModal__Content, .layerWrap')]
                    .filter(l => l.offsetWidth || l.offsetHeight);
                for (const r of roots) {
                    for (const b of r.querySelectorAll('button')) {
                        const t = (b.textContent||'').trim();
                        if (t === '예' || t === '확인') { b.click(); return t; }
                    }
                }
                return null;
            }"""
        )
        if not clicked:
            break
        LOGGER.info("전송 확인 모달 '%s' 클릭", clicked)
        _time.sleep(1.2)
    LOGGER.info("✅ 승차권 전달 전송 완료 (수신자 %s)", name)
    return "sent"


__all__ = ["perform_transfer", "open_transfer_popup"]
