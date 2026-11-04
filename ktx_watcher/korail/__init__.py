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


class QueryConditionMismatch(KorailError):
    """화면의 실제 조회 조건이 요청과 다르거나 확인되지 않음."""


class SearchResultUnavailable(KorailError):
    """열차 목록이 비어 있거나 불완전함. 차단으로 확정하지 않는다."""


class GuardBlocked(KorailError):
    """명시적인 차단 안내를 확인함. 빈 목록만으로 이 예외를 만들지 않는다."""

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
    "QueryConditionMismatch",
    "SearchResultUnavailable",
]
