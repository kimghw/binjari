<#
  win_watch.ps1 — OS 입력 기반 코레일 감시 (CDP 미사용)

  왜 이게 필요한가 (2026-11-03 실측):
    코레일은 CDP(개발자도구 프로토콜) 세션에 거짓 응답을 보낸다. 같은 시각 같은 질의에
    사람 경로는 20편/자리 30셀, CDP 경로는 0편/"운행하는 열차가 없습니다" 가 왔다.
    따라서 Playwright(CDP) 로는 조회 자체가 불가능하고, OS 레벨 입력 + 접근성 API(UIA)
    로만 정상 응답을 받을 수 있다.

  2026-11-04 정정:
    위 '거짓 응답' 은 첫 조회 제출에만 걸리는 1회성 -8002 가드였고, CDP 경로도
    모달을 닫고 조회를 한 번 더 누르면 정상 목록(10편 → 더보기 40편)을 받는다
    (korail/search.py `_requery_after_guard`). CDP 조회 불가라는 전제는 틀렸다.
    이 스크립트는 CDP 경로가 막혔을 때의 대체 수단으로만 남긴다.

  설계 원칙 — "좌표를 믿지 않는다":
    창 위치/최대화 상태/다른 앱의 가림에 따라 좌표는 수시로 어긋난다. 실제로 오늘
    (1) AppActivate 실패로 클릭이 VS Code 로 들어가고 (2) SW_RESTORE 가 최대화를 풀어
    좌표가 1136px 밀려 엉뚱한 텍스트를 선택하는 일이 있었다.
    그래서 클릭 직전에 **그 좌표의 UIA 요소가 목표물과 동일한지** 확인하고, 다르면 클릭하지
    않는다. 사용자의 다른 앱을 잘못 누르느니 그 회차를 건너뛴다.

  전제:
    - Chrome 이 KTXA_CDP_USER_DATA_DIR 프로필로, **디버그 포트 없이** 떠 있어야 한다.
    - 코레일 검색 결과 페이지(/ticket/search/list)가 열려 있고, 조회 조건이 .env.ktx 와
      일치해야 한다. (날짜 픽커 자동화는 하지 않는다 — 사람이 한 번 맞춰두면 된다.)
    - 예약까지 하려면 **로그인되어 있어야 한다.** 자동 로그인은 하지 않는다
      (코레일 5회 실패 시 계정 잠금 위험).

  사용:
    powershell -NoProfile -ExecutionPolicy Bypass -File win_watch.ps1
    powershell ... -File win_watch.ps1 -Once          # 1회만 조회
    powershell ... -File win_watch.ps1 -NoReserve     # 자리 찾아도 예약 시도 안 함
#>

param(
    [switch]$Once,
    [switch]$NoReserve,
    [int]$Strikes = 3,
    [int]$MaxPolls = 0,           # 0 = 무제한
    # 폴링 간격(초). KTXA_POLL_MIN/MAX 는 쓰지 않는다 — 그건 CDP 경로용이라 3~5'초' 로
    # 설정돼 있어서, 창을 앞으로 끌어오며 조작하는 이 방식엔 과도하고 사이트에도 무례하다.
    [int]$IntervalSec = 120
)

$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms

Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class WinIn {
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, int e);
}
"@

$ROOT    = 'C:\Users\kimghw\binjari'
$LOG     = Join-Path $ROOT 'runs\win_watch.log'
$ENVFILE = Join-Path $ROOT '.env.ktx'
$SW_MAXIMIZE = 3

function Log($m) {
    $line = '{0} | {1}' -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -Path $LOG -Value $line -Encoding utf8
}

