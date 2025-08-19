from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from .config import settings
from .utils import ensure_data_dir


_JSON_SINK_CONFIGURED = False
_JSON_LOG_PATH: Optional[Path] = None


def configure_json_logging(path: Optional[Path] = None) -> Path:
    global _JSON_SINK_CONFIGURED, _JSON_LOG_PATH
    if _JSON_SINK_CONFIGURED and _JSON_LOG_PATH:
        return _JSON_LOG_PATH
    logs_dir = ensure_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    target = path or (logs_dir / "events.jsonl")
    # Keep human console logs; add JSONL file sink
    logger.add(
        target,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        serialize=True,  # JSON lines
        rotation="100 MB",
        retention=10,  # keep last 10 rotations
    )
    _JSON_SINK_CONFIGURED = True
    _JSON_LOG_PATH = target
    return target


def log_event(event: str, **fields: Any) -> None:
    """Emit a structured JSON event into the JSON sink.

    Fields should be JSON-serializable. Adds common context: profile, proxy.
    """
    configure_json_logging()  # ensure sink exists
    payload: Dict[str, Any] = {
        "event": event,
        "ts": int(time.time()),
        "profile": _current_profile(),
        "proxy": settings.proxy_url or None,
    }
    payload.update(fields)
    # Bind for JSON sink; message equals event label
    logger.bind(**payload).info(event)


def _current_profile() -> str:
    p = Path(settings.user_data_dir)
    return p.name or "default"

