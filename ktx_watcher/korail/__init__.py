"""Korail SPA driver — CDP-only."""


class KorailError(RuntimeError):
    """Base error."""


class CaptchaDetected(KorailError):
    """매크로/봇 가드(-8002/-8003) 감지 및 dismiss 실패."""


class LoginError(KorailError):
    """로그인 실패."""


class SiteLayoutChanged(KorailError):
    """예상 selector 가 매치되지 않음."""


class UserActionRequired(KorailError):
    """사용자 개입 필요 (예: 추가 본인인증)."""


class ReservationFailed(KorailError):
    """예매 클릭 후 예약이 실제로 성립하지 않음 (잔여석 소진 등) — 다음 iteration 재시도."""


class GuardBlocked(KorailError):
    """조회가 차단된 것으로 보임 — 결과를 '매진'으로 오인하면 안 되는 상태.

    두 가지 형태 (2026-11-03 실측, 2026-11-04 보강):
      explicit=True  : -8002/-8003 안내 모달. "매크로, 개발자도구 등 미허가 도구" 문구.
                       첫 조회 제출에만 걸리는 1회성 가드라 search 가 먼저 재조회하고,
                       재시도 후에도 0건일 때만 이 형태로 올린다.
      explicit=False : 모달 없이 빈 목록. 열차가 실재하는데도
                       '해당 스케줄에 운행하는 열차가 없습니다' 만 돌아온다.
                       (11-03 에 본 사례는 dismiss 된 -8002 였음 — 재조회 도입 후
                       이 형태가 실제로 재현되는지는 미확인.)

    중요 — '열차 row 는 나오는데 전부 매진' 은 차단이 아니다(정상 감시 상태).
    차단은 **열차 목록 자체가 사라지는** 것으로 구분한다.
    """

    def __init__(self, message: str, *, explicit: bool) -> None:
        super().__init__(message)
        self.explicit = explicit


__all__ = [
    "KorailError",
    "CaptchaDetected",
    "LoginError",
    "SiteLayoutChanged",
    "UserActionRequired",
    "ReservationFailed",
    "GuardBlocked",
]
