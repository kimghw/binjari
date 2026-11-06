"""Chrome 디버그 인스턴스 관리 (subprocess + 헬스체크).

watcher 가 직접 chrome.exe 를 ``--remote-debugging-port=<port>`` 로 띄우고,
9222 헬스 엔드포인트(``/json/version``) 가 응답할 때까지 polling 한다.

- 이미 같은 포트에 Chrome 이 살아있으면 그대로 재사용 (subprocess 안 띄움).
- watcher 가 띄운 경우, 종료 시 같은 프로세스를 terminate.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger("ktx_watcher_spa.chrome_launcher")


def _force_ipv4_for_localhost() -> None:
    """Windows + Chrome CDP 호환: 'localhost' 를 IPv4(127.0.0.1) 만 해석되게 한다.

    Chrome 의 ``--remote-debugging-port`` 는 0.0.0.0(IPv4) 만 listen 하는데
    Python 의 ``socket.getaddrinfo`` 는 IPv6(::1) 을 우선 반환해 EADDRINUSE 가 난다.
    playwright 의 connect_over_cdp 도 같은 경로를 탄다.
    """
    if getattr(_force_ipv4_for_localhost, "_applied", False):
        return
    orig = socket.getaddrinfo

    def _ipv4_only(host, port, *args, **kwargs):
        if isinstance(host, str) and host.lower() in ("localhost", "::1"):
            host = "127.0.0.1"
        # AF_INET 만 반환하도록 family 인자도 제한
        if len(args) >= 1:
            args = (socket.AF_INET,) + args[1:]
        else:
            kwargs["family"] = socket.AF_INET
        return orig(host, port, *args, **kwargs)

    socket.getaddrinfo = _ipv4_only  # type: ignore[assignment]
    _force_ipv4_for_localhost._applied = True  # type: ignore[attr-defined]
    LOGGER.debug("socket.getaddrinfo monkey-patched → IPv4 only for localhost")


# 모듈 import 시점에 즉시 적용 (urllib / playwright 모두 영향받기 전에)
_force_ipv4_for_localhost()

DEFAULT_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _cdp_alive(port: int, retries: int = 2, http_timeout: float = 5.0) -> bool:
    """포트가 열려있고 ``/json/version`` 이 응답하면 True.

    NOTE: Chrome DevTools 는 Host=127.0.0.1 을 거부 (RemoteDisconnected).
    URL 은 반드시 ``localhost`` 로 호출해야 함. (검증 2026-05-14)
    """
    if not _port_open("127.0.0.1", port, timeout=1.0):
        return False
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(f"http://localhost:{port}/json/version")
            with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception as e:
            LOGGER.debug("CDP probe attempt=%d 실패: %s", attempt + 1, e)
        time.sleep(0.3)
    return False


def _pid_is_watcher(pid: int) -> bool:
    """pid 가 살아있는 python 프로세스인지 (제어권 잠금 파일의 주인이 아직 도는지)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, errors="replace", timeout=5,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            ).stdout
        except Exception:
            return False
        first = out.strip().splitlines()[0] if out.strip() else ""
        return first.startswith('"') and "python" in first.lower()
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class ChromeLauncher:
    """chrome.exe 를 디버그 모드로 띄우고 lifecycle 을 관리.

    Usage:
        launcher = ChromeLauncher(port=9222, user_data_dir=..., exe_path=...)
        launcher.ensure_running()
        ...
        launcher.shutdown_if_owned()
    """

    def __init__(
        self,
        port: int = 9222,
        user_data_dir: Optional[Path] = None,
        exe_path: Optional[str] = None,
        startup_timeout: float = 15.0,
        vdesk: bool = False,
        vdesk_name: str = "binjari",
    ) -> None:
        self.port = port
        self.user_data_dir = (
            Path(user_data_dir).expanduser() if user_data_dir else None
        )
        self.exe_path = exe_path or self._find_chrome_exe()
        self.startup_timeout = startup_timeout
        self.vdesk = vdesk
        self.vdesk_name = vdesk_name
        self._proc: Optional[subprocess.Popen] = None  # watcher 가 띄운 경우만 set
        self._reused_existing = False
        self._owner_lock: Optional[Path] = None

    @staticmethod
    def _find_chrome_exe() -> str:
        for p in DEFAULT_CHROME_PATHS:
            if os.path.isfile(p):
                return p
        raise RuntimeError(
            "chrome.exe 경로를 찾지 못했습니다. KTXA_CHROME_EXE 환경변수로 지정하세요."
        )

    @property
    def cdp_url(self) -> str:
        return f"http://localhost:{self.port}"

    def ensure_running(self) -> str:
        """Chrome 디버그 인스턴스가 살아있도록 보장. CDP URL 반환."""
        if _cdp_alive(self.port):
            self._claim_control()   # 다른 워처가 제어 중이면 여기서 RuntimeError
            LOGGER.info("Chrome 디버그 인스턴스 이미 살아있음: port=%d (재사용)", self.port)
            self._reused_existing = True
            self._move_to_vdesk()
            return self.cdp_url
        self._claim_control()

        args = [
            self.exe_path,
            f"--remote-debugging-port={self.port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            # 다른 가상 데스크톱/가려진 창에서도 렌더링·타이머 스로틀링 방지.
            # PasswordLeakDetection: 로그인 뒤 Chrome 자체 "비밀번호 유출" 대화상자가 페이지 입력을
            # 막아 워처가 죽음 (2026-11-07 01:16 실측: 1건 발권 후 인원 팝업 클릭 무반응 → 종료).
            "--disable-features=CalculateNativeWinOcclusion,PasswordLeakDetection",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            # watcher 가 terminate 로 끝낸 뒤 다음 기동 때 뜨는 "페이지를 복원하시겠습니까?" 풍선 숨김
            "--hide-crash-restore-bubble",
        ]
        if self.user_data_dir:
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
            args.append(f"--user-data-dir={self.user_data_dir}")
        args.append("about:blank")

        self._mark_clean_exit()
        LOGGER.info("Chrome 디버그 모드 기동: %s (port=%d)", self.exe_path, self.port)
        # stdout/stderr 는 무시 (Chrome 이 콘솔에 잡히면 종료 시 같이 죽음 회피)
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        # CDP 가 떴는지 polling
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if _cdp_alive(self.port):
                LOGGER.info("Chrome CDP 준비 완료 (port=%d)", self.port)
                self._move_to_vdesk()
                return self.cdp_url
            time.sleep(0.3)

        # timeout → 정리
        self.shutdown_if_owned()
        raise RuntimeError(
            f"Chrome 디버그 포트 {self.port} 가 {self.startup_timeout}s 안에 응답하지 않음"
        )

    def _mark_clean_exit(self) -> None:
        """프로필 Preferences 의 종료 상태를 '정상' 으로 바꿔 "페이지를 복원하시겠습니까?" 풍선을 막는다.

        watcher 는 Chrome 을 terminate 로 끝내므로 다음 기동 때 Chrome 이 비정상 종료로 본다
        (2026-11-07 01:2x 실측, 사용자 보고). 플래그(--hide-crash-restore-bubble)와 이중 방어.
        """
        if not self.user_data_dir:
            return
        prefs = Path(self.user_data_dir) / "Default" / "Preferences"
        if not prefs.is_file():
            return
        try:
            data = json.loads(prefs.read_text(encoding="utf-8"))
            prof = data.setdefault("profile", {})
            if prof.get("exit_type") == "Normal" and prof.get("exited_cleanly") is True:
                return
            prof["exit_type"] = "Normal"
            prof["exited_cleanly"] = True
            prefs.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            LOGGER.info("Chrome 프로필 종료 상태를 정상으로 표시 (복원 풍선 방지)")
        except Exception as e:
            LOGGER.debug("Preferences 수정 실패(무시): %s", e)

    def _move_to_vdesk(self) -> None:
        """Chrome 창을 별도 가상 데스크톱(vdesk_name)으로 이동. 실패해도 진행.

        vdesk_move.ps1 이 VirtualDesktop 모듈(내부 API)로 이동한다 —
        문서화된 IVirtualDesktopManager 는 타 프로세스 창에 Access Denied.
        창이 CDP 준비보다 늦게 뜰 수 있어 짧게 재시도한다.
        """
        if not self.vdesk:
            return
        script = Path(__file__).with_name("vdesk_move.ps1")
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script),
            "-Port", str(self.port), "-Name", self.vdesk_name,
        ]
        for attempt in range(3):
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30.0,
                    encoding="utf-8", errors="replace",
                )
            except Exception as e:
                LOGGER.warning("vdesk 이동 실행 실패: %s", e)
                return
            out = (r.stdout or "").strip()
            if r.returncode == 0:
                LOGGER.info("Chrome 창 가상 데스크톱 이동: %s", out)
                return
            if r.returncode == 4:  # 창이 아직 안 뜸 / 이동 실패("요소가 없습니다" 등) → 재시도
                LOGGER.warning("vdesk 이동 재시도 [%d/3]: %s", attempt + 1, out)
                time.sleep(2.0)
                continue
            LOGGER.warning(
                "vdesk 이동 skip (exit=%d): %s %s",
                r.returncode, out, (r.stderr or "").strip()[:200],
            )
            return
        LOGGER.warning(
            "vdesk 이동 포기 — Chrome 창이 사용자 데스크톱에 남아 있을 수 있음 (port=%d)", self.port
        )

    # ── 제어권 잠금 ────────────────────────────────────────────────────
    # 같은 디버그 포트의 Chrome 에 워처가 둘 붙으면 한쪽이 다른 쪽 페이지를 조작해 깨진다
    # (2026-11-06 18:25 실측: CLI 검증 실행이 웹 워처의 Chrome 에 '재사용' 으로 붙어 웹 워처가 죽음).
    # 제어 중인 프로세스 pid 를 프로필 폴더의 잠금 파일에 남기고, 살아있는 다른 워처가 있으면 거부한다.

    def _lock_path(self) -> Path:
        base = self.user_data_dir or Path(tempfile.gettempdir())
        return base / f"ktx_watcher_cdp_{self.port}.owner"

    def _claim_control(self) -> None:
        path = self._lock_path()
        try:
            raw = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        except Exception:
            raw = ""
        if raw.isdigit() and int(raw) != os.getpid() and _pid_is_watcher(int(raw)):
            raise RuntimeError(
                f"다른 워처(pid={raw})가 Chrome 디버그 포트 {self.port} 를 제어 중입니다 — "
                "동시에 붙으면 상대 조회가 깨집니다. 그 워처를 먼저 중지하거나 KTXA_CDP_PORT 를 바꾸세요."
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(os.getpid()), encoding="utf-8")
            self._owner_lock = path
        except Exception as e:
            LOGGER.warning("제어권 잠금 파일 기록 실패 (계속 진행): %s", e)

    def _release_control(self) -> None:
        path, self._owner_lock = self._owner_lock, None
        if path is None:
            return
        try:
            if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink()
        except Exception as e:
            LOGGER.debug("제어권 잠금 해제 실패: %s", e)

    def release_control(self) -> None:
        """잠금만 해제 (Chrome 은 그대로). 수명을 관리하지 않는 일회성 호출자(웹서버 시간표 조회)용."""
        self._release_control()

    def shutdown_if_owned(self) -> None:
        """watcher 가 띄운 인스턴스만 종료. 사용자가 띄운 건 건드리지 않음. 제어권 잠금은 항상 해제."""
        self._release_control()
        if self._reused_existing or self._proc is None:
            return
        try:
            LOGGER.info("Chrome 디버그 인스턴스 종료 (watcher-owned)")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception as e:
            LOGGER.warning("Chrome 종료 실패: %s", e)
        finally:
            self._proc = None


__all__ = ["ChromeLauncher", "_cdp_alive"]
