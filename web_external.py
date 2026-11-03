"""binjari 외부용 웹서버 — Azure(Microsoft) 로그인 게이트.

실행::

    python -m uvicorn web_external:app --host 127.0.0.1 --port 8002

공개는 Caddy 리버스 프록시(https://binjari.rndsscb.com → 127.0.0.1:8002)가 담당하므로
이 프로세스는 반드시 127.0.0.1 에만 바인딩한다.

격리 원칙:
- 읽는 설정 파일은 `.env.azure`(Azure 앱 자격증명) + `.env.external`(게이트 설정) 뿐.
- `.env.ktx`(코레일 로그인·카드 실값)를 읽는 코드 경로가 없다 — 로컬 전용
  web_server.py(127.0.0.1:8001) 와 프로세스·저장소 수준에서 분리.
- 모든 페이지/API 는 Microsoft 로그인 + 허용 이메일 목록(EXT_ALLOWED_EMAILS) 통과 후에만 응답.

인증 흐름 (OAuth 2.0 authorization code, 추가 의존성 없이 httpx + stdlib HMAC):
  /auth/login → login.microsoftonline.com authorize → /auth/callback (code 교환)
  → Graph /me 로 이메일 확인 → 허용 목록 검사 → 서명된 세션 쿠키 발급.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlencode

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

LOGGER = logging.getLogger("web_external")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

BASE_DIR = Path(__file__).resolve().parent
AZURE_ENV = dotenv_values(BASE_DIR / ".env.azure")
EXT_ENV = dotenv_values(BASE_DIR / ".env.external")


def _require(env: Dict[str, Optional[str]], key: str, src: str) -> str:
    val = (env.get(key) or "").strip()
    if not val:
        raise RuntimeError(f"{src} 에 {key} 가 없습니다. 셋업을 먼저 하세요.")
    return val


CLIENT_ID = _require(AZURE_ENV, "AZURE_CLIENT_ID", ".env.azure")
CLIENT_SECRET = _require(AZURE_ENV, "AZURE_CLIENT_SECRET", ".env.azure")
_authority = (AZURE_ENV.get("AZURE_AUTHORITY") or "").strip().rstrip("/") \
    or "https://login.microsoftonline.com"
if _authority.count("/") <= 2:  # 도메인만 있고 테넌트 세그먼트가 없으면 붙인다
    _authority += "/" + _require(AZURE_ENV, "AZURE_TENANT_ID", ".env.azure")
AUTHORITY = _authority
AUTHORIZE_URL = f"{AUTHORITY}/oauth2/v2.0/authorize"
TOKEN_URL = f"{AUTHORITY}/oauth2/v2.0/token"
GRAPH_ME = "https://graph.microsoft.com/v1.0/me"
LOGIN_SCOPES = "openid profile email User.Read"

BASE_URL = _require(EXT_ENV, "EXT_BASE_URL", ".env.external").rstrip("/")
SESSION_SECRET = _require(EXT_ENV, "EXT_SESSION_SECRET", ".env.external").encode()
SESSION_DAYS = int((EXT_ENV.get("EXT_SESSION_DAYS") or "7").strip())

# 허용/관리자 이메일 목록은 .env.external 을 mtime 기준으로 핫리로드 — 등록/해제에
# 서버 재시작이 필요 없고, 목록에서 빠진 사용자는 기존 세션도 즉시 거부된다.
# 관리자(EXT_ADMIN_EMAILS)는 로컬 UI 전체(예매설정·환경설정·감시 제어)를 프록시로 쓰고,
# 일반 허용 사용자(EXT_ALLOWED_EMAILS)는 조회 화면만 쓴다. 관리자는 자동으로 허용에 포함.
_ACL_CACHE: Dict[str, object] = {"mtime": 0.0, "emails": frozenset(), "admins": frozenset()}


def _parse_email_csv(raw: Optional[str]) -> frozenset:
    return frozenset(e.strip().lower() for e in (raw or "").split(",") if e.strip())


def _acl_reload() -> None:
    path = BASE_DIR / ".env.external"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return
    if mtime != _ACL_CACHE["mtime"]:
        vals = dotenv_values(path)
        _ACL_CACHE["admins"] = _parse_email_csv(vals.get("EXT_ADMIN_EMAILS"))
        _ACL_CACHE["emails"] = _parse_email_csv(vals.get("EXT_ALLOWED_EMAILS")) | _ACL_CACHE["admins"]
        _ACL_CACHE["mtime"] = mtime


def _allowed_emails() -> frozenset:
    _acl_reload()
    return _ACL_CACHE["emails"]  # type: ignore[return-value]


def _admin_emails() -> frozenset:
    _acl_reload()
    return _ACL_CACHE["admins"]  # type: ignore[return-value]
REDIRECT_URI = f"{BASE_URL}/auth/callback"

SESSION_COOKIE = "binjari_ext_session"
STATE_COOKIE = "binjari_ext_state"

# 로컬 전용 서버(web_server.py)의 검색 API 만 좁게 프록시한다.
# 설정(.env.ktx)·감시 제어·결제 엔드포인트는 절대 프록시하지 않는다.
LOCAL_API = "http://127.0.0.1:8001"
_SEARCH_LOCK = asyncio.Lock()  # 크롬(CDP) 실조회는 한 번에 하나만

app = FastAPI(title="binjari external", docs_url=None, redoc_url=None, openapi_url=None)


# ─────────────────── 서명 쿠키 (stdlib HMAC) ───────────────────

def _sign(payload: str) -> str:
    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify(token: Optional[str]) -> Optional[str]:
    """서명·만료 검증 후 payload 반환. 실패 시 None."""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expect = hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    except Exception:
        return None
    return payload


def _session_email(request: Request) -> Optional[str]:
    payload = _verify(request.cookies.get(SESSION_COOKIE))
    if not payload:
        return None
    try:
        email, exp = payload.rsplit("|", 1)
        if time.time() > float(exp):
            return None
    except ValueError:
        return None
    # 목록에서 제거된 사용자는 살아 있는 세션 쿠키가 있어도 즉시 차단
    if email not in _allowed_emails():
        return None
    return email


def _set_cookie(resp, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(name, value, max_age=max_age, httponly=True,
                    secure=True, samesite="lax", path="/")


# ─────────────────── 페이지 ───────────────────

_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>binjari</title><style>
body{{font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;background:#f4f5f7;
margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#fff;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.08);
padding:32px 28px;max-width:380px;width:calc(100% - 48px);text-align:center}}
h1{{font-size:1.3rem;margin:0 0 6px}} p{{color:#555;font-size:.92rem;line-height:1.5}}
.btn{{display:inline-block;margin-top:14px;padding:12px 22px;border-radius:8px;
background:#2f2f2f;color:#fff;text-decoration:none;font-size:.95rem}}
.btn.gray{{background:#888}} .email{{font-weight:600;color:#1a56db;word-break:break-all}}
</style></head><body><div class="card">{body}</div></body></html>"""


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(body=body), status_code=status)


