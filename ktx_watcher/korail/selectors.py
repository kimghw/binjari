"""Korail SPA selectors.

**모두 live-verified 2026-05-14** — CDP 직접 DOM probe 로 확정한 것만 보관한다.
번들 정적 분석 추측은 제외 (이전 variant 에서 false-match 가 너무 많았음).
"""

# ───────────────────────── URLs ──────────────────────────
SEARCH_URL = "https://www.korail.com/ticket/search/general"
RESULT_URL_PATTERN = "**/search/list*"
LOGIN_URL = "https://www.korail.com/ticket/login"
MAIN_URL = "https://www.korail.com/ticket/main"

# ─────────────────── 검색 폼 (search/general) ───────────────────
ORIGIN_INPUT = "input[name='txtGoStart']"
DEST_INPUT = "input[name='txtGoEnd']"
ORIGIN_BTN = ".selectAreaWrap .start a.btn_pop-open"
DEST_BTN = ".selectAreaWrap .end a.btn_pop-open"
DATE_INPUT = "input#startDate"
DATE_PICKER_BTN = "a.btn_pop.btn_d-day"
SEARCH_SUBMIT = "button.btn_lookup"
SEARCH_FORM_DETECT = "button.btn_lookup, input[name='txtGoStart']"
# SRT 포함 옵션 — VERIFIED 2026-11-03 (CDP DOM probe)
#   사이트에서 "에스알티(SRT) 함께 보기"(srtCheckYn) 가 사라지고 SRT 가 KTX 탭에 통합됨.
#   수서 발착(SRT) 열차는 "서울·용산 - 수서 함께 보기"(adjStnScdlOfrFlg2) 로 포함한다.
#   폼(search/general): 숨김 옵션 영역(.selectAreaWrap.inline, display:none) 안 라디오
#     <input type="radio" id="option05" name="adjStnScdlOfrFlg2" value="Y">  포함
#     <input type="radio" id="option06" name="adjStnScdlOfrFlg2" value="N">  미포함
#     → hidden 이라 JS click 으로 토글. SPA 가 폼 값을 세션 내 유지하므로 Y/N 둘 다 명시.
#   결과(search/list): <input type="checkbox" id="adjStnScdlOfrFlg2"> + label[for] (클릭 시 재조회)
SRT_RADIO_Y = "input[name='adjStnScdlOfrFlg2'][value='Y']"
SRT_RADIO_N = "input[name='adjStnScdlOfrFlg2'][value='N']"
SRT_RESULT_CHECKBOX = "input#adjStnScdlOfrFlg2[type='checkbox']"
SRT_RESULT_CHECKBOX_LABEL = "label[for='adjStnScdlOfrFlg2']"

# 인원 선택 팝업 — VERIFIED 2026-07-07 (CDP DOM probe)
#   폼의 <a class="data btn_pop">총 1명</a> 클릭 → .layerWrap.personnel_pop_wrap
#   <li><p>경로(65세 이상)</p><div class="flo_right">
#     <button class="down_num" [disabled]>...<span>0</span><button class="up_num">
#   하단 <button class="btn_bn-blue">적용</button> / <button class="btn_pop-close">취소</button>
PEOPLE_BTN = "a.data.btn_pop"
PEOPLE_POPUP = ".layerWrap.personnel_pop_wrap"
PEOPLE_POPUP_APPLY = ".layerWrap.personnel_pop_wrap .btnWrap button.btn_bn-blue"
PEOPLE_POPUP_CANCEL = ".layerWrap.personnel_pop_wrap .btnWrap button.btn_pop-close"
# 비어른 구성 적용 시 확인 모달 "경로 : 1명 / 선택하신 인원이 확실한가요?" → 예
# (VERIFIED 2026-07-07 — 별도 .layerWrap + .confirm_message 로 뜸)
PEOPLE_CONFIRM_YES = ".layerWrap:has(.confirm_message) button.btn_bn-blue"
# config 유형명 → 팝업 li <p> 라벨 prefix ("경로(65세 이상)", "중증 장애인" 등)
PASSENGER_TYPE_PREFIX = {
    "어른": "어른",
    "어린이": "어린이",
    "유아": "유아",
    "경로": "경로",
    "중증장애인": "중증",
    "경증장애인": "경증",
    "국가유공자": "국가유공자",
}

