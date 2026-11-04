"""Single-shot smoke test — CDP-only.

KTXA_USER/KTXA_PASS 가 비어있지 않으면 ensure_logged_in 도 수행.
"""

from __future__ import annotations

import logging
import sys

from .chrome_launcher import ChromeLauncher
from .config import ConfigError, load_config
from .korail import (CaptchaDetected, GuardBlocked, LoginError, SiteLayoutChanged,
                    QueryConditionMismatch, SearchResultUnavailable)
from .korail.client import KorailSPAClient
from .korail.reserve import ensure_logged_in
from .korail.search import perform_search


def main() -> int:
    try:
        config = load_config()
    except ConfigError as e:
        print(f"[smoke_test] CONFIG ERROR: {e}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.ktxa_log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("ktx_watcher_spa.smoke_test")

    print(
        f"[smoke_test] mode={config.ktxa_mode} "
        f"{config.ktxa_origin}→{config.ktxa_dest} "
        f"date={config.ktxa_date.isoformat()} "
        f"times={[t.strftime('%H:%M') for t in config.ktxa_times]} "
        f"train_type={config.ktxa_train_type}"
    )

    launcher = ChromeLauncher(
        port=config.ktxa_cdp_port,
        user_data_dir=config.ktxa_cdp_user_data_dir,
        exe_path=config.ktxa_chrome_exe,
        startup_timeout=config.ktxa_cdp_startup_timeout,
    )
    cdp_url = launcher.ensure_running()
    print(f"[smoke_test] cdp_url={cdp_url}")

    do_login = bool(
        config.ktxa_user
        and config.ktxa_pass
        and config.ktxa_user.lower() != "dummy"
        and config.ktxa_pass.lower() != "dummy"
    )
    print(f"[smoke_test] login_first={do_login}")

    candidates = []
    err = None
    try:
        with KorailSPAClient(cdp_url) as client:
            if do_login:
                try:
                    ensure_logged_in(client, config)
                    print("[smoke_test] ✓ login OK")
                except LoginError as e:
                    print(f"[smoke_test] LOGIN FAILED: {e}")
                    raise
            candidates = perform_search(client, config)
    except LoginError as e:
        err = ("LoginError", str(e))
    except GuardBlocked as e:
        # 예상 못한 오류가 아니라 '차단' 이다 — traceback 없이 명확히 보고.
        err = ("GuardBlocked", str(e))
        print(f"[smoke_test] BLOCKED: {e}")
        print("[smoke_test] → '열차 없음/매진' 이 아니라 조회가 차단된 상태입니다.")
        log.warning("GuardBlocked: %s", e)
    except CaptchaDetected as e:
        err = ("CaptchaDetected", str(e))
        log.warning("Captcha: %s", e)
    except (QueryConditionMismatch, SearchResultUnavailable) as e:
        err = (type(e).__name__, str(e))
        log.error("조회 검증 실패 (차단 미확정): %s", e)
    except SiteLayoutChanged as e:
        err = ("SiteLayoutChanged", str(e))
        log.warning("Layout: %s", e)
    except Exception as e:
        err = (e.__class__.__name__, str(e))
        log.exception("Unexpected: %s", e)
    finally:
        launcher.shutdown_if_owned()

    print("=" * 60)
    print(f"[smoke_test] candidates: {len(candidates)}")
    print("=" * 60)
    for i, c in enumerate(candidates):
        print(
            f"  [{i:>2}] {c['depart']}  {c.get('train_name', '?'):<12}  "
            f"{c['origin']}→{c['dest']}  seat={c['seat_class']:<6}  status={c.get('status', '')!r}"
        )

    if err:
        print(f"[smoke_test] error: {err[0]}: {err[1]}")
        return 1
    if not candidates:
        print("[smoke_test] 조회 성공, 조건에 맞는 예약 후보 없음 (매진/시간/좌석 조건 확인).")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