# ─────────────────── 라우트 ───────────────────

@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    email = _session_email(request)
    if not email:
        return _page(
            "<h1>binjari</h1>"
            "<p>KTX 예매 도우미 — 허용된 사용자만 이용할 수 있습니다.<br>"
            "Microsoft 계정으로 로그인하세요.</p>"
            '<a class="btn" href="/auth/login">Microsoft 계정으로 로그인</a>'
        )
    if email in _admin_emails():
        # 관리자는 로컬 UI 전체(예매설정·환경설정·감시 제어)를 그대로 쓴다
        return await _proxy_local(request, "/")
    return HTMLResponse(_SEARCH_HTML.replace("__EMAIL__", email))


@app.get("/auth/login")
def auth_login():
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": LOGIN_SCOPES,
        "state": state,
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=302)
    _set_cookie(resp, STATE_COOKIE, _sign(state), max_age=600)
    return resp


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = "",
                        error: str = "", error_description: str = ""):
    if error:
        LOGGER.warning("OAuth error: %s %s", error, error_description)
        return _page(f"<h1>로그인 실패</h1><p>{error}</p>"
                     '<a class="btn" href="/auth/login">다시 시도</a>', status=400)
    saved_state = _verify(request.cookies.get(STATE_COOKIE))
    if not code or not state or saved_state != state:
        return _page("<h1>로그인 실패</h1><p>세션이 만료되었거나 잘못된 요청입니다.</p>"
                     '<a class="btn" href="/auth/login">다시 시도</a>', status=400)

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(TOKEN_URL, data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "scope": LOGIN_SCOPES,
        })
        if token_resp.status_code != 200:
            LOGGER.warning("token exchange failed: %s %s",
                           token_resp.status_code, token_resp.text[:300])
            return _page("<h1>로그인 실패</h1><p>토큰 교환에 실패했습니다.</p>"
                         '<a class="btn" href="/auth/login">다시 시도</a>', status=502)
        access_token = token_resp.json().get("access_token", "")

        me_resp = await client.get(GRAPH_ME,
                                   headers={"Authorization": f"Bearer {access_token}"})
        if me_resp.status_code != 200:
            LOGGER.warning("graph /me failed: %s", me_resp.status_code)
            return _page("<h1>로그인 실패</h1><p>사용자 정보를 확인할 수 없습니다.</p>"
                         '<a class="btn" href="/auth/login">다시 시도</a>', status=502)
        me = me_resp.json()

    email = (me.get("mail") or me.get("userPrincipalName") or "").strip().lower()
    if not email or email not in _allowed_emails():
        LOGGER.warning("허용되지 않은 로그인 시도: %s", email or "(email 없음)")
        return _page("<h1>접근 권한 없음</h1>"
                     f'<p><span class="email">{email or "알 수 없음"}</span> 계정은 '
                     "허용 목록에 없습니다.<br>관리자에게 등록을 요청하세요.</p>",
                     status=403)

    LOGGER.info("로그인 성공: %s", email)
    resp = RedirectResponse("/", status_code=302)
    _set_cookie(resp, SESSION_COOKIE, _sign(f"{email}|{time.time() + SESSION_DAYS * 86400}"),
                max_age=SESSION_DAYS * 86400)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