# 역 선택 팝업
STATION_POPUP = ".layerWrap.type_tranin-station-pop_wrap"
STATION_POPUP_INPUT = "input[name='searchTxt']"
STATION_POPUP_OPTION = ".layerWrap.type_tranin-station-pop_wrap span.ch_tag a"
STATION_POPUP_CLOSE = ".layerWrap.type_tranin-station-pop_wrap .btn_close"

# 날짜 picker
DATE_POPUP = ".layerWrap.type_date-pop_wrap"
DATE_POPUP_DAYS = ".layerWrap.type_date-pop_wrap .datepicker tbody td:not(.disabled) a[aria-disabled='false']"
DATE_POPUP_HOURS = ".layerWrap.type_date-pop_wrap .timeSelect a"
DATE_POPUP_NEXT = ".layerWrap.type_date-pop_wrap .slick-arrow.slick-next"
DATE_POPUP_PREV = ".layerWrap.type_date-pop_wrap .slick-arrow.slick-prev"
DATE_POPUP_APPLY = ".layerWrap.type_date-pop_wrap .btn_wrap button.btn_bn-blue"
DATE_POPUP_CANCEL = ".layerWrap.type_date-pop_wrap .btn_wrap button.btn_pop-close"

# ─────────────────── 결과 페이지 (search/list) ───────────────────
RESULT_PAGE_DETECT = ".sub_content.tab-tck_view, ul.tab_bar.type4, .tck_confirm_no-data"
RESULT_EMPTY_TEXT = "해당 스케줄에 운행하는 열차가 없습니다"
RESULT_EMPTY_MARKER = ".tck_confirm_no-data"

# 열차 종류 필터 탭 — VERIFIED 2026-05-14 (CDP elementFromPoint probe)
#   <ul class="tab_bar type4 clear fl-l">
#     <li><button class="all">전체</button></li>
#     <li><button><div class="korail_logo_tab">KTX/KTX-산천</div></button></li>
#     <li><button><div class="saemaeul_logo_tab">새마을호/ITX-새마을</div></button></li>
#     <li><button><div class="mugung_logo_tab">무궁화호/누리로</div></button></li>
#     <li><button><div class="chung_logo_tab">ITX-청춘</div></button></li>
#   </ul>
TRAIN_TYPE_TAB = {
    "전체": "ul.tab_bar button.all",
    "KTX": "ul.tab_bar button:has(div.korail_logo_tab)",
    "KTX-산천": "ul.tab_bar button:has(div.korail_logo_tab)",
    "새마을": "ul.tab_bar button:has(div.saemaeul_logo_tab)",
    "ITX-새마을": "ul.tab_bar button:has(div.saemaeul_logo_tab)",
    "무궁화": "ul.tab_bar button:has(div.mugung_logo_tab)",
    "누리로": "ul.tab_bar button:has(div.mugung_logo_tab)",
    "ITX-청춘": "ul.tab_bar button:has(div.chung_logo_tab)",
}

# ─────────────────── 매크로 안내 모달 / 팝업 ───────────────────
# 두 가지 형태로 뜬다 (live observed):
#   (A) 별도 Chrome window.open 팝업 → page.on('popup') 으로 잡힘
#   (B) 메인 페이지 .ReactModalPortal > .ReactModal__Content
MACRO_NOTICE_KEYWORDS = (
    "CODE : -8002",
    "CODE : -8003",
    "안내 메시지",
    "매크로 등 미허가",
    "매크로 등의 프로그램",
    "비정상적인 접속",
)
MODAL_CONFIRM_BUTTON = "button:has-text('확인')"
# "계속 진행하시겠습니까?" 류 진행 확인 모달의 긍정 버튼 (아니오/네 구성).
# ':text-is' 정확 일치 — has-text 는 부분 일치라 '안내' 등에 오탐.
MODAL_PROCEED_BUTTON = "button:text-is('네'), a:text-is('네')"

