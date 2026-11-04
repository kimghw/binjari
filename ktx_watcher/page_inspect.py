"""Korail SPA 주요 페이지 캡쳐 + 메뉴/액션 DOM 정보 수집.

각 페이지마다:
  1. full-page 스크린샷
  2. GNB / 본문 주요 버튼 텍스트 / 입력 폼 / 모달 (있으면)
  3. URL + title

결과:
  - runs/pages/<slug>.png
  - ktx_watcher_spa/PAGES.md (요약)

사용법:
  python -m ktx_watcher_spa.page_inspect
환경변수: KTXA_CDP_PORT, KTXA_CDP_USER_DATA_DIR, KTXA_USER, KTXA_PASS
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from .chrome_launcher import ChromeLauncher
from .config import ConfigError, load_config
from .korail.client import (
    KorailSPAClient,
    dismiss_macro_notice,
    human_click,
    human_pause,
    safe_goto,
)
from .korail import selectors as S
from .korail.reserve import ensure_logged_in

LOGGER = logging.getLogger("ktx_watcher_spa.page_inspect")

RUNS_DIR = Path("./runs/pages")
DOC_PATH = Path("./ktx_watcher_spa/PAGES.md")


def _collect_interactive(page) -> dict:
    """페이지 상의 클릭 가능한 요소들 (a, button, [role=tab]) 텍스트 수집."""
    return page.evaluate(
        """() => {
            const collect = (root, sel) => {
                const out = [];
                const seen = new Set();
                root.querySelectorAll(sel).forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
                    if (!text || text.length < 1 || text.length > 80) return;
                    if (seen.has(text)) return;
                    seen.add(text);
                    out.push({
                        tag: el.tagName.toLowerCase(),
                        text: text,
                        href: el.getAttribute('href'),
                        cls: (el.className || '').toString().slice(0, 60),
                        x: Math.round(r.x), y: Math.round(r.y),
                    });
                });
                return out;
            };

            const result = {
                title: document.title,
                url: location.href,
                gnb: [],
                main: [],
                tabs: [],
                forms: [],
                modal: null,
            };

            // GNB — header / nav 영역
            const header = document.querySelector('header, .gnb_wrap, .header') || document.body;
            result.gnb = collect(header, 'a, button').slice(0, 25);

            // 본문 주요 액션 — header 제외 영역의 button + 텍스트 anchor
            const main = document.querySelector('main, [role=main], .sub_content, .container') || document.body;
            result.main = collect(main, 'button, a.btn_pop, a.btn_lookup, a:has(button)').slice(0, 30);

            // 탭
            result.tabs = collect(document.body, '[role=tab], .tab_bar button, .tab_bar a, ul.tab_bar li').slice(0, 15);

            // 입력 폼
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                const info = {
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    value: (el.value || '').slice(0, 50),
                    readonly: el.readOnly,
                };
                if (info.name || info.id || info.placeholder) result.forms.push(info);
            });

            // 모달
            const modal = document.querySelector('.ReactModal__Content, [role=dialog]');
            if (modal) {
                const r = modal.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    result.modal = {
                        text: (modal.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 300),
                        buttons: collect(modal, 'button, a'),
                    };
                }
            }
            return result;
        }"""
    )


def _md_section(slug: str, label: str, url: str, info: dict, screenshot_rel: str) -> str:
    lines: List[str] = []
    lines.append(f"## {label}")
    lines.append("")
    lines.append(f"- URL: `{url}`")
    lines.append(f"- Title: {info.get('title', '')}")
    lines.append(f"- 스크린샷: [{screenshot_rel}]({screenshot_rel})")
    lines.append("")

    if info.get("modal"):
        lines.append("### 떠 있는 모달")
        lines.append("")
        lines.append(f"- 본문: {info['modal']['text']}")
        btns = info["modal"].get("buttons") or []
        if btns:
            lines.append(f"- 버튼: {', '.join(b['text'] for b in btns)}")
        lines.append("")

    if info.get("gnb"):
        lines.append("### GNB / 헤더 메뉴")
        lines.append("")
        for x in info["gnb"]:
            href = x.get("href")
            href_s = f" → `{href}`" if href and href != "#" and href != "#none" else ""
            lines.append(f"- `{x['tag']}` **{x['text']}**{href_s}")
        lines.append("")

    if info.get("tabs"):
        lines.append("### 탭 / 필터")
        lines.append("")
        for x in info["tabs"]:
            lines.append(f"- `{x['tag']}` **{x['text']}**")
        lines.append("")

    if info.get("main"):
        lines.append("### 본문 주요 액션")
        lines.append("")
        for x in info["main"]:
            lines.append(f"- `{x['tag']}` **{x['text']}** (cls=`{x['cls']}`)")
        lines.append("")

    if info.get("forms"):
        lines.append("### 입력 필드")
        lines.append("")
        for f in info["forms"]:
            ident = f.get("name") or f.get("id") or f.get("placeholder")
            ro = " readonly" if f.get("readonly") else ""
            val = f.get("value") or ""
            val_s = f" value=`{val}`" if val else ""
            ph = f.get("placeholder") or ""
            ph_s = f" placeholder=`{ph}`" if ph else ""
            lines.append(f"- `{f['tag']}[type={f['type']}]` **{ident}**{ro}{val_s}{ph_s}")
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _capture(page, slug: str, label: str) -> tuple[str, dict]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    png_path = RUNS_DIR / f"{slug}.png"
    page.screenshot(path=str(png_path), full_page=True)
    info = _collect_interactive(page)
    LOGGER.info("[capture] %s url=%s screenshot=%s", label, info.get("url"), png_path)
    rel = png_path.as_posix().replace("./", "../")
    return rel, info


def main() -> int:
    try:
        config = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.ktxa_log_level,
        format="%(asctime)s | %(message)s",
        stream=sys.stdout,
    )

    launcher = ChromeLauncher(
        port=config.ktxa_cdp_port,
        user_data_dir=config.ktxa_cdp_user_data_dir,
        exe_path=config.ktxa_chrome_exe,
    )
    cdp_url = launcher.ensure_running()
    LOGGER.info("CDP %s", cdp_url)

    sections: List[str] = []
    sections.append("# Korail SPA — 페이지별 메뉴/액션 카탈로그")
    sections.append("")
    sections.append(f"_자동 생성 (page_inspect.py, {time.strftime('%Y-%m-%d %H:%M')})_")
    sections.append("")
    sections.append("---")
    sections.append("")

    try:
        with KorailSPAClient(cdp_url) as client:
            page = client.main_page()

            # 1) /ticket/main (미로그인 상태)
            safe_goto(page, S.MAIN_URL, timeout_ms=30_000)
            human_pause(1.5, 2.5)
            dismiss_macro_notice(page)
            rel, info = _capture(page, "01-main-anon", "메인 (미로그인)")
            sections.append(_md_section("01-main-anon", "1. 메인 페이지 (미로그인)", info["url"], info, rel))

            # 2) /ticket/login (폼 노출)
            safe_goto(page, S.LOGIN_URL, timeout_ms=30_000)
            human_pause(1.5, 2.5)
            dismiss_macro_notice(page)
            rel, info = _capture(page, "02-login", "로그인 페이지")
            sections.append(_md_section("02-login", "2. 로그인 페이지", info["url"], info, rel))

            # 3) 로그인 시도 (자격증명 있을 때만)
            if config.ktxa_user and config.ktxa_pass:
                try:
                    ensure_logged_in(client, config)
                    safe_goto(page, S.MAIN_URL, timeout_ms=30_000)
                    human_pause(1.5, 2.5)
                    dismiss_macro_notice(page)
                    rel, info = _capture(page, "03-main-logged-in", "메인 (로그인 후)")
                    sections.append(_md_section("03-main-logged-in", "3. 메인 페이지 (로그인 후)", info["url"], info, rel))
                except Exception as e:
                    LOGGER.warning("로그인 실패: %s", e)

            # 4) /ticket/search/general
            safe_goto(page, S.SEARCH_URL, timeout_ms=30_000)
            human_pause(1.5, 2.5)
            dismiss_macro_notice(page)
            rel, info = _capture(page, "04-search-general", "검색 폼")
            sections.append(_md_section("04-search-general", "4. 검색 폼 페이지", info["url"], info, rel))

            # 5) /ticket/search/list — 검색 결과 (실제 검색을 한 번 수행)
            try:
                from .korail.search import fill_search_form, submit_search, _click_train_type_tab
                fill_search_form(page, config)
                submit_search(page, config)
                # 두 번째 검색으로 결과 row 보이게
                safe_goto(page, S.SEARCH_URL, timeout_ms=30_000)
                human_pause(2.0, 3.0)
                # 검색 버튼 한번 더
                page.locator(S.SEARCH_SUBMIT).first.click()
                human_pause(3.0, 4.5)
                dismiss_macro_notice(page)
                _click_train_type_tab(page, config.ktxa_train_type or "KTX")
                human_pause(1.5, 2.5)
                rel, info = _capture(page, "05-search-list", "검색 결과 (KTX 탭)")
                sections.append(_md_section("05-search-list", "5. 검색 결과 페이지 (KTX 탭)", info["url"], info, rel))

                # 6) 예약하기 클릭 시도
                try:
                    btn = page.locator(S.RESERVE_BUTTON_GENERAL).first
                    if btn.count() > 0:
                        human_click(btn)
                        human_pause(3.0, 5.0)
                        dismiss_macro_notice(page)
                        rel, info = _capture(page, "06-reserve-next", "예약하기 클릭 후")
                        sections.append(_md_section("06-reserve-next", "6. 예약하기 클릭 후 페이지", info["url"], info, rel))
                except Exception as e:
                    LOGGER.warning("예약하기 단계 캡쳐 실패: %s", e)
            except Exception as e:
                LOGGER.warning("검색 결과 캡쳐 실패: %s", e)

            # 7) 마이페이지 GNB
            try:
                safe_goto(page, "https://www.korail.com/mypage", timeout_ms=15_000)
                human_pause(2.0, 3.0)
                dismiss_macro_notice(page)
                rel, info = _capture(page, "07-mypage", "마이페이지")
                sections.append(_md_section("07-mypage", "7. 마이페이지", info["url"], info, rel))
            except Exception as e:
                LOGGER.warning("마이페이지 캡쳐 실패: %s", e)

    finally:
        launcher.shutdown_if_owned()

    DOC_PATH.write_text("\n".join(sections), encoding="utf-8")
    print(f"\n✓ Pages catalog written to: {DOC_PATH}")
    print(f"✓ Screenshots in: {RUNS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
