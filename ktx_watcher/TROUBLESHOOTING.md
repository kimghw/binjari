# KTX Watcher — 사이트별 흐름 트러블슈팅

CDP 연결 / Chrome 환경 트러블은 [WORKFLOW.md §3-1](WORKFLOW.md#3-1-cdp--chrome-환경-troubleshooting-1-7-통합) 로 통합됨.
본 문서는 **Korail SPA 흐름 자체** (검색/예약/결제 selectors, popup, 매크로 가드)
에서 만난 사이트 특성 이슈만 보관.

---

## 1. _set_date 매번 picker 열면 매크로 가드 -8002 트리거 ✓
- 증상: polling 매 iteration 마다 "안내 메시지 CODE: -8002" 모달 + 빈 결과.
- 원인: 검색 페이지 재진입마다 `_set_date` 가 무조건 datepicker 열고 day/hour/apply
  4번 클릭. 같은 값인데도 반복 클릭하는 패턴이 봇 시그널.
- 해결: `input#startDate` 현재 값이 target 과 일치하면 picker skip.
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

## 8. KTXA_ONCE=true + -8002 첫 검색 dismiss 충돌 ✓
- 증상: 첫 검색에서 -8002 dismiss 후 빈 결과 → ONCE=true 라 종료. 두 번째 검색에서
  결과 row 나오는데 못 봄.
- 해결책 (선택): polling 모드 (`KTXA_ONCE=false`) 권장. ONCE 모드면 사전에 한 번
  검색해둔 user-data-dir 권장.

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

## 13. -8002 매크로 안내가 1회성인데 dismiss 직후 차단으로 포기 ✓
- 증상: 조회마다 `GuardBlocked` + "운행하는 열차가 없습니다", 후보 0건. 사람이 같은
  창에서 refresh/조회를 누르면 정상 목록이 나옴 (2026-11-04 실측).
- 원인: -8002 모달은 **첫 조회 제출에만** 뜬다. `submit_search` 가 모달을 닫은 직후
  재조회 없이 `GuardBlocked` 를 던져, 가드가 이미 풀린 뒤에도 영구 0건.
  네트워크 추적: 목록 XHR 자체가 안 나가고 `schedule.runDt` 까지만 호출됨 → 빈 목록은
  서버의 "열차 없음" 이 아니라 가드가 끊은 흔적. (11-03 의 '모달 없이 조용한 차단' 도
  dismiss 가 먼저 돌고 파싱한 같은 현상이었다.)
- 해결: `_requery_after_guard` — dismiss 후 `button.btn_lookup` 재클릭 → 재파싱,
  2회 재시도에도 0건일 때만 `GuardBlocked(explicit=True)`. 검색 제출·reload 경로 모두.
- 참고: 로그인 단계에서도 같은 모달이 뜰 수 있는데 `ensure_logged_in` 은
  `dismiss_macro_notice` 를 먼저 돌려 에러 문구를 `err=''` 로 잃는다. 원인 추적 시
  dismiss **전에** 모달을 캡쳐할 것 (키워드 '안내 메세지' 가 일반 에러 모달도 삼킨다).
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
