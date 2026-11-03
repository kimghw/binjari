---
name: binjari_setup
description: binjari 웹서버 설치·셋업 — 의존성 라이브러리 설치(필요 시 .venv 생성), 실행 런처(launch_binjari.bat) 생성, 바탕화면 'binjari' 아이콘 설치, .env.azure 로 Azure/Teams 설정 초기화(.env.ktx 병합, 없으면 example 복사 생성), 채팅·AI 복구용 claude CLI(exe) 설정 검토. 사용자가 "설치", "셋업", "바탕화면 아이콘", "새 PC 세팅", "의존성 설치" 등을 말하면 시작. 절차 — (1) scripts/setup.ps1 실행 (2) 아이콘·런처·의존성·env·claude CLI 검증 (3) 결과 보고.
---

# binjari_setup — 웹서버 설치·바탕화면 아이콘

한 번 실행하면 이 PC 에서 binjari 웹서버를 더블클릭으로 쓸 수 있게 만든다. 멱등 — 여러 번 실행해도 안전.

## 하는 일

1. **python 결정**: `.venv` 가 있으면 그걸 사용. 없으면 시스템 python 에 핵심 의존성(fastapi·uvicorn·playwright·pydantic·dotenv·aiohttp)이 있는지 확인하고, 부족할 때만 `.venv` 를 새로 만든다. `-Venv` 스위치로 강제 생성 가능.
2. **의존성 설치**: pyproject.toml 의 dependencies 와 동일한 목록을 pip 으로 설치 (충족된 건 skip).
3. **런처 생성**: 프로젝트 루트에 `launch_binjari.bat` — 포트 8001 이 안 떠 있으면 서버를 백그라운드(pythonw, 콘솔 창 없음)로 **127.0.0.1 바인딩**으로 띄운 뒤 기본 브라우저로 http://localhost:8001 을 연다 (.env.ktx 실값을 다루는 로컬 전용 서버라 절대 0.0.0.0 으로 열지 않는다).
4. **바탕화면 아이콘**: `binjari.lnk` 를 바탕화면에 생성 (아이콘은 Chrome 아이콘, 없으면 시스템 기본). `-NoIcon` 으로 생략 가능.
5. **.env.azure 초기화**: 프로젝트 루트에 `.env.azure`(azure_env_export 스킬 산출물) 가 있으면 그 안의 **AZURE_* 키와 DB_PATH 만** 골라 `.env.ktx` 에 병합한다 (다른 키가 섞여 있어도 무시). `.env.ktx` 가 없으면 `.env.ktx.example` 복사로 먼저 생성한다 (신규 PC 초기화). DB_PATH 의 폴더가 이 PC 에 없으면 `<프로젝트>/team_mcp/database/auth.db` 로 대체. 병합 후 auth.db 존재를 확인해 없으면 `python -m team_mcp.login` OAuth 안내를 남긴다 (자동으로 브라우저 로그인을 띄우지는 않음 — korail_alarm 스킬 담당). **시크릿 값은 출력하지 않는다 — 키 이름만.**
6. **claude CLI 검토**: 웹 채팅 도우미(`/api/chat`)와 AI 자동 복구 폴백(fable→opus)이 쓰는 claude CLI(exe)가 있는지 확인 — PATH → `~\.local\bin\claude.exe` → `%APPDATA%\npm\claude.cmd` 순으로 탐색(web_server 의 `_find_claude` 와 동일 순서). 있으면 버전 출력, 없으면 설치 안내(https://claude.com/claude-code)를 경고로 남긴다. 자동 설치는 하지 않는다 (로그인이 필요해서 사용자가 직접).

## 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<프로젝트루트>\.claude\skills\binjari_setup\scripts\setup.ps1"
```

옵션: `-Venv` (강제 .venv), `-NoIcon` (아이콘 생략).

## 검증 (실행 후 반드시)

- [ ] 스크립트 출력에 `[binjari_setup] 완료` 가 있다.
- [ ] `launch_binjari.bat` 이 프로젝트 루트에 생겼다.
- [ ] 바탕화면에 `binjari.lnk` 가 있다 (`-NoIcon` 아니면).
- [ ] 선택한 python 으로 `import fastapi, uvicorn, playwright, aiohttp` 가 된다.
- [ ] claude CLI 가 `claude CLI OK` 로 확인됐다 — 없으면 사용자에게 채팅·AI 복구가 비활성임을 알린다.
- [ ] `.env.azure` 가 있었다면 `.env.azure 적용 (N개 키)` 가 출력됐고, `.env.ktx` 의 AZURE_* 값이 채워졌다 (값 자체는 화면에 노출 금지).
- [ ] auth.db 가 없다는 경고가 나왔다면 Teams 알림 셋업(`python -m team_mcp.login` / korail_alarm 스킬)을 사용자에게 안내했다.

## 주의

- **외부용 서버(web_external.py, :8002)는 설치하지 않는다** — 셋업 대상은 로컬 전용
  서버(web_server.py, 127.0.0.1:8001)뿐. 외부용은 운영 VM 한 대에서만 돌며
  Caddy 리버스 프록시·`.env.external`(허용/관리자 목록)·Azure 앱 redirect URI 가
  필요해 수동 구성한다. 새 PC 에 `.env.external` 이나 외부용 런처를 만들지 말 것.
- `.venv` 를 새로 만든 경우 playwright 등 설치에 수 분 걸릴 수 있다.
- 의존성 목록을 바꾸면 **pyproject.toml 과 setup.ps1 의 $deps 를 같이** 고친다.
- 런처는 서버가 이미 떠 있으면 새로 띄우지 않고 브라우저만 연다. 서버 중지는 `/port_manager` 또는 웹 UI 와 무관하게 프로세스 종료로.
- 워처의 CDP Chrome(별도 프로필) 과는 무관 — 그건 감시 시작 시 워처가 알아서 띄운다.
