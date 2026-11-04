"""KorailSPAClient — CDP-only.

이 클래스는 공통 browser API의 ``chromium.connect_over_cdp(cdp_url)`` 만 한다.
자체 launch 경로는 없다.

부가 책임:
  - 팝업 자동 dismiss (context.on('page') 한 곳에서 처리)
  - 일반 광고/공지 팝업 자동 close
  - 실제 클릭·일괄 입력과 동작 사이 대기
"""

from __future__ import annotations

import logging
import os
import random
import time
from contextlib import AbstractContextManager
from typing import Optional

# NOTE: chrome_launcher import 가 socket.getaddrinfo 를 IPv4-only 로 patch 한다.
# playwright import 보다 *먼저* 해야 효과 있음.
from .. import chrome_launcher as _cl  # noqa: F401  (side-effect import)

from ..browser import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

from ..dom import first_visible, read_page_state
from . import selectors as S

LOGGER = logging.getLogger("ktx_watcher_spa.korail.client")

# KTXA_HUMANIZE 는 .env.ktx 에서도 읽어야 함 — import 시점 평가라 env 파일 선로드 필요
from ..config import _load_env_files as _hload

_hload()
HUMANIZE = os.getenv("KTXA_HUMANIZE", "true").lower() not in ("false", "0", "no")


# ─────────────────── humanization helpers ───────────────────

def human_pause(min_s: float = 0.5, max_s: float = 1.2) -> None:
    if HUMANIZE:
        # 사용자 지시(2026-05-14): 0.5s 최소 + 랜덤 텀
        lo = max(min_s, 0.5)
        hi = max(max_s, lo + 0.5)
        time.sleep(random.uniform(lo, hi))


def human_click(loc) -> None:
    """Send only the actual click; retain pauses between user actions."""
    loc.click()
    if HUMANIZE:
        time.sleep(0.5 + random.uniform(0.0, 1.0))


def human_type(loc, text: str) -> None:
    """Fill once instead of issuing keyboard commands for every character."""
    loc.fill(text)
    if HUMANIZE:
        time.sleep(random.uniform(0.25, 0.5))


def _attach_popup_guard(page: Page) -> None:
    """Use one context handler instead of handling each popup twice."""
    attach_context_popup_guard(page.context)


class KorailSPAClient(AbstractContextManager["KorailSPAClient"]):
    """CDP-only Korail driver.

    Args:
        cdp_url: ``http://localhost:9222`` 등. ChromeLauncher 가 만든 URL.
    """

    def __init__(self, cdp_url: str) -> None:
        if not cdp_url:
            raise ValueError("cdp_url is required (CDP-only variant)")
        self.cdp_url = cdp_url
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._main_page: Optional[Page] = None

    def __enter__(self) -> "KorailSPAClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        if self._browser is not None:
            return
        self._pw = sync_playwright().start()
        ws_url = self._resolve_ws_url()
        LOGGER.info("CDP 연결: %s (via ws=%s)", self.cdp_url, ws_url)
        self._browser = self._pw.chromium.connect_over_cdp(ws_url or self.cdp_url)
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
        else:
            self._context = self._browser.new_context()
        LOGGER.info(
            "CDP 연결 OK (contexts=%d pages=%d)",
            len(self._browser.contexts),
            len(self._context.pages),
        )
        # context-level popup guard 부착 — 어디서 popup 이 생기든 자동 확인 클릭
        attach_context_popup_guard(self._context)

    def _resolve_ws_url(self) -> Optional[str]:
        """Chrome 의 /json/version 에서 webSocketDebuggerUrl 을 직접 받는다."""
        import json
        import urllib.request
        if self.cdp_url.startswith(("ws://", "wss://")):
            return self.cdp_url
        try:
            # NOTE: Chrome 은 Host=127.0.0.1 거부 → URL 호스트는 'localhost' 로
            base = self.cdp_url.rstrip("/")
            if base.startswith("http://127.0.0.1"):
                base = base.replace("http://127.0.0.1", "http://localhost")
            with urllib.request.urlopen(f"{base}/json/version", timeout=5.0) as resp:
                data = json.loads(resp.read())
            ws = data.get("webSocketDebuggerUrl")
            if ws:
                # ws 도 호스트 표기 정리 (Chrome 이 ::1 listen 못할 수 있음 → 127.0.0.1)
                ws = ws.replace("ws://localhost:", "ws://127.0.0.1:")
                return ws
        except Exception as e:
            LOGGER.warning("webSocketDebuggerUrl 해석 실패, cdp_url 그대로 사용: %s", e)
        return None

    def stop(self) -> None:
        # CDP 모드에선 context/browser 를 close 하지 않는다 (사용자 Chrome 그대로 유지).
        try:
            if self._browser:
                # disconnect 만 (close 는 사용자 Chrome 까지 죽임)
                pass
        finally:
            self._browser = None
            self._context = None
            self._main_page = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Client not started")
        return self._context

    def main_page(self) -> Page:
        """사용할 메인 page. 없으면 새로 만든다. popup guard 자동 부착."""
        ctx = self.context
        if self._main_page is not None and not self._main_page.is_closed():
            return self._main_page
        page: Optional[Page] = None
        # 가장 적합한 page = korail.com 또는 about:blank
        for p in ctx.pages:
            try:
                url = p.url or ""
            except Exception:
                continue
            if "korail.com" in url or url.startswith("about:") or url == "":
                page = p
                break
        if page is None:
            page = ctx.new_page()
        self._main_page = page
        return page


# ─────────────────── safe navigation helpers ───────────────────