@app.get("/auth/logout")
def auth_logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ─────────────────── 조회 (로컬 서버 검색 API 프록시) ───────────────────

_SEARCH_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>binjari</title><style>
body{font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;background:#f4f5f7;margin:0;padding:16px}
.wrap{max-width:560px;margin:0 auto}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.top h1{font-size:1.15rem;margin:0} .top a{font-size:.8rem;color:#888;text-decoration:none}
.email{font-size:.75rem;color:#999;word-break:break-all}
.card{background:#fff;border-radius:12px;box-shadow:0 1px 8px rgba(0,0,0,.07);padding:16px;margin-bottom:14px}
.row{display:flex;gap:8px;margin-bottom:10px} .row>*{flex:1;min-width:0}
label{display:block;font-size:.72rem;color:#777;margin-bottom:3px}
input,select{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px}
button{width:100%;padding:13px;border:0;border-radius:8px;background:#2f2f2f;color:#fff;font-size:1rem}
button:disabled{background:#aaa}
.swap{flex:0 0 44px;align-self:flex-end;background:#eee;color:#333;font-size:1.1rem;padding:10px 0}
#st{font-size:.85rem;color:#555;margin:10px 2px} #st a{color:#1a56db;text-decoration:none}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;
box-shadow:0 1px 8px rgba(0,0,0,.07);font-size:.88rem}
th,td{padding:9px 6px;text-align:center;border-bottom:1px solid #f0f0f0}
th{background:#fafafa;color:#777;font-size:.75rem;font-weight:600}
.arr{color:#999;font-size:.78rem}
.tag{display:block;width:fit-content;margin:2px auto;padding:2px 9px;border-radius:999px;
background:#ededf0;color:#666;font-size:.72rem;font-weight:600}
</style></head><body><div class="wrap">
<div class="top"><h1>binjari 열차 조회</h1>
<div style="text-align:right"><div class="email">__EMAIL__</div><a href="/auth/logout">로그아웃</a></div></div>
<div class="card">
<div class="row">
  <div><label>출발역</label><input id="o" list="stns" placeholder="서울"></div>
  <button type="button" class="swap" onclick="swap()">⇄</button>
  <div><label>도착역</label><input id="d" list="stns" placeholder="부산"></div>
</div>
<div class="row">
  <div><label>날짜</label><input id="dt" type="date"></div>
  <div><label>출발 시각부터</label><select id="eh"></select></div>
  <div><label>인원</label><select id="ps"><option>1</option><option>2</option><option>3</option><option>4</option></select></div>
</div>
<button type="button" id="go" onclick="doSearch(false)">조회</button>
</div>
<div id="st"></div><div id="res"></div>
<datalist id="stns"></datalist>
</div><script>
const $=id=>document.getElementById(id);
$('dt').value=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
$('dt').min=$('dt').value;
for(let h=0;h<24;h++){const o=document.createElement('option');o.value=h;o.textContent=String(h).padStart(2,'0')+':00';if(h===6)o.selected=true;$('eh').appendChild(o);}
fetch('/api/stations').then(r=>r.json()).then(j=>{
  for(const s of (j.all||j.major||[])){const o=document.createElement('option');o.value=s;$('stns').appendChild(o);}
}).catch(()=>{});
function swap(){const a=$('o').value;$('o').value=$('d').value;$('d').value=a;}
async function doSearch(force){
  const o=$('o').value.trim(), d=$('d').value.trim(), date=$('dt').value;
  if(!o||!d||!date){$('st').textContent='출발역·도착역·날짜를 입력하세요.';return;}
  $('go').disabled=true;
  $('st').textContent=force?'사이트 재조회 중… (최대 1분 걸릴 수 있어요)':'조회 중…';
  $('res').innerHTML='';
  const ctrl=new AbortController();const to=setTimeout(()=>ctrl.abort(),120000);
  try{
    const r=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({origin:o,dest:d,date:date,earliest_hour:+$('eh').value,
                           passengers:+$('ps').value,force:!!force}),signal:ctrl.signal});
    if(r.status===401){location.href='/auth/login';return;}
    const j=await r.json();
    if(!r.ok){$('st').textContent='오류: '+(j.detail||r.status);return;}
    render(j);
  }catch(e){$('st').textContent='조회 실패: '+(e.name==='AbortError'?'시간 초과':e);}
  finally{clearTimeout(to);$('go').disabled=false;}
}
function render(j){
  $('st').innerHTML=j.count+'건 · '+(j.cached?'캐시':'실조회')+(j.fetched_at?' · '+j.fetched_at:'')
    +' &nbsp;<a href="#" onclick="doSearch(true);return false">↻ 사이트 재조회</a>';
  if(!j.rows.length){$('res').innerHTML='<div class="card">결과가 없습니다.</div>';return;}
  const tag=(label,txt)=>{const t=(txt||'').trim();
    return (/원|가능/.test(t)&&t!=='매진')
      ? '<span class="tag" title="'+t.replace(/"/g,'&quot;')+'">'+label+'</span>' : '';};
  let h='<table><thead><tr><th>열차</th><th>출발·도착</th><th>좌석</th></tr></thead><tbody>';
  for(const r of j.rows){
    h+='<tr><td><div>'+r.train_type+'</div><div class="arr">'+r.train_no+'</div></td><td><div>'+r.depart
      +'</div><div class="arr">'+r.arrive+'</div></td><td>'
      +((tag('특실',r.first)+tag('일반실',r.general))||'<span class="arr">–</span>')+'</td></tr>';
  }
  $('res').innerHTML=h+'</tbody></table>';
}
</script></body></html>"""


class ExtSearchRequest(BaseModel):
    origin: str = Field(..., min_length=1, max_length=20)
    dest: str = Field(..., min_length=1, max_length=20)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    earliest_hour: int = Field(6, ge=0, le=23)
    passengers: int = Field(1, ge=1, le=4)
    force: bool = False


@app.get("/api/stations")
async def api_stations(request: Request):
    if not _session_email(request):
        return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{LOCAL_API}/api/stations")
        return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.HTTPError:
        return JSONResponse({"detail": "로컬 서버에 연결할 수 없습니다."}, status_code=503)


@app.post("/api/search")
async def api_search(request: Request, req: ExtSearchRequest):
    email = _session_email(request)
    if not email:
        return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
    LOGGER.info("조회 요청: %s %s→%s %s force=%s", email, req.origin, req.dest, req.date, req.force)
    try:
        # 실조회(force 또는 캐시 없음)는 크롬 하나를 쓰므로 외부 요청은 직렬화한다.
        async with _SEARCH_LOCK:
            async with httpx.AsyncClient(timeout=110) as client:
                r = await client.post(f"{LOCAL_API}/api/search/ktx", json={
                    "origin": req.origin, "dest": req.dest, "date": req.date,
                    "earliest_hour": req.earliest_hour,
                    "passengers": req.passengers, "force": req.force,
                })
        return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        return JSONResponse({"detail": "로컬 서버가 꺼져 있습니다. 관리자에게 문의하세요."},
                            status_code=503)
    except httpx.HTTPError as exc:
        LOGGER.warning("검색 프록시 실패: %s", exc)
        return JSONResponse({"detail": "조회 중 오류가 발생했습니다."}, status_code=502)


# 로그인 이후에만 열리는 API 는 아래처럼 _session_email 가드를 통과해야 한다.
@app.get("/api/me")
def api_me(request: Request):
    email = _session_email(request)
    if not email:
        return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
    return {"email": email, "admin": email in _admin_emails()}


# ─────────────────── 관리자 전용: 로컬 UI 전체 프록시 ───────────────────
# 관리자에게는 로컬 전용 서버(127.0.0.1:8001)의 화면·API 를 통째로 중계한다.
# 예매설정(.env.ktx 여정·대상 열차)·환경설정·감시 시작/중지가 그대로 동작한다.
# 일반 사용자는 이 경로에 절대 못 들어온다 (403) — 조회 전용 화면만.

_PROXY_STRIP_RESP = {"content-length", "transfer-encoding", "connection", "content-encoding"}


async def _proxy_local(request: Request, path: str) -> Response:
    body = await request.body()
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in ("content-type", "accept", "accept-language")
    }
    try:
        # /api/chat(claude CLI)·실조회 등 오래 걸리는 호출이 있어 타임아웃을 길게 둔다
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.request(request.method, f"{LOCAL_API}{path}",
                                     params=request.query_params,
                                     content=body, headers=fwd_headers)
    except httpx.HTTPError as exc:
        LOGGER.warning("로컬 프록시 실패 %s %s: %s", request.method, path, exc)
        return JSONResponse({"detail": "로컬 서버에 연결할 수 없습니다."}, status_code=503)
    resp_headers = {k: v for k, v in r.headers.items()
                    if k.lower() not in _PROXY_STRIP_RESP}
    return Response(content=r.content, status_code=r.status_code, headers=resp_headers)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def admin_catch_all(request: Request, path: str):
    email = _session_email(request)
    if not email:
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/", status_code=302)
        return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
    if email not in _admin_emails():
        return JSONResponse({"detail": "관리자 전용 기능입니다."}, status_code=403)
    return await _proxy_local(request, f"/{path}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)
