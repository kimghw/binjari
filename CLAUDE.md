# 작업 룰

## .env.ktx ↔ .env.ktx.example 동기화

- `.env.ktx` 는 **실값**(로그인·카드·Azure 시크릿) — `.gitignore`, 절대 커밋하지 않는다.
  레포에는 자리표시자만 든 **`.env.ktx.example`** 을 커밋한다.
- **설정 키를 추가/변경/삭제하면 같은 작업에서 `.env.ktx.example` 에도 반영**한다
  (실값 대신 `<설명>` 또는 안전한 기본값). 두 파일의 키 목록·주석이 항상 일치해야 한다.
- 새 머신 셋업: `.env.ktx.example` 을 `.env.ktx` 로 복사 후 `<...>` 자리에 실값 입력.

## 동작 검증 — 의도한 반응이 없으면 화면을 캡쳐해서 직접 확인

Watcher / 자동화 스크립트가 클릭 또는 navigate 후 **예상한 결과가 안 나오면**
(URL 안 바뀜, 빈 결과, 모달 안 보임 등), **즉시 CDP 로 직접 캡쳐**해서
실제 페이지 상태를 확인할 것. 추측하지 말고 본다.

루틴:

```python
from ktx_watcher.browser import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:<port>")
    pg = browser.contexts[0].pages[0]
    print("url:", pg.url, "title:", pg.title())
    # 본문 텍스트 일부
    print(pg.locator("body").inner_text(timeout=2000)[:500])
    # 모달
    for sel in (".ReactModal__Content", "[role=dialog]"):
        m = pg.locator(sel).first
        if m.count() > 0:
            print(f"modal {sel}:", m.inner_text(timeout=1000)[:300])
    # 별도 popup 페이지도 같이
    for p2 in browser.contexts[0].pages:
        print("page:", p2.url, p2.title())
    # 전체 스크린샷
    pg.screenshot(path="runs/diag.png", full_page=True)
```

추가:
- popup 윈도우인지(Chrome 별도 창) 메인 페이지의 ReactModal 인지 **반드시 구분**.
  스크린샷 제목줄에 "Google Chrome" 보이면 별도 window.open.
- CDP 의 `browser.contexts[0].pages` 는 popup 도 별도 page 객체로 노출.
- 안내/매크로 모달은 `button:has-text('확인')` 으로 dismiss 가능.

## 사용자가 직접 한 동작과 다르면 비교

자동화가 안 되고 사용자가 직접 하면 되는 경우, **무엇이 다른지** 한 액션씩 좁힌다.
사이트가 `isTrusted` 외 다른 시그널로 봇 검사할 수도 있으므로 추측 금지.