def safe_goto(page: Page, url: str, timeout_ms: int = 30_000) -> None:
    try:
        page.goto(url, wait_until="load", timeout=timeout_ms)
    except PWTimeoutError as e:
        from . import SiteLayoutChanged
        raise SiteLayoutChanged(f"goto timeout: {url}") from e


def _click_visible(page: Page, selector: str, timeout: int = 2000) -> bool:
    button = first_visible(page, selector)
    if not button.is_visible():
        return False
    button.click(timeout=timeout)
    return True


def dismiss_macro_notice(page: Page) -> bool:
    try:
        state = read_page_state(page)
        if not any(kw in state["body"] for kw in S.MACRO_NOTICE_KEYWORDS):
            return False
        clicked = _click_visible(page, S.MODAL_CONFIRM_BUTTON)
        if clicked:
            human_pause(0.8, 1.4)
        return clicked
    except Exception:
        return False


def dismiss_notice_modal(page: Page) -> bool:
    try:
        state = read_page_state(page)
        if not any(kw in state["body"] for kw in S.NOTICE_MODAL_KEYWORDS):
            return False
        _click_visible(page, S.NOTICE_MODAL_HIDE_TODAY_CHECKBOX, timeout=1500)
        clicked = _click_visible(page, S.NOTICE_MODAL_DISMISS_BUTTON)
        if clicked:
            human_pause(0.6, 1.0)
        return clicked
    except Exception:
        return False


def dismiss_any_modal(page: Page) -> bool:
    try:
        clicked = _click_visible(page, S.MODAL_CONFIRM_BUTTON)
        if clicked:
            human_pause(0.6, 1.2)
        return clicked
    except Exception:
        return False


_INFO_KEYWORDS = S.MACRO_NOTICE_KEYWORDS + (
    "안내",
    "이용안내",
    "확인하시고",
    "선택하신",
    "예매",
    "본인인증",
    "약관",
)

# "계속 진행하시겠습니까?" 류 진행 확인 모달 (아니오/네) → '네' 클릭으로 통과.
# 2026-08-19 실측: "정차역 수가 적어 가격이 최대 0.6% 높습니다. 계속 진행하시겠습니까?"
# 이 문구 없이 '네' 를 누르면 취소류 모달을 오확인할 수 있어 키워드 필수.
_PROCEED_KEYWORDS = ("진행하시겠습니까",)


def _click_proceed_if_asked(pg: Page, txt: str) -> bool:
    """모달 텍스트가 진행 확인형이면 '네' 클릭. 성공 시 True."""
    if not any(kw in txt for kw in _PROCEED_KEYWORDS):
        return False
    try:
        if _click_visible(pg, S.MODAL_PROCEED_BUTTON):
            human_pause(0.5, 0.9)
            return True
    except Exception as e:
        LOGGER.debug("Proceed confirmation failed: %s", e)
    return False


def dismiss_all_popups(context) -> int:
    """**공통 popup 핸들러** — 현재 떠 있는 모든 page/popup 의 안내 모달 '확인' 클릭.

    page-level on('popup') 만 의지하면 timing race condition 으로 놓치는 경우가
    있어 매 action 후 명시적으로 호출. context.pages 를 snapshot 해서 순회.
    """
    count = 0
    try:
        pages = list(context.pages)
    except Exception:
        return 0
    for pg in pages:
        try:
            if pg.is_closed():
                continue
        except Exception:
            continue

        try:
            state = read_page_state(pg)
        except Exception:
            continue
        body = state["body"]
        if not any(kw in body for kw in _INFO_KEYWORDS):
            continue
        modal_txt = next(iter(state["modals"]), "")

        if _click_proceed_if_asked(pg, modal_txt or body):
            count += 1
            continue

        try:
            if _click_visible(pg, S.MODAL_CONFIRM_BUTTON):
                count += 1
                human_pause(0.5, 0.9)
        except Exception:
            continue
    return count


def attach_context_popup_guard(context) -> None:
    """context.on('page') 로 모든 새 page (popup 포함) 자동 dismiss.

    page-level on('popup') 보다 광범위. 어디서 popup 이 생기든 잡음.
    """
    if getattr(context, "_popup_guard_attached", False):
        return

    def _on_page(new_page: Page) -> None:
        # A tab created by the client is not an advertising popup.
        if new_page.opener() is None:
            return
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        try:
            body = read_page_state(new_page)["body"]
        except Exception:
            body = ""
        if not any(kw in body for kw in _INFO_KEYWORDS):
            # 광고/외부 popup — close
            try:
                if "korail" not in (new_page.url or "") and not new_page.is_closed():
                    LOGGER.info("외부/광고 popup close: %s", new_page.url)
                    new_page.close()
            except Exception:
                pass
            return

        # 안내성 popup → 진행 확인형이면 '네', 아니면 '확인' 클릭
        LOGGER.info("새 popup 감지 (안내성) → 확인 클릭: %s body=%r", new_page.url, body[:60])
        if _click_proceed_if_asked(new_page, body):
            return
        try:
            time.sleep(random.uniform(0.5, 1.0))
            _click_visible(new_page, S.MODAL_CONFIRM_BUTTON, timeout=3000)
        except Exception as e:
            LOGGER.debug("popup 확인 클릭 실패: %s", e)

    context.on("page", _on_page)
    context._popup_guard_attached = True  # type: ignore[attr-defined]
    LOGGER.info("context popup guard 부착 (context.on('page'))")


__all__ = [
    "KorailSPAClient",
    "_attach_popup_guard",
    "safe_goto",
    "dismiss_macro_notice",
    "human_pause",
    "human_click",
    "human_type",
    "HUMANIZE",
]
