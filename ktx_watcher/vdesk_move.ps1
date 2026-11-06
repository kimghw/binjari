# Chrome 창을 별도 가상 데스크톱("binjari")으로 이동 — 사용자 화면 전환 없음.
#
# chrome_launcher.py 가 CDP 준비 후 호출한다.
# 요구사항: VirtualDesktop PowerShell 모듈 (MScholtes, PSGallery)
#   Install-Module VirtualDesktop -Scope CurrentUser -Force
# 없으면 exit 2 로 조용히 skip (런처가 경고 로그만 남김).
#
# NOTE: 문서화된 IVirtualDesktopManager.MoveWindowToDesktop 은 다른 프로세스
# 창에 Access Denied (2026-08-19 검증) — 그래서 모듈(내부 API) 사용.
#
# 2026-11-06: 갓 띄운 Chrome 창에서 Get-DesktopFromWindow/Move-Window 가
# "요소가 없습니다"(TYPE_E_ELEMENTNOTFOUND) 로 실패하는데, 예전엔 warn 만 찍고 exit 0
# 으로 끝나 런처가 성공으로 기록했다 → 창이 사용자 데스크톱에 그대로 남음.
# 이제 WaitSec 동안 창 목록을 다시 열거하며 재시도하고, 끝내 못 옮기면 exit 4 (런처가 재시도).
# 출력에 창별 hwnd/현재 데스크톱/cloaked/제목/오류를 남겨 원인 추적이 되게 한다.
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [string]$Name = 'binjari',
    [int]$WaitSec = 10
)

$ErrorActionPreference = 'Stop'
# 호출측(python)이 utf-8 로 읽음 — 한글 출력 인코딩 고정
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

try {
    Import-Module VirtualDesktop -WarningAction SilentlyContinue
} catch {
    Write-Output "SKIP: VirtualDesktop 모듈 없음 — Install-Module VirtualDesktop -Scope CurrentUser -Force"
    exit 2
}

# 1) CDP 포트를 listen 중인 Chrome 브라우저 프로세스 pid
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $conn) { Write-Output "SKIP: port $Port listener 없음"; exit 3 }
$chromePid = [uint32]$conn.OwningProcess

# 2) 해당 pid 의 보이는 top-level 창 열거 (popup 포함 — MainWindowHandle 은 1개만 줌)
Add-Type -Language CSharp @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class BinjariWinEnum
{
    delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll")] static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int n);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr hwnd, int attr, out int pv, int cb);

    public static long[] TopWindowsOfPid(uint targetPid)
    {
        // 타이틀 없는 보조 창(툴팁 등)은 가상 데스크톱 관리 대상이 아님 → 제외
        var found = new List<long>();
        EnumWindows((h, l) => {
            uint pid;
            GetWindowThreadProcessId(h, out pid);
            if (pid == targetPid && IsWindowVisible(h) && GetWindowTextLength(h) > 0)
                found.Add(h.ToInt64());
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }

    public static string Title(IntPtr h)
    {
        var sb = new StringBuilder(256);
        GetWindowText(h, sb, 256);
        return sb.ToString();
    }

    // DWMWA_CLOAKED(14): 0=보임, 1=앱, 2=셸(다른 가상 데스크톱 등), 4=상속. -1=조회 실패
    public static int Cloaked(IntPtr h)
    {
        int v;
        return DwmGetWindowAttribute(h, 14, out v, 4) == 0 ? v : -1;
    }
}
'@

# 3) 이름이 $Name 인 데스크톱 찾기, 없으면 생성 (New-Desktop 은 화면 전환 안 함)
$target = $null
$count = Get-DesktopCount
for ($i = 0; $i -lt $count; $i++) {
    if ((Get-DesktopName $i) -eq $Name) { $target = Get-Desktop $i; break }
}
if (-not $target) {
    $target = New-Desktop
    Set-DesktopName -Desktop $target -Name $Name
}
$targetIdx = Get-DesktopIndex $target

# 4) 이동 — WaitSec 동안 창 목록을 다시 열거하며 재시도.
#    FromWindow 가 실패해도 Move-Window 는 시도한다 (둘 다 실패하면 그 창은 failed).
$moved = 0; $already = 0; $failed = 0; $total = 0; $detail = @()
$deadline = (Get-Date).AddSeconds($WaitSec)
while ($true) {
    $wins = [BinjariWinEnum]::TopWindowsOfPid($chromePid)
    $moved = 0; $already = 0; $failed = 0; $total = $wins.Count; $detail = @()
    foreach ($h in $wins) {
        $hp = [IntPtr][int64]$h
        $curIdx = $null
        try { $curIdx = Get-DesktopIndex (Get-DesktopFromWindow -Hwnd $hp) } catch { }
        if ($null -ne $curIdx -and $curIdx -eq $targetIdx) { $already++; continue }
        try {
            Move-Window -Desktop $target -Hwnd $hp | Out-Null
            $moved++
        } catch {
            $failed++
            $cur = if ($null -eq $curIdx) { '?' } else { $curIdx }
            $detail += ("hwnd=$h cur=$cur cloaked=" + [BinjariWinEnum]::Cloaked($hp) +
                        " title='" + [BinjariWinEnum]::Title($hp) + "' — " + $_.Exception.Message.Trim())
        }
    }
    if ($total -gt 0 -and $failed -eq 0) {
        Write-Output "OK: moved=$moved already=$already/$total desktop='$Name'(idx=$targetIdx) pid=$chromePid"
        exit 0
    }
    if ((Get-Date) -ge $deadline) { break }
    Start-Sleep -Milliseconds 700
}
if ($total -eq 0) { Write-Output "SKIP: pid $chromePid 의 보이는 창 없음 (${WaitSec}s 대기)"; exit 4 }
Write-Output ("FAIL: moved=$moved already=$already failed=$failed/$total desktop='$Name'(idx=$targetIdx) pid=$chromePid | " +
              ($detail -join ' ; '))
exit 4
