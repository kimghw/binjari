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
