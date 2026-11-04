# KTX Watcher — 사이트별 흐름 트러블슈팅

CDP 연결 / Chrome 환경 트러블은 [WORKFLOW.md §3-1](WORKFLOW.md#3-1-cdp--chrome-환경-troubleshooting-1-7-통합) 로 통합됨.
본 문서는 **Korail SPA 흐름 자체** (검색/예약/결제 selectors, popup, 매크로 가드)
에서 만난 사이트 특성 이슈만 보관.

2026-11-04 조회 차단 재검증과 CDP·UIA·Claude Code 현황은
[최신 분석 기록](QUERY_AUTOMATION_ANALYSIS_2026-11-04.md)을 참고한다.

---

## 1. 날짜 선택기의 불필요한 조작 줄이기 — 차단 원인 단정 정정

- 기존 개선: `input#startDate` 현재 값이 target과 일치하면 picker를 생략한다.
- 2026-11-04 재검증: picker를 생략한 조회에서도 `-8002`가 발생했다.
  반복 날짜 클릭을 이번 차단의 확정 원인으로 볼 수 없다.
- 같은 값의 반복 조작을 줄이는 개선은 유지하되, 차단 여부는 실제 응답·안내로 판단한다.
- 위치: `korail/search.py:_set_date`

## 2. KTX 탭 selector 가 GNB 'KTX 마일리지' 메뉴 매칭 ✓
- 증상: `button:has-text('KTX')` 가 `<a class="gnb_dep3">KTX 마일리지＆회원쿠폰</a>` 잡음.
  hidden anchor 라 30s timeout.
- 해결: 결과 영역 한정 selector `ul.tab_bar button:has(div.korail_logo_tab)`.
- 위치: `korail/selectors.py:TRAIN_TYPE_TAB`

## 3. 결과 row '예약 버튼' 이 실은 anchor 선택용 ✓
- 증상: row 안에 `<button>` 없음. `<a href="#none">` 만 있고 `a.onclick = function cn(){}`
  빈 함수. CDP `.click()`, `mouse.click(x,y)` 모두 페이지 변화 없음.
- 사용자 검증: 직접 클릭하니 row 가 **선택**만 되고 (파란 하이라이트), 별도 하단
  "예매" 버튼이 진짜 트리거.
- 해결: **2단계 클릭**
  1. row 가격 anchor 클릭 (selection)
  2. `button.reservbtn` 클릭 (진짜 예약 진입)
- 위치: `korail/reserve.py:attempt_reservation`, `korail/selectors.py:BOOK_NOW_BUTTON`

## 4. "예매" 클릭 후 '이용안내' 별도 popup window ✓
- 증상: `button.reservbtn` 클릭하면 별도 Chrome 윈도우 (`window.open`) 로 "이용안내"
  ("선택하신 열차는 KTX-산천 2개 편성을 연결...") 모달. 메인 page 의 ReactModal 이 아님.
- 1차 시도 실패 원인: `page.on('popup')` 만 의지 → listener 가 비동기 처리하는 동안
  메인 흐름이 다음 step 으로 가서 race condition.
- 해결: **공통 popup 핸들러**
  - `context.on('page')` 로 부착 — page-level 보다 광범위 (어디서 popup 떠도 잡음)
  - 매 클릭 후 명시적 `dismiss_all_popups(context)` polling (1초 간격 6~15회)
  - 안내 키워드 (`안내`, `CODE`, `이용안내`, `확인하시고`, `선택하신`, `본인인증`, `약관`)
    매칭 시 "확인" 클릭
- 위치: `korail/client.py:attach_context_popup_guard`, `dismiss_all_popups`

## 5. confirm_buttons 의 '다음' 매칭이 '다음날 조회' 버튼 ✓
- 증상: attempt_reservation 의 후속 단계가 `button:has-text('다음')` 으로 매칭 →
  화면 하단 `button.btn_bn-blue.btn_lookup` "다음날(MM월DD일)조회" 잡음.
  잘못된 "예약 단계 통과" 로그.
- 해결: 정확한 `button.reservbtn` selector 사용 (2단계 흐름으로 재작성).

## 6. row 텍스트의 status 추출이 일반실 split 만 ✓
- 증상: 매진 row 의 status_col 빈 문자열 → 후보 0건.
- 원인: row text 에 "일반실" 단어가 없는 경우 (예: "입석 + 좌석매진") 가 있음.
- 해결: "일반실" 없으면 row 전체 텍스트를 status 로. 필터에서 매진 키워드 검사.
- 위치: `korail/search.py:_parse_result_rows`

## 7. status 필터 키워드가 "예약하기/좌석선택/예매/입석" 뿐 ✓
- 증상: 가격(원) 표시된 예약 가능 row 가 후보 안 됨.
- 원인: row text 에 "예약하기" 버튼 텍스트 없음. 가격(원) 자체가 클릭 트리거.
- 해결: "원" 키워드 또는 명시적 예약 키워드 + "매진" (매진임박 제외) 으로 판정.
- 위치: `korail/search.py:perform_search` 후보 필터 분기

## 8. KTXA_ONCE=true와 차단 후 재조회

- 과거 증상: 첫 차단 안내를 닫고 재조회하지 않아 빈 결과로 종료했다.
- 현재는 검색 함수 안에서 조건을 검증하고 제한된 재조회를 수행한다. ONCE를 끄는 것만으로
  해결된다고 안내하지 않는다. 차단 이후 복구 성공과 첫 제출 성공은 별도로 기록한다.

## 9. row anchor 매진 row 가 선택될 수 있음 (filter 한계) ⚠
- 증상: `locator("a").filter(has_text="일반실").filter(has_text="원").filter(has_not_text="매진")`
  에서 anchor 자체 텍스트는 "일반실23,700원5%적립" 인데, has_not_text 가 anchor 만
  보니까 매진 row 의 일반실 anchor 도 매치.
- 부분 해결: target.depart (HH:MM) 매칭으로 row 컨테이너에서 시간 일치 확인.
- 미해결 가능성: 그래도 잘못 row 선택 가능. row scoping 더 정교화 필요.

## 10. 결제 페이지의 동의 체크박스 #check 이 label 가로챔 ✓
- 증상: `input#check` 클릭 시 `<label for="check">동의함</label>` intercepts pointer events.
- 해결: `chk.check()` 호출이 자동으로 label 우회. 실패해도 try/except 로 계속 진행
  (대부분 사이트가 default 체크 상태).
- 위치: `korail/payment.py:perform_payment`

## 11. 결제 페이지 default 탭이 카드결제 아닐 수 있음 ✓
- 증상: 결제 페이지 진입 시 default 탭이 "간편현금결제" 또는 다른 탭. 카드 입력 필드 안 보임.
- 해결: `_click_card_payment_tab()` 으로 명시적 카드결제 탭 클릭. 이미 active 면 skip.
- 위치: `korail/payment.py:_click_card_payment_tab`

## 12. cardYear 필드가 select 또는 input ⚠
- 증상: KTX 결제 페이지의 연도 필드가 환경에 따라 `<select>` 일 수도 `<input>` 일 수도.
- 해결: 양쪽 fallback — `select.select_option(value=yy2 → yyyy → label=yyyy)` 시도 후
  실패 시 `input.fill(maxLength 에 따라 yy2 또는 yyyy)`.
- 위치: `korail/payment.py:_set_card_year`
- 미확정: 실제 어느 케이스가 default 인지 추가 검증 필요.

## 13. -8002 명시적 차단과 조건을 유지한 재조회 — 2026-11-04 정정

- 보호 경로 `/web_s/...`로 요청이 전송됐고 HTTP 200 본문에
  `FAIL / macro_err1 / dynaPathResultCode=-8002`가 반환됐다.
- 같은 브라우저에서 새 폼 제출 시 반복됐다. “최초 1회성”, “목록 XHR 미전송” 설명은 철회한다.
- `_requery_after_guard`는 조건을 검증하고 결과 조회 버튼이 보이면 클릭하며,
  그렇지 않으면 현재 결과 페이지를 새로고침한다. 실험에서는 전체 새로고침 후 정상 목록을 받았다.
- 명시적 차단은 `GuardBlocked`, 차단 문구 없는 빈 목록은 `SearchResultUnavailable`로 구분한다.
  재시도 횟수 제한과 조회 조건 검증을 유지한다. 날짜를 다음날로 바꾸어 복구하지 않는다.
- 안내를 닫기 전에 증거를 남긴다. CDP 개별 시험 성공과 UIA 제출 비교는
  [분석 기록](QUERY_AUTOMATION_ANALYSIS_2026-11-04.md)에 정리했다.
- 위치: `korail/search.py:_requery_after_guard`, `submit_search`, `perform_search`

## 14. '더보기' 가 button 이 아니라 anchor — 확장이 조용히 중단 ✓
- 증상: `후보 0건 (전체 row 10건)`. 첫 화면 10행(05:13~07:27)만 파싱되고 KTXA_TIMES
  (09:00) 구간은 아예 안 읽힘.
- 원인: `page.get_by_role("button", name="더보기")` 가 0건. 실제 DOM 은
  `<a class="page_group"><span>더보기</span></a>`. 루프가 debug 로그만 남기고 break.
- 해결: `RESULT_MORE_BUTTON = "a.page_group:has-text('더보기')"`, 미발견 시 warning.
  적용 후 10→40행, 양성 대조(TOLERANCE 240)에서 10:18 KTX 일반실 후보 추출 확인.
- 위치: `korail/selectors.py:RESULT_MORE_BUTTON`, `korail/search.py:_expand_more_until`

---

# 참조

- 환경/CDP 트러블: [WORKFLOW.md §3-1](WORKFLOW.md#3-1-cdp--chrome-환경-troubleshooting-1-7-통합)
- 전체 흐름: [WORKFLOW.md §1](WORKFLOW.md#1-전체-흐름-한눈에)
- 운영 체크리스트: [WORKFLOW.md §6](WORKFLOW.md#6-운영-체크리스트)
- 페이지별 메뉴 카탈로그: [PAGES.md](PAGES.md)
