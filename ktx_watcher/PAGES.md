# Korail SPA — 페이지별 메뉴/액션 카탈로그

_자동 생성 (page_inspect.py, 2026-05-14 10:54)_

---

## 1. 메인 페이지 (미로그인)

- URL: `https://www.korail.com/ticket/main`
- Title: 코레일 승차권예매
- 스크린샷: [runs/pages/01-main-anon.png](runs/pages/01-main-anon.png)

### GNB / 헤더 메뉴

- `a` **한국철도** → `https://info.korail.com/info/index.do`
- `a` **승차권예매** → `/ticket/main`
- `a` **기차여행** → `/tour/main`
- `a` **로그인** → `/ticket/login`
- `a` **장바구니** → `/ticket/mypage/cart`
- `a` **마이페이지** → `/ticket/mypage/mykorail`
- `a` **고객센터** → `/ticket/guest/csc`
- `a` **기업전용** → `/biz/main`
- `button` **Language**
- `a` **팝업열기**
- `a` **승차권** → `/ticket/myticket/list`
- `a` **철도역·열차** → `/ticket/train/stationGuide/station`
- `a` **고객서비스** → `/ticket/guest/notice`
- `a` **코레일멤버십** → `/ticket/membership/report`
- `button` **전체 메뉴 열기**

### 본문 주요 액션

- `button` **Language** (cls=`dropdown-button`)
- `button` **전체 메뉴 열기** (cls=`btn-allmenu`)
- `button` **Previous** (cls=`slick-arrow slick-prev`)
- `button` **Next** (cls=`slick-arrow slick-next`)
- `button` **1** (cls=``)
- `button` **2** (cls=``)
- `button` **3** (cls=``)
- `button` **정지** (cls=`btn-pause`)
- `a` **출발역 선택** (cls=`btn_pop btn_start`)
- `a` **도착역 선택** (cls=`btn_pop btn_end`)
- `a` **출발일 선택** (cls=`btn_pop btn_brth`)
- `a` **인원 선택** (cls=`btn_pop btn_recom`)
- `button` **열차 조회하기** (cls=`btn_lookup`)
- `button` **관련 사이트** (cls=`dropdown-button`)

### 입력 필드

- `input[type=text]` **labelstart** readonly value=`서울`
- `input[type=text]` **labelend** readonly value=`부산`
- `input[type=text]` **labelday** readonly value=`2026-05-14(목) 10:00`
- `input[type=text]` **labelple** readonly value=`총 1명`

---

## 2. 로그인 페이지

- URL: `https://www.korail.com/ticket/login`
- Title: 로그인>코레일 승차권예매
- 스크린샷: [runs/pages/02-login.png](runs/pages/02-login.png)

### GNB / 헤더 메뉴

- `a` **한국철도** → `https://info.korail.com/info/index.do`
- `a` **승차권예매** → `/ticket/main`
- `a` **기차여행** → `/tour/main`
- `a` **로그인** → `/ticket/login`
- `a` **장바구니** → `/ticket/mypage/cart`
- `a` **마이페이지** → `/ticket/mypage/mykorail`
- `a` **고객센터** → `/ticket/guest/csc`
- `a` **기업전용** → `/biz/main`
- `button` **Language**
- `a` **팝업열기**
- `a` **승차권** → `/ticket/myticket/list`
- `a` **철도역·열차** → `/ticket/train/stationGuide/station`
- `a` **고객서비스** → `/ticket/guest/notice`
- `a` **코레일멤버십** → `/ticket/membership/report`
- `button` **전체 메뉴 열기**

### 탭 / 필터

- `li` **회원번호**
- `li` **이메일 주소**
- `li` **휴대폰 번호**
- `li` **비회원 예매**

### 입력 필드

- `input[type=text]` **id** placeholder=`회원번호를 입력하세요`
- `input[type=password]` **password** placeholder=`비밀번호를 입력하세요`
- `input[type=checkbox]` **saveCheck** value=`on`

---

## 3. 메인 페이지 (로그인 후)

- URL: `https://www.korail.com/ticket/main`
- Title: 코레일 승차권예매
- 스크린샷: [runs/pages/03-main-logged-in.png](runs/pages/03-main-logged-in.png)

### GNB / 헤더 메뉴

- `a` **한국철도** → `https://www.korail.com/login/ssoDomainProc.do?domainURL=http://info.korail.com&domainSsoURL=https://info.korail.com&retURL=/mbs/www/`
- `a` **승차권예매** → `/ticket/main`
- `a` **기차여행** → `/tour/main`
- `a` **로그아웃**
- `a` **장바구니** → `/ticket/mypage/cart`
- `a` **마이페이지** → `/ticket/mypage/mykorail`
- `a` **고객센터** → `/ticket/guest/csc`
- `a` **기업전용** → `/biz/main`
- `button` **Language**
- `a` **팝업열기**
- `a` **승차권** → `/ticket/myticket/list`
- `a` **철도역·열차** → `/ticket/train/stationGuide/station`
- `a` **고객서비스** → `/ticket/guest/notice`
- `a` **코레일멤버십** → `/ticket/membership/report`
- `button` **전체 메뉴 열기**

### 본문 주요 액션