# ───────────────────────── 설정 ─────────────────────────
function Read-EnvFile {
    $h = @{}
    foreach ($l in (Get-Content -Path $ENVFILE -Encoding UTF8)) {
        $t = $l.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $h[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
    }
    return $h
}

$cfg = Read-EnvFile
$ORIGIN   = $cfg['KTXA_ORIGIN']
$DEST     = $cfg['KTXA_DEST']
$DATE     = $cfg['KTXA_DATE']
$TRAINTY  = $cfg['KTXA_TRAIN_TYPE']
$SEATCLS  = $cfg['KTXA_SEAT_CLASS']
$SEATONLY = ($cfg['KTXA_SEATED_ONLY'] -eq 'true')
$TOL      = [int]($cfg['KTXA_TOLERANCE_MIN'])
$PMIN     = [int]($cfg['KTXA_POLL_MIN']); if ($PMIN -le 0) { $PMIN = 3 }
$PMAX     = [int]($cfg['KTXA_POLL_MAX']); if ($PMAX -lt $PMIN) { $PMAX = $PMIN }
$TIMES    = @()
foreach ($t in ($cfg['KTXA_TIMES'] -split ',')) {
    $t = $t.Trim(); if ($t -match '^(\d{1,2}):(\d{2})$') { $TIMES += ([int]$Matches[1] * 60 + [int]$Matches[2]) }
}

# ───────────────────────── 창 찾기 ─────────────────────────
function Find-KorailWindow {
    $profile = $cfg['KTXA_CDP_USER_DATA_DIR']
    $cands = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
             Where-Object { $_.CommandLine -like "*$profile*" -and $_.CommandLine -notlike '*--type=*' }
    foreach ($c in $cands) {
        $p = Get-Process -Id $c.ProcessId -ErrorAction SilentlyContinue
        if ($p -and $p.MainWindowHandle -ne 0) {
            if ($c.CommandLine -match 'remote-debugging-port') {
                Log "⚠ 이 Chrome 은 디버그 포트로 떠 있습니다 — 코레일이 차단합니다. 포트 없이 다시 띄우세요."
                return $null
            }
            return $p
        }
    }
    return $null
}

$proc = Find-KorailWindow
if (-not $proc) {
    Log "❌ 코레일 Chrome 창을 찾지 못했습니다. 프로필 '$($cfg['KTXA_CDP_USER_DATA_DIR'])' 로, 디버그 포트 없이 띄우고 검색 결과 페이지를 열어두세요."
    exit 1
}
$PID_T = $proc.Id
$HWND  = $proc.MainWindowHandle
$WS    = New-Object -ComObject WScript.Shell
$AUTO_ROOT = [System.Windows.Automation.AutomationElement]::RootElement
$PID_COND  = New-Object System.Windows.Automation.PropertyCondition(
                [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $PID_T)

function Get-Win { $AUTO_ROOT.FindFirst([System.Windows.Automation.TreeScope]::Children, $PID_COND) }

function Ensure-Front {
    for ($i = 1; $i -le 6; $i++) {
        [void][WinIn]::ShowWindow($HWND, $SW_MAXIMIZE)   # RESTORE 쓰면 최대화가 풀려 좌표가 밀린다
        $WS.SendKeys('%')                                 # ALT: 포그라운드 잠금 해제
        Start-Sleep -Milliseconds 180
        [void][WinIn]::SetForegroundWindow($HWND)
        Start-Sleep -Milliseconds 800
        if ([WinIn]::GetForegroundWindow() -eq $HWND) { Start-Sleep -Milliseconds 900; return $true }
    }
    return $false
}

# 좌표가 아니라 '그 지점의 요소' 를 확인하고 클릭한다.
function Invoke-VerifiedClick($el, $label) {
    $sp = $el.GetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern)
    if ($sp) { $sp.ScrollIntoView(); Start-Sleep -Milliseconds 900 }
    $want = $el.Current.Name
    $r = $el.Current.BoundingRectangle
    if ($r.Width -le 0 -or $r.Height -le 0) { Log "   클릭 skip($label): 보이지 않는 요소"; return $false }
    $cx = [int]($r.X + $r.Width / 2); $cy = [int]($r.Y + $r.Height / 2)
    $at = [System.Windows.Automation.AutomationElement]::FromPoint((New-Object System.Windows.Point($cx, $cy)))
    if (-not $at -or $at.Current.Name -ne $want) {
        Log "   클릭 skip($label): ($cx,$cy) 에 '$($at.Current.Name)' — 목표 '$want' 아님"
        return $false
    }
    [void][WinIn]::SetCursorPos($cx - 25, $cy - 12); Start-Sleep -Milliseconds 300
    [void][WinIn]::SetCursorPos($cx, $cy);           Start-Sleep -Milliseconds 500
    [WinIn]::mouse_event(0x0002, 0, 0, 0, 0); Start-Sleep -Milliseconds 120
    [WinIn]::mouse_event(0x0004, 0, 0, 0, 0)
    Log "   클릭: $label"
    return $true
}

function Get-FieldValue($name) {
    $w = Get-Win; if (-not $w) { return '' }
    $c = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Edit)
    foreach ($e in $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $c)) {
        if ($e.Current.Name -eq $name) {
            $vp = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
            if ($vp) { return $vp.Current.Value }
        }
    }
    return ''
}

