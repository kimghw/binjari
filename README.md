# 🪑 빈자리 (binjari)

**기차(KTX)의 빈자리를 감시하다가 잡아주는 예매 워처.**
조회 → 예약 → (옵션) 결제/발권 → (옵션) 승차권 전달까지 자동 처리하고, 성공하면 Teams 알림으로 알려줍니다.

> **개인 사용용(personal use) 프로젝트입니다.** 작성자 개인의 학습·편의 목적으로 만든 도구로,
> 범용 배포·상업적 이용을 염두에 두지 않았으며 동작 보장이나 지원을 제공하지 않습니다.

## 구성

| 모듈 | 역할 | 실행 |
|---|---|---|
| `ktx_watcher` | 코레일 KTX 감시·예매 워처 (경로 등 승객유형·승차권 전달 지원) | `python -m ktx_watcher.main` |
| `web_server` | 출발·도착·시간 조회 웹 UI (FastAPI) | `python -m uvicorn web_server:app --host 0.0.0.0 --port 8001` |
| `team_mcp` | Teams 알림 (Azure AD OAuth / Graph API) | `python -m team_mcp.login` (최초 인증) |

## 설치

- **자동**: Claude Code에서 `binjari_setup` 스킬 실행 — 의존성 설치, 실행 런처(`launch_binjari.bat`), 바탕화면 아이콘까지 셋업.
- **수동**: Python 3.12+ 에서

  ```bash
  uv sync            # 또는: pip install -e .
  # 시스템 Chrome에 CDP로 연결하므로 별도 Chromium 설치는 필요하지 않습니다.
  ```

## 설정

- 브라우저 연결은 `rebrowser-playwright`의 `addBinding` 모드를 사용하여
  CDP `Runtime.enable`을 호출하지 않습니다. 조회·예매·결제와 웹 서버의 CDP
  조작은 모두 `ktx_watcher.browser`를 사용합니다.
  `REBROWSER_PATCHES_RUNTIME_FIX_MODE`는 연결을 시작할 때 `addBinding`으로 고정됩니다.
  JavaScript 실행에 필요한 다른 `Runtime.*` 명령은 계속 사용합니다.
  변경 후 `uv sync`를 실행하고 실행 중인 워처와 웹 서버를 재시작하세요.
  동작 방식: [Rebrowser 공식 문서](https://github.com/rebrowser/rebrowser-patches#fix-runtimeenable-leak).
- CDP 사용은 브라우저 연결과 실제 화면 조작에 집중합니다. `ktx_watcher.dom`이
  입력값·본문·표시 중인 모달을 한 번에 읽고, 팝업은 context 핸들러 하나로 처리합니다.
  불필요한 마우스 이동·hover·글자별 타이핑은 제거했으며 입력은 `fill`을 사용합니다.
  동일 클라이언트의 연결과 메인 탭을 재사용하고, 탭 전환이 없으면 결과 재파싱을 생략합니다.
  Playwright가 사용하는 CDP 연결과 내부 프로토콜 명령은 계속 필요합니다.
  검증: `uv run pytest tests/test_browser_runtime.py -q -s`.
- `KTXA_TIME_WINDOW`가 있으면 그 구간 전체를 감시합니다. 비어 있을 때만
  `KTXA_TIMES` ± `KTXA_TOLERANCE_MIN`을 적용합니다.
- 실제 조회 점검: `uv run python -m ktx_watcher.diagnose`.
  로그인·예약·결제 없이 조회하고 `runs/diagnose/`에 조건, 목록, 후보, 오류 유형과
  화면을 저장합니다. 명시적인 차단 안내는 닫기 전에 `runs/guards/`에 따로 기록합니다.
  `GuardBlocked`는 차단 문구가 확인된 경우이고, `QueryConditionMismatch`는 조건 불일치,
  `SearchResultUnavailable`는 빈 목록·불완전한 목록입니다. 정상 조회 후 후보 0건은
  매진 또는 시간·구간·좌석 조건에 해당하는 열차가 없다는 뜻입니다.
  전체 회귀 테스트: `uv run python -m pytest tests -q`.
- 조회 차단과 실행 방식 비교:
  [2026-11-04 CDP·UIA 분석 및 Claude Code 복구 현황](ktx_watcher/QUERY_AUTOMATION_ANALYSIS_2026-11-04.md).
  CDP 개별 시험은 성공했으며, 전체 단계별 자동화의 반복 안정성은 아직 미검증입니다.
  UIA Invoke는 진단 실험에만 적용돼 있고 운영 조회는 현재 CDP를 사용합니다.

- `.env.ktx.example` 을 `.env.ktx` 로 복사해 `<...>` 자리에 실값(로그인·카드·Azure)을 채웁니다.
  **실값 파일은 커밋 금지** — `.gitignore` 가 `.env.*` 전체를 차단하며 양식(`*.example`)만 커밋됩니다.
- Teams 알림을 쓰려면 Azure AD OAuth 값을 채우고 `python -m team_mcp.login` 으로 최초 1회 인증합니다.
- Azure 설정만 별도 파일로 뽑을 때는 `azure_env_export` 스킬 사용 (`.env.ktx` → `.env.azure`).

---

## ⚠️ 주의 사항

- 본 도구는 학습/개인 편의 목적이며, **사이트 약관 및 관련 법령 준수**가 필요합니다.
- 사이트 구조 변경 시 일부 동작이 중단될 수 있습니다(로그/캡쳐로 원인 추적 가능).