- `button` **Language** (cls=`dropdown-button`)
- `button` **전체 메뉴 열기** (cls=`btn-allmenu`)
- `button` **Previous** (cls=`slick-arrow slick-prev`)
- `button` **Next** (cls=`slick-arrow slick-next`)
- `button` **1** (cls=``)
- `button` **2** (cls=``)
- `button` **3** (cls=``)
- `button` **정지** (cls=`btn-pause`)
- `a` **출발역 선택** (cls=`btn_pop btn_start`)
- `a` **도착역 선택** (cls=`btn_pop btn_end`)
- `a` **출발일 선택** (cls=`btn_pop btn_brth`)
- `a` **인원 선택** (cls=`btn_pop btn_recom`)
- `button` **열차 조회하기** (cls=`btn_lookup`)
- `button` **관련 사이트** (cls=`dropdown-button`)

### 입력 필드

- `input[type=text]` **labelstart** readonly value=`서울`
- `input[type=text]` **labelend** readonly value=`부산`
- `input[type=text]` **labelday** readonly value=`2026-05-14(목) 10:00`
- `input[type=text]` **labelple** readonly value=`총 1명`

---

## 4. 검색 폼 페이지

- URL: `https://www.korail.com/ticket/search/general`
- Title: 승차권 예매>예매>승차권>코레일 승차권예매
- 스크린샷: [runs/pages/04-search-general.png](runs/pages/04-search-general.png)

### GNB / 헤더 메뉴

- `a` **한국철도** → `https://www.korail.com/login/ssoDomainProc.do?domainURL=http://info.korail.com&domainSsoURL=https://info.korail.com&retURL=/mbs/www/`
- `a` **승차권예매** → `/ticket/main`
- `a` **기차여행** → `/tour/main`
- `a` **로그아웃**
- `a` **장바구니** → `/ticket/mypage/cart`
- `a` **마이페이지** → `/ticket/mypage/mykorail`
- `a` **고객센터** → `/ticket/guest/csc`
- `a` **기업전용** → `/biz/main`
- `button` **Language**
- `a` **팝업열기**
- `a` **승차권** → `/ticket/myticket/list`
- `a` **철도역·열차** → `/ticket/train/stationGuide/station`
- `a` **고객서비스** → `/ticket/guest/notice`
- `a` **코레일멤버십** → `/ticket/membership/report`
- `button` **전체 메뉴 열기**

### 입력 필드

- `input[type=text]` **txtGoStart** readonly value=`서울` placeholder=`출발역`
- `input[type=text]` **txtGoEnd** readonly value=`부산` placeholder=`도착역`
- `input[type=checkbox]` **rtYn** value=`on`
- `input[type=text]` **startDate** readonly value=`2026-05-14(목) 10:00` placeholder=`날짜를 선택해주세요`

---

## 5. 검색 결과 페이지 (KTX 탭)

- URL: `https://www.korail.com/ticket/search/list`
- Title: 열차 목록>승차권 예매>예매>승차권
- 스크린샷: [runs/pages/05-search-list.png](runs/pages/05-search-list.png)

### GNB / 헤더 메뉴

- `a` **한국철도** → `https://www.korail.com/login/ssoDomainProc.do?domainURL=http://info.korail.com&domainSsoURL=https://info.korail.com&retURL=/mbs/www/`
- `a` **승차권예매** → `/ticket/main`
- `a` **기차여행** → `/tour/main`
- `a` **로그아웃**
- `a` **장바구니** → `/ticket/mypage/cart`
- `a` **마이페이지** → `/ticket/mypage/mykorail`
- `a` **고객센터** → `/ticket/guest/csc`
- `a` **기업전용** → `/biz/main`
- `button` **Language**
- `a` **팝업열기**
- `a` **승차권** → `/ticket/myticket/list`
- `a` **철도역·열차** → `/ticket/train/stationGuide/station`
- `a` **고객서비스** → `/ticket/guest/notice`
- `a` **코레일멤버십** → `/ticket/membership/report`
- `button` **전체 메뉴 열기**

### 탭 / 필터

- `li` **전체**
- `li` **KTX/KTX-산천**
- `li` **새마을호/ITX-새마을**
- `li` **무궁화호/누리로**
- `li` **ITX-청춘**

### 입력 필드

- `input[type=text]` **startDate** readonly value=`2026-05-15(금) 09:00`
- `input[type=text]` **labelstart** readonly value=`서울`
- `input[type=text]` **labelend** readonly value=`부산`
- `input[type=text]` **labelple** readonly value=`총 1명`
- `input[type=checkbox]` **rtYn** value=`on`
- `input[type=checkbox]` **adjStnScdlOfrFlg** value=`on`
- `input[type=checkbox]` **adjStnScdlOfrFlg2** value=`on` — "서울·용산 - 수서 함께 보기" (SRT 포함 옵션. 2026-11-03 확인: 이전 **srtCheckYn** 은 사라짐, SRT 는 KTX 탭에 통합)

---

## 7. 마이페이지

- URL: `https://www.korail.com/mypage`
- Title: 코레일 승차권예매
- 스크린샷: [runs/pages/07-mypage.png](runs/pages/07-mypage.png)

### GNB / 헤더 메뉴

- `a` **고객센터** → `/ticket/guest/csc/korailcs`
- `a` **바로가기** → `/`

---
