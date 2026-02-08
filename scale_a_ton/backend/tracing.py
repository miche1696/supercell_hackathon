from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


TRACE_ENABLED = os.getenv("TRACE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
TRACE_STDOUT = os.getenv("TRACE_STDOUT", "1").strip().lower() not in {"0", "false", "no", "off"}
TRACE_FILE = os.getenv("TRACE_FILE", "logs/trace.ndjson")
TRACE_MAX_VALUE_LEN = int(os.getenv("TRACE_MAX_VALUE_LEN", "300"))

_TRACE_LOCK = threading.Lock()
_TRACE_FILE_PATH = Path(TRACE_FILE)

if TRACE_ENABLED and TRACE_FILE:
    _TRACE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(value: str) -> str:
    if len(value) <= TRACE_MAX_VALUE_LEN:
        return value
    return value[: TRACE_MAX_VALUE_LEN - 3] + "..."


def _sanitize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v) for v in value]
    return _truncate(repr(value))


def trace_event(component: str, event: str, *, trace_id: Optional[str] = None, level: str = "INFO", **fields: Any) -> None:
    if not TRACE_ENABLED:
        return

    record: Dict[str, Any] = {
        "ts": _utc_now_iso(),
        "level": level.upper(),
        "component": component,
        "event": event,
        "trace_id": trace_id or "-",
        "thread": threading.current_thread().name,
    }
    for key, value in fields.items():
        record[key] = _sanitize(value)

    line = json.dumps(record, ensure_ascii=True)

    with _TRACE_LOCK:
        if TRACE_FILE:
            with _TRACE_FILE_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if TRACE_STDOUT:
            print(line, flush=True)


@contextlib.contextmanager
def trace_span(component: str, span_name: str, *, trace_id: Optional[str] = None, **fields: Any) -> Iterator[str]:
    span_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    trace_event(component, f"{span_name}.start", trace_id=trace_id, span_id=span_id, **fields)
    try:
        yield span_id
    except Exception as exc:  # pragma: no cover - debugging path
        trace_event(
            component,
            f"{span_name}.error",
            trace_id=trace_id,
            span_id=span_id,
            level="ERROR",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        trace_event(component, f"{span_name}.end", trace_id=trace_id, span_id=span_id, elapsed_ms=elapsed_ms)