# ───────────────────────── 결과 파싱 ─────────────────────────
# 행 구조 (2026-11-03 UIA 실측):
#   ListItem
#     Text 'KTX' / Text '001' / Text '서울 → 부산(05:13 ~ 07:50)' / Text '소요시간' ...
#     Hyperlink <일반실 셀>  (X 작음)   Hyperlink <특실 셀> (X 큼)
#   좌석 셀 이름: '매진' | '입석 + 좌석' | '일반실 15% 할인 45,800원'
function Read-Rows {
    $w = Get-Win; if (-not $w) { return $null }
    $liC = New-Object System.Windows.Automation.PropertyCondition(
             [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
             [System.Windows.Automation.ControlType]::ListItem)
    $rows = @()
    foreach ($li in $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $liC)) {
        $nm = $li.Current.Name
        if (-not $nm -or $nm -notmatch '→.*\(\d{2}:\d{2}') { continue }
        $kids = $li.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                            [System.Windows.Automation.Condition]::TrueCondition)
        $texts = @(); $links = @()
        foreach ($k in $kids) {
            $kn = $k.Current.Name; if (-not $kn -or -not $kn.Trim()) { continue }
            $t = ($k.Current.ControlType.ProgrammaticName -replace 'ControlType\.', '')
            if ($t -eq 'Text') { $texts += $kn.Trim() }
            elseif ($t -eq 'Hyperlink') { $links += $k }
        }
        $route = ($texts | Where-Object { $_ -match '→.*\(\d{2}:\d{2} ~ \d{2}:\d{2}\)' } | Select-Object -First 1)
        if (-not $route) { continue }
        [void]($route -match '^(.+?)\s*→\s*(.+?)\((\d{2}):(\d{2}) ~ (\d{2}):(\d{2})\)')
        # 좌석 셀 = 좌석 상태로 보이는 링크. X 오름차순 → [0] 일반실, [1] 특실
        $seatLinks = @($links | Where-Object {
                        $_.Current.Name -match '^(매진|입석|일반실|특실|우등실)' } |
                      Sort-Object { $_.Current.BoundingRectangle.X })
        $rows += [PSCustomObject]@{
            Train   = $(if ($texts.Count -ge 1) { $texts[0] } else { '' })
            No      = $(if ($texts.Count -ge 2) { $texts[1] } else { '' })
            From    = $Matches[1]
            To      = $Matches[2]
            DepMin  = [int]$Matches[3] * 60 + [int]$Matches[4]
            Dep     = '{0}:{1}' -f $Matches[3], $Matches[4]
            General = $(if ($seatLinks.Count -ge 1) { $seatLinks[0] } else { $null })
            Special = $(if ($seatLinks.Count -ge 2) { $seatLinks[1] } else { $null })
            Raw     = $nm.Trim()
        }
    }
    return $rows
}

# 결과 목록은 첫 화면에 일부만 준다. 감시 대상 시각이 목록에 들어올 때까지 '더보기' 를 누른다.
# (이게 없으면 KTXA_TIMES=09:00 인데 목록이 05~06시대에서 끊겨 후보를 영영 못 본다.)
function Expand-More {
    if ($TIMES.Count -eq 0) { return }
    $limit = ($TIMES | Measure-Object -Maximum).Maximum + $TOL
    for ($k = 1; $k -le 15; $k++) {
        $rows = Read-Rows
        if (-not $rows -or $rows.Count -eq 0) { return }
        $last = ($rows | Sort-Object DepMin | Select-Object -Last 1).DepMin
        if ($last -ge $limit) { return }
        $w = Get-Win; if (-not $w) { return }
        $more = $null
        foreach ($e in $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                                  [System.Windows.Automation.Condition]::TrueCondition)) {
            if ($e.Current.Name -eq '더보기' -and
                ($e.Current.ControlType.ProgrammaticName -replace 'ControlType\.', '') -eq 'Hyperlink') {
                $more = $e; break
            }
        }
        if (-not $more) { return }
        if (-not (Invoke-VerifiedClick $more '더보기')) { return }
        Start-Sleep -Seconds 4
    }
}

