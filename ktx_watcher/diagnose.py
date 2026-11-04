"""Run one query and retain evidence without logging in or reserving a seat.

Usage: python -m ktx_watcher.diagnose [--output runs/diagnose/example]
The existing browser session is reused and left open after the diagnostic.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .chrome_launcher import ChromeLauncher
from .config import KTXAConfig, _apply_rail_fallback, _load_env_files
from .korail.client import KorailSPAClient
from .korail.search import _parse_result_rows, perform_search


LOGGER = logging.getLogger("ktx_watcher.diagnose")
KOREA = ZoneInfo("Asia/Seoul")


def _query_config() -> KTXAConfig:
    """Override the environment copy before validation; never edit .env files."""
    _load_env_files()
    data = dict(os.environ)
    _apply_rail_fallback(data)
    data.update({
        "KTXA_MODE": "search", "KTXA_ONCE": "true",
        "KTXA_USER": "", "KTXA_PASS": "",
        "KTXA_PAYMENT_MODE": "false", "KTXA_TRANSFER_ENABLED": "false",
        "KTXA_TRANSFER_SEND": "false", "TEAMS_ENABLED": "false",
        "KTXA_VDESK": "false",
    })
    for key in tuple(data):
        if key.startswith("PAY_") or key.startswith("KTXA_TRANSFER_") and key not in {
            "KTXA_TRANSFER_ENABLED", "KTXA_TRANSFER_SEND",
        }:
            data[key] = ""
    return KTXAConfig.model_validate(data)


class Redactor:
    def __init__(self) -> None:
        names = {"KTXA_USER", "KTXA_PASS", "TEAMS_USER_EMAIL", "TEAMS_CHAT_ID",
                 "KTXA_TRANSFER_MEMBER_NO", "KTXA_TRANSFER_NAME", "KTXA_TRANSFER_PHONE",
                 "PAY_CARD_NUM", "PAY_CARD_PW2", "PAY_ID6"}
        # Expiry month/year and short numeric PINs also occur in ordinary dates,
        # times and counts. Mask those only in a named sensitive field.
        self.values = sorted({value for key, value in os.environ.items()
                              if len(value) >= 4 and (key in names
                                                     or "SECRET" in key or "TOKEN" in key)},
                             key=len, reverse=True)
        self.named_value = re.compile(
            r"(?P<label>\b(?:KTXA_USER|KTXA_PASS|PAY_[A-Z0-9_]+|"
            r"KTXA_TRANSFER_(?:MEMBER_NO|NAME|PHONE)|"
            r"password|passwd|secret|token|pin|card_number|card_pw2)\b"
            r"\s*(?:[:=]\s*|\s+))"
            r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
            re.IGNORECASE,
        )

    def __call__(self, text: str) -> str:
        text = self.named_value.sub(lambda match: match["label"] + "[redacted]", text)
        for value in self.values:
            text = text.replace(value, "[redacted]")
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
        return text


class _SafeFormatter(logging.Formatter):
    def __init__(self, redact: Redactor) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self.redact = redact

    def format(self, record: logging.LogRecord) -> str:
        return self.redact(super().format(record))


@contextmanager
def _trace_logging(output: Path, redact: Redactor):
    root = logging.getLogger()
    previous_handlers, previous_level = root.handlers[:], root.level
    handlers = [logging.StreamHandler(sys.stdout),
                logging.FileHandler(output / "trace.log", encoding="utf-8")]
    for handler in handlers:
        handler.setFormatter(_SafeFormatter(redact))
    root.handlers, root.level = handlers, logging.INFO
    try:
        yield
    finally:
        root.handlers, root.level = previous_handlers, previous_level
        for handler in handlers:
            handler.close()


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _page_evidence(page, output: Path, label: str) -> dict:
    """Only trip fields and visible modal text; never serialize input forms."""
    evidence: dict = {"url": _safe_url(page.url)}
    try:
        evidence.update(page.evaluate("""() => ({
            fields: Object.fromEntries([
                ['origin', "input[name='txtGoStart']"],
                ['dest', "input[name='txtGoEnd']"],
                ['date', 'input#startDate']
            ].map(([key, sel]) => [key, document.querySelector(sel)?.value ?? null])),
            passengers: document.querySelector('a.data.btn_pop')?.innerText || null,
            row_count: document.querySelectorAll('li.tckList').length,
            modals: [...document.querySelectorAll('.ReactModal__Content, [role=dialog]')]
                .filter(el => el.getClientRects().length &&
                    getComputedStyle(el).visibility !== 'hidden')
                .map(el => el.innerText.slice(0, 1500))
        })"""))
    except Exception as exc:
        evidence["read_error"] = {"type": type(exc).__name__, "message": str(exc)}
    try:
        filename = f"{label}.png"
        # Mask credential/payment controls if an unexpected navigation reached them.
        page.screenshot(path=str(output / filename), full_page=True,
                        mask=[page.locator("input[type=password], input#id, "
                                           "input[autocomplete=cc-number], "
                                           "input[autocomplete=cc-csc]")])
        evidence["screenshot"] = filename
    except Exception as exc:
        evidence["screenshot_error"] = {"type": type(exc).__name__, "message": str(exc)}
    return evidence


def _safe_rows(rows: list[dict]) -> list[dict]:
    keys = ("depart", "train_name", "train_number", "general_status", "first_status",
            "seat_class", "status_kind", "status", "origin", "dest", "date")
    return [{key: row[key] for key in keys if key in row} for row in rows]


def _sanitize(value, redact: Redactor):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: ("[redacted]" if _sensitive_key(key) else _sanitize(item, redact))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, redact) for item in value]
    return value


def _sensitive_key(key: str) -> bool:
    upper = key.upper()
    return (upper.startswith("PAY_") or "SECRET" in upper or "TOKEN" in upper or
            upper in {"KTXA_USER", "KTXA_PASS", "PASSWORD", "PASSWD", "PIN",
                      "CARD_NUMBER", "CARD_PW2", "USERNAME", "USER",
                      "KTXA_TRANSFER_MEMBER_NO", "KTXA_TRANSFER_NAME", "KTXA_TRANSFER_PHONE"})


def _guard_events(page) -> list[dict]:
    events = list(getattr(page, "_guard_events", []))
    context = getattr(page, "context", None)
    for event in getattr(context, "_guard_events", []):
        if event not in events:
            events.append(event)
    return events


def run_diagnosis(config: KTXAConfig, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    redact = Redactor()
    # Enforce query-only behavior even when this function is called with a reserve config.
    config = config.model_copy(update={
        "ktxa_mode": "search", "ktxa_once": True, "ktxa_user": "", "ktxa_pass": "",
        "ktxa_payment_mode": False, "ktxa_transfer_enabled": False,
        "ktxa_transfer_send": False, "teams_enabled": False, "ktxa_vdesk": False,
        "ktxa_log_dir": output,
    })
    report: dict = {
        "started_at": datetime.now(KOREA).isoformat(), "mode": "query_only",
        "config": {
            "origin": config.ktxa_origin, "dest": config.ktxa_dest,
            "date": config.ktxa_date.isoformat(),
            "times": [value.strftime("%H:%M") for value in config.ktxa_times],
            "time_window": ([value.strftime("%H:%M") for value in config.ktxa_time_window]
                            if config.ktxa_time_window else None),
            "tolerance_min": config.ktxa_tolerance_min,
            "train_type": config.ktxa_train_type, "seat_class": config.ktxa_seat_class,
            "passengers": config.passenger_counts(), "seated_only": config.ktxa_seated_only,
            "include_srt": config.ktxa_include_srt,
        },
        "status": "starting", "rows": [], "candidates": [], "guard_events": [],
    }
    with _trace_logging(output, redact):
        LOGGER.info("Query-only diagnostic: %s", json.dumps(report["config"], ensure_ascii=False))
        try:
            launcher = ChromeLauncher(
                port=config.ktxa_cdp_port, user_data_dir=config.ktxa_cdp_user_data_dir,
                exe_path=config.ktxa_chrome_exe, startup_timeout=config.ktxa_cdp_startup_timeout,
            )
            with KorailSPAClient(launcher.ensure_running()) as client:
                page = client.main_page()
                report["start"] = _page_evidence(page, output, "start")
                try:
                    report["status"] = "querying"
                    candidates = perform_search(client, config)
                    report["candidates"] = _safe_rows(candidates)
                    report["status"] = "ok"
                finally:
                    report["guard_events"] = _guard_events(page)
                    report["end"] = _page_evidence(page, output, "end")
                    if "/search/list" in page.url:
                        try:
                            report["rows"] = _safe_rows(_parse_result_rows(page))
                        except Exception as exc:
                            report["row_read_error"] = {
                                "type": type(exc).__name__, "message": str(exc),
                            }
        except Exception as exc:
            report["status"] = "error"
            report["error"] = {"type": type(exc).__name__, "message": str(exc)}
            if hasattr(exc, "explicit"):
                report["error"]["explicit"] = exc.explicit
            LOGGER.error("%s: %s", type(exc).__name__, exc)
        report["finished_at"] = datetime.now(KOREA).isoformat()
        # Redact the serialized report before it reaches disk or callers.
        serialized = json.dumps(_sanitize(report, redact), ensure_ascii=False, indent=2, default=str)
        (output / "report.json").write_text(serialized, encoding="utf-8")
        LOGGER.info("Diagnostic %s: %d rows, %d candidates; report=%s",
                    report["status"], len(report["rows"]), len(report["candidates"]),
                    output / "report.json")
        return json.loads(serialized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("runs/diagnose") / datetime.now(KOREA).strftime("%Y%m%d-%H%M%S-%f"))
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        config = _query_config()
    except ValidationError as exc:
        details = exc.errors(include_input=False, include_context=False, include_url=False)
        print("ConfigurationError: " + Redactor()(json.dumps(details, ensure_ascii=False)))
        return 2
    report = run_diagnosis(config, args.output)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
