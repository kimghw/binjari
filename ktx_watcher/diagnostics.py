"""Persist explicit guard evidence before its dialog is dismissed."""

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)


def record_guard(page, notice: dict, stage: str) -> dict:
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d-%H%M%S-%f")
    event = {"stage": stage, "code": notice.get("code", ""),
             "message": notice["message"], "url": page.url}
    events = getattr(page, "_guard_events", [])
    events.append(event)
    page._guard_events = events[-20:]
    try:
        folder = Path("runs/guards")
        folder.mkdir(parents=True, exist_ok=True)
        screenshot = folder / f"{stamp}.png"
        page.screenshot(path=str(screenshot), timeout=5000)
        event["screenshot"] = str(screenshot)
    except Exception as exc:
        LOGGER.warning("차단 화면 캡처 실패: %s", type(exc).__name__)
    try:
        record = Path("runs/guards") / f"{stamp}.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        event["record"] = str(record)
        record.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        LOGGER.warning("차단 기록 저장 실패: %s", type(exc).__name__)
    LOGGER.warning("명시적 차단 안내: stage=%s code=%s evidence=%s",
                   stage, event["code"] or "문구", event.get("record", "저장 실패"))
    return event


def record_payment_evidence(page, stage: str, text: str = "") -> dict:
    """결제 단계 화면·모달 텍스트를 runs/payment 에 남긴다.

    2026-11-07 00:35 실패: 결제 응답 모달을 '확인' 자동 클릭으로 닫아 거절 사유가 유실됐다 →
    모달이 보이는 순간, 완료 시, 미완료 판정 시 각각 스크린샷 + json 을 남긴다.
    """
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d-%H%M%S-%f")
    event = {"stage": stage, "text": text, "url": getattr(page, "url", "")}
    folder = Path("runs/payment")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        screenshot = folder / f"{stamp}-{stage}.png"
        page.screenshot(path=str(screenshot), timeout=5000)
        event["screenshot"] = str(screenshot)
    except Exception as exc:
        LOGGER.warning("결제 화면 캡처 실패: %s", type(exc).__name__)
    try:
        record = folder / f"{stamp}-{stage}.json"
        record.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        event["record"] = str(record)
    except OSError as exc:
        LOGGER.warning("결제 기록 저장 실패: %s", type(exc).__name__)
    LOGGER.info("결제 증거 저장: stage=%s %s", stage, event.get("record", "저장 실패"))
    return event