function Get-PageFlags {
    $w = Get-Win; if (-not $w) { return $null }
    $names = @()
    foreach ($e in $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                              [System.Windows.Automation.Condition]::TrueCondition)) {
        $n = $e.Current.Name; if ($n) { $names += $n }
    }
    [PSCustomObject]@{
        Blocked  = [bool]($names | Where-Object { $_ -match '미허가|개발자도구|-800\d' })
        Empty    = [bool]($names | Where-Object { $_ -like '*운행하는 열차가 없습니다*' })
        LoggedIn = [bool]($names | Where-Object { $_ -eq '로그아웃' })
    }
}

# 좌석 셀 이름 → 상태 분류
function Get-SeatKind($name) {
    if (-not $name) { return 'none' }
    if ($name -match '\d{1,3},\d{3}원') { return 'reserve' }   # 가격 = 예약 가능
    if ($name -match '예약대기')        { return 'waitlist' }
    if ($name -match '입석')            { return 'standing' }
    if ($name -match '매진')            { return 'soldout' }
    return 'unknown'
}

function Test-TrainType($train) {
    if (-not $TRAINTY) { return $true }
    switch ($TRAINTY.ToUpper()) {
        'KTX' { return ($train -match 'KTX') }
        default { return ($train -match [regex]::Escape($TRAINTY)) }
    }
}

function Test-TimeMatch($depMin) {
    if ($TIMES.Count -eq 0) { return $true }
    foreach ($t in $TIMES) { if ([Math]::Abs($depMin - $t) -le $TOL) { return $true } }
    return $false
}