# 광고/공지 모달 (예: "광명→천안아산 KTX 서행 알림" 운영기간성 공지).
# 매크로 차단과 무관 — body 에 "창닫기" / "그만보기" / "알림" 같은 키워드 + 닫기 버튼.
NOTICE_MODAL_KEYWORDS = (
    "창닫기",
    "그만보기",
)
NOTICE_MODAL_DISMISS_BUTTON = (
    "button.btn_pop-close, "
    "button:has-text('창닫기'), "
    "a:has-text('창닫기')"
)
# 모달 안의 "N일간 그만보기" 체크박스 → 체크 후 닫기 누르면 cookie 로 24시간 안 뜸.
NOTICE_MODAL_HIDE_TODAY_CHECKBOX = (
    "label:has-text('그만보기'), "
    "input[id^='popClose'][type='checkbox']"
)

# ─────────────────── 로그인 폼 ───────────────────
LOGIN_ID_INPUT = "input#id"
LOGIN_PW_INPUT = "input#password"
LOGIN_KEYSEC_CHECK = "input#useKeySec"
LOGIN_SUBMIT = ".login__form-cont button:has-text('로그인')"
LOGIN_DONE_DETECT = ".gnb_login_y, a:has-text('로그아웃')"

# ─────────────────── 결과 row (예약 단계) ───────────────────
# DOM 구조 확정 selector. CDP probe (2026-05-14):
# row 텍스트 예시:
#   "KTX 101서대구,구포정차서울 → 부산(09:33 ~ 12:53)소요시간: 3시간 20분입석 + 좌석매진"
# row 자체의 className 은 SPA 마다 바뀌므로 JS-side scan 으로 추출 (search.py 참조).
# VERIFIED 2026-05-14: 결과 row 의 예약은 *2단계* 입력.
# (1) row 의 가격 anchor (<a href="#none">) 클릭 → row 선택 (파란 하이라이트)
# (2) 화면 하단 우측 고정 영역의 button.reservbtn ("예매") 클릭 → 예약 진행
#
# anchor 텍스트 예:
#   "일반실23,700원5%적립"      (예약 가능)
#   "특실(매진임박)33,200원..."  (예약 가능)
#   "일반실23,700원5%적립매진"  (매진)
SEAT_SELECTION_ANCHOR_GENERAL = (
    "a:has-text('일반실'):has-text('원')"
)
SEAT_SELECTION_ANCHOR_SPECIAL = (
    "a:has-text('특실'):has-text('원')"
)
# 하단 우측 "예매" 버튼 (활성 상태일 때만 클릭 가능). class 가 'reservbtn' (밑줄 X).
# 'reserv_btn' (밑줄) 은 "예매 숨기기" 토글 버튼이라 다름.
BOOK_NOW_BUTTON = "button.reservbtn"
SEAT_SELECT_BUTTON = "button:has-text('좌석선택')"  # 직접 좌석 고를 때
# 매진 row 선택 시 활성화 (좌석 매진 시 대기 명단 등록).
WAITLIST_BUTTON = "button:has-text('예약대기신청')"
# "입석 + 좌석" row 선택 시 활성화.
STANDING_BUTTON = "button:has-text('입석+좌석 예매'), button:has-text('입석+좌석예매')"

# Legacy aliases (호환)
RESERVE_BUTTON_GENERAL = SEAT_SELECTION_ANCHOR_GENERAL
RESERVE_BUTTON_SPECIAL = SEAT_SELECTION_ANCHOR_SPECIAL
