from __future__ import annotations
import json, os, time, uuid, traceback
from typing import Any, Dict, Optional

_SESSION_ID = uuid.uuid4().hex[:12]
_START_TS = time.time()

def _addon_root() -> str:
    try:
        return os.path.dirname(__file__)
    except Exception:
        return os.getcwd()

def _state_dir() -> str:
    # Try importing STATE_DIR from the add-on if available to keep log location consistent
    try:
        from .__init__ import STATE_DIR  # type: ignore
        os.makedirs(STATE_DIR, exist_ok=True)
        return STATE_DIR
    except Exception:
        p = os.path.join(_addon_root(), "user_files", "_state")
        os.makedirs(p, exist_ok=True)
        return p

def _log_path() -> str:
    return os.path.join(_state_dir(), "addon.log")

def _should_rotate(path: str, max_kb: int = 2048) -> bool:
    try:
        return os.path.exists(path) and (os.path.getsize(path) > max_kb * 1024)
    except Exception:
        return False

def _rotate(path: str) -> None:
    try:
        if not os.path.exists(path):
            return
        bak = path + ".1"
        if os.path.exists(bak):
            try: os.remove(bak)
            except Exception: pass
        try: os.rename(path, bak)
        except Exception: pass
    except Exception:
        pass

_LEVELS = {"DEBUG":10, "INFO":20, "WARN":30, "ERROR":40}

def _min_level() -> int:
    try:
        # Read from add-on config if available
        from .__init__ import get_config  # type: ignore
        cfg = get_config() or {}
        lv = str(cfg.get("log_level", "INFO")).upper()
        return _LEVELS.get(lv, 20)
    except Exception:
        return 20

class scope:
    def __init__(self, event: str, **fields: Any):
        self.event = event
        self.fields = fields or {}
        self.t0 = time.time()
        log(event + ".start", **self.fields)
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        ms = round((time.time() - self.t0) * 1000, 1)
        if exc is not None:
            log(self.event + ".error", ms=ms, error=f"{exc_type.__name__}: {exc}", **self.fields)
            return False
        log(self.event + ".end", ms=ms, **self.fields)
        return False

def log(event: str, level: str = "INFO", **fields: Any) -> None:
    """Structured JSONL logging with a session and monotonic timestamp.

    Example: log("glossary.open", id="ttp", ok=True)
    """
    try:
        # level filter
        lvl = _LEVELS.get(level.upper(), 20)
        if lvl < _min_level():
            return
        path = _log_path()
        if _should_rotate(path):
            _rotate(path)
        rec: Dict[str, Any] = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "ts": round(time.time(), 3),
            "uptime": round(time.time() - _START_TS, 3),
            "session": _SESSION_ID,
            "level": level.upper(),
            "event": event,
        }
        if fields:
            # Avoid dumping giant blobs
            try:
                for k, v in list(fields.items()):
                    if isinstance(v, str) and len(v) > 2000:
                        fields[k] = v[:2000] + "…"
            except Exception:
                pass
            rec.update(fields)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        # Never raise from logger
        pass

def log_exc(event: str, err: BaseException, **fields: Any) -> None:
    tb = traceback.format_exc()
    fields = dict(fields or {})
    fields.update({"error": f"{type(err).__name__}: {err}", "trace": tb})
    log(event, level="ERROR", **fields)