# ───────────────────────── 메인 루프 ─────────────────────────
Log ('===== win_watch 시작 — {0}→{1} {2} times={3} seat={4} seatedOnly={5} =====' -f `
     $ORIGIN, $DEST, $DATE, ($cfg['KTXA_TIMES']), $(if($SEATCLS){$SEATCLS}else{'일반실+특실'}), $SEATONLY)
Log "대상 창 PID=$PID_T (디버그 포트 없음 확인됨)"

# 조회 조건이 설정과 맞는지 한 번 점검 (날짜 픽커는 자동화하지 않는다)
$dateField = Get-FieldValue '날짜'
$fromField = Get-FieldValue '출발역'
$toField   = Get-FieldValue '도착역'
Log "화면 조건: $fromField → $toField / $dateField"
if ($dateField -and $dateField -notlike "$DATE*") {
    Log "❌ 화면 날짜($dateField)가 설정($DATE)과 다릅니다. 브라우저에서 조건을 맞춘 뒤 다시 실행하세요."
    exit 2
}
if ($fromField -and $fromField -ne $ORIGIN) { Log "❌ 출발역 불일치: 화면=$fromField 설정=$ORIGIN"; exit 2 }
if ($toField   -and $toField   -ne $DEST)   { Log "❌ 도착역 불일치: 화면=$toField 설정=$DEST";   exit 2 }

$strike = 0; $poll = 0; $okCount = 0
while ($true) {
    $poll++
    if ($MaxPolls -gt 0 -and $poll -gt $MaxPolls) { Log "MaxPolls 도달 — 종료"; break }

    if (-not (Ensure-Front)) { Log "#$poll 포그라운드 확보 실패 — 이번 회차 건너뜀"; Start-Sleep -Seconds 30; continue }
    $WS.SendKeys('{F5}')
    Start-Sleep -Seconds 15

    $flags = Get-PageFlags
    Expand-More                     # 감시 시각이 목록에 포함되도록 펼친다
    $rows  = Read-Rows
    if ($null -eq $rows) { Log "#$poll 창 소실 — 종료"; break }

    # 차단 판정: 문구가 떴거나, 목록 자체가 비었거나
    if ($flags.Blocked -or $rows.Count -eq 0) {
        $strike++
        $why = $(if ($flags.Blocked) { '차단 문구' } elseif ($flags.Empty) { '빈 목록(열차 없음)' } else { '행 0건' })
        Log "#$poll ⚠ 이상 [$strike/$Strikes] — $why"
        if ($strike -ge $Strikes) {
            Log "🛑 연속 $strike 회 이상 — 중단. '매진' 이 아니라 목록을 못 읽는 상태입니다."
            Log "   조치: Chrome 을 완전히 종료 후 다시 띄우고, 사람이 직접 조회해 정상인지 확인하세요."
            break
        }
        Start-Sleep -Seconds 30
        continue
    }
    if ($strike -gt 0) { Log "   조회 정상 복구 (직전 이상 $strike 회)"; $strike = 0 }
    $okCount++

    # 후보 추리기
    $cands = @()
    foreach ($r in $rows) {
        if (-not (Test-TrainType $r.Train)) { continue }
        if (-not (Test-TimeMatch $r.DepMin)) { continue }
        foreach ($slot in @(
                @{ Label = '일반실'; El = $r.General },
                @{ Label = '특실';   El = $r.Special })) {
            if (-not $slot.El) { continue }
            if ($SEATCLS -and $slot.Label -ne $SEATCLS) { continue }
            $kind = Get-SeatKind $slot.El.Current.Name
            if ($kind -eq 'soldout' -or $kind -eq 'none' -or $kind -eq 'unknown') { continue }
            if ($SEATONLY -and $kind -ne 'reserve') { continue }
            $cands += [PSCustomObject]@{
                Row = $r; Label = $slot.Label; El = $slot.El
                Kind = $kind; Text = $slot.El.Current.Name
            }
        }
    }

    $soldCnt = @($rows | Where-Object { (Get-SeatKind $_.General.Current.Name) -eq 'soldout' }).Count
    Log ('#{0} 총 {1}편 / 일반실매진 {2}편 / 후보 {3}건' -f $poll, $rows.Count, $soldCnt, $cands.Count)

    if ($cands.Count -gt 0) {
        $best = $cands | Sort-Object { $_.Row.DepMin } | Select-Object -First 1
        Log ('🔔 자리 발견: {0}{1} {2}→{3} {4} [{5}] {6}' -f `
             $best.Row.Train, $best.Row.No, $best.Row.From, $best.Row.To, $best.Row.Dep, $best.Label, $best.Text)
        [Console]::Beep(880, 400); [Console]::Beep(1320, 400)

        if ($NoReserve) { Log "   -NoReserve 지정 — 예약 시도 안 함. 지금 직접 예매하세요."; break }
        if (-not $flags.LoggedIn) {
            Log "   ⚠ 로그인되어 있지 않아 예약을 진행할 수 없습니다. 지금 브라우저에서 직접 예매하세요."
            break
        }
        # 좌석 셀 클릭 → 예매 버튼 탐색
        if (Invoke-VerifiedClick $best.El "좌석셀($($best.Label))") {
            Start-Sleep -Seconds 4
            $w = Get-Win
            $btn = $null
            foreach ($e in $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                                      [System.Windows.Automation.Condition]::TrueCondition)) {
                $n = $e.Current.Name
                if (-not $n) { continue }
                $t = ($e.Current.ControlType.ProgrammaticName -replace 'ControlType\.', '')
                if ($t -in @('Button', 'Hyperlink') -and $n -match '^(예매하기|예매|좌석선택|예약하기)$') {
                    $rr = $e.Current.BoundingRectangle
                    if ($rr.Y -gt 400) { $btn = $e; break }   # 상단 breadcrumb 의 '예매' 제외
                }
            }
            if ($btn) {
                if (Invoke-VerifiedClick $btn "예매버튼($($btn.Current.Name))") {
                    Start-Sleep -Seconds 8
                    Log "   예매 클릭 후 창 제목: $((Get-Process -Id $PID_T).MainWindowTitle)"
                }
            } else {
                Log "   예매 버튼을 찾지 못했습니다 — 브라우저에서 직접 이어서 진행하세요."
            }
        }
        Log "🛑 사람 확인이 필요합니다. 결제는 자동화하지 않습니다."
        break
    }

    if ($Once) { Log "-Once 지정 — 종료"; break }
    $wait = $IntervalSec + (Get-Random -Minimum -20 -Maximum 21)   # 지터
    if ($wait -lt 60) { $wait = 60 }
    Start-Sleep -Seconds $wait
}

Log "===== 종료 (정상 조회 $okCount 회) ====="
