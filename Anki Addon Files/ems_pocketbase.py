from __future__ import annotations
import json, os, time, urllib.request, urllib.error, socket
from typing import Dict, Any, Tuple, Optional
from . import ems_logging as LOG
import threading
from datetime import datetime

# These are imported lazily inside functions to avoid import cycles

_RATING_CACHE: Dict[str, Dict[str, Any]] = {}
_TERM_ID_CACHE: Dict[str, str] = {}

def _state_paths():
    from .__init__ import STATE_DIR
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, "pb_auth.json")

def _offline_path() -> str:
    from .__init__ import STATE_DIR
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, "offline_state.json")

def _read_offline_state() -> Dict[str, Any]:
    try:
        p = _offline_path()
        if os.path.exists(p):
            return json.load(open(p, "r", encoding="utf-8")) or {}
    except Exception:
        pass
    return {}

def _write_offline_state(obj: Dict[str, Any]) -> None:
    try:
        p = _offline_path()
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _mark_connect_fail(reason: str) -> None:
    """Track transient failures without immediately forcing offline.

    We only flip to offline after 2 consecutive connectivity errors
    to avoid false positives from 404s or hook route misses.
    """
    try:
        st = _read_offline_state() or {}
        fails = int(st.get("fails", 0) or 0) + 1
        st["fails"] = fails
        st["last_err"] = reason
        _write_offline_state(st)
    except Exception:
        pass

def _reset_connect_fail() -> None:
    try:
        st = _read_offline_state() or {}
        changed = False
        if st.get("fails"):
            st["fails"] = 0; changed = True
        # track last successful time to avoid flap
        st["last_ok_ts"] = int(time.time())
        if changed or ("last_ok_ts" not in st):
            _write_offline_state(st)
    except Exception:
        pass

def _is_connectivity_error(e: Exception) -> bool:
    if isinstance(e, urllib.error.URLError):
        return True
    if isinstance(e, (TimeoutError, ConnectionRefusedError, ConnectionResetError, socket.gaierror, socket.timeout)):
        return True
    s = (str(e) or "").lower()
    for kw in ("timed out", "connection refused", "offline", "failed to establish", "name resolution", "getaddrinfo", "remote end closed"):
        if kw in s:
            return True
    return False

def _tama_meta_path() -> str:
    # Where we persist the remote record id for tamagotchi state
    from .__init__ import STATE_DIR
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, "tamagotchi_pb_meta.json")

def _hooks_state_path() -> str:
    from .__init__ import STATE_DIR
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, "pb_hooks.json")

def _load_hooks_state() -> Dict[str, Any]:
    try:
        p = _hooks_state_path()
        if os.path.exists(p):
            return json.load(open(p, "r", encoding="utf-8")) or {}
    except Exception:
        pass
    return {}

def _save_hooks_state(data: Dict[str, Any]) -> None:
    try:
        p = _hooks_state_path()
        cur = _load_hooks_state()
        cur.update(data)
        json.dump(cur, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass

def _load_tama_meta() -> Dict[str, Any]:
    try:
        p = _tama_meta_path()
        if os.path.exists(p):
            return json.load(open(p, "r", encoding="utf-8")) or {}
    except Exception:
        pass
    return {}

def _save_tama_meta(meta: Dict[str, Any]) -> None:
    try:
        p = _tama_meta_path()
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_auth() -> Dict[str, Any]:
    try:
        p = _state_paths()
        if os.path.exists(p):
            return json.load(open(p, "r", encoding="utf-8")) or {}
    except Exception:
        pass
    return {}

def save_auth(data: Dict[str, Any]) -> None:
    try:
        p = _state_paths()
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass

def clear_auth() -> None:
    try:
        p = _state_paths()
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass

# ---------------- Offline mode management ----------------

def is_offline() -> bool:
    st = _read_offline_state() or {}
    return bool(st.get("offline"))

def _notify_offline_once(msg: str) -> None:
    # Debounce notifications to at most once per session window
    st = _read_offline_state() or {}
    last_note = int(st.get("last_notify", 0) or 0)
    now = int(time.time())
    if now - last_note < 30:
        return
    st["last_notify"] = now
    _write_offline_state(st)
    try:
        from aqt import mw
        from aqt.utils import tooltip
        def _show():
            try:
                tooltip(msg, period=5000)
            except Exception:
                pass
        try:
            mw.taskman.run_on_main(_show)
        except Exception:
            _show()
    except Exception:
        pass

def set_offline(on: bool, reason: str = "") -> None:
    st = _read_offline_state() or {}
    prev = bool(st.get("offline"))
    st["offline"] = bool(on)
    st["ts"] = int(time.time())
    if reason:
        st["reason"] = str(reason)
    _write_offline_state(st)
    if on and not prev:
        try:
            from . import ems_logging as LOG
            LOG.log("pb.offline", reason=reason or "")
        except Exception:
            pass
        _notify_offline_once("PocketBase unreachable. Offline mode enabled.")
    if (not on) and prev:
        try:
            from . import ems_logging as LOG
            LOG.log("pb.online")
        except Exception:
            pass
        try:
            from aqt import mw
            from aqt.utils import tooltip
            def _show():
                try:
                    tooltip("Reconnected to PocketBase. Online mode.")
                except Exception:
                    pass
            try:
                mw.taskman.run_on_main(_show)
            except Exception:
                _show()
        except Exception:
            pass

def _base_url_from_auth() -> str:
    a = load_auth() or {}
    return (a.get("base_url") or "").strip()

def ping(base_url: Optional[str] = None, timeout: int = 5) -> bool:
    """Lightweight health check to detect connectivity to PocketBase."""
    # Fallback order: explicit arg -> stored auth base -> configured pb_base_url
    base = (base_url or _base_url_from_auth() or "").rstrip("/")
    if not base:
        try:
            from .__init__ import get_config
            cfg = get_config() or {}
            base = (cfg.get("pb_base_url") or "").strip().rstrip("/")
        except Exception:
            base = ""
    if not base:
        return False
    url = f"{base}/api/health"
    try:
        # Always bypass offline short-circuit for ping
        code, _ = _req(url, timeout=timeout, ignore_offline=True)
        return int(code) == 200
    except Exception:
        return False

def try_reconnect(background: bool = True) -> None:
    """Attempt to go back online by pinging the server. No-op if already online."""
    def _run():
        try:
            if ping():
                set_offline(False)
                try:
                    from . import ems_logging as LOG
                    LOG.log("pb.reconnect.ok")
                except Exception:
                    pass
        except Exception:
            pass
    if background:
        threading.Thread(target=_run, daemon=True).start()
    else:
        _run()

def _req(url: str, method: str = "GET", body: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None, timeout: int = 12, ignore_offline: bool = False) -> Tuple[int, str]:
    t0 = time.time()
    safe_url = url
    try:
        # Redact tokens if present in query
        if "token=" in safe_url:
            safe_url = safe_url.split("token=")[0] + "token=REDACTED"
    except Exception:
        pass
    data = None
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        data = raw
        hdrs = {"Content-Type": "application/json"}
    else:
        hdrs = {}
    # Add browser-like defaults to play nice with Cloudflare/CDN
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
    except Exception:
        origin = None
    default_headers = {
        # Pretend to be a regular browser (avoid Python-urllib UA blocks)
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 EMSAnki/1.0",
        # Expect JSON responses from the PB API
        "Accept": "application/json, text/plain, */*",
        # Avoid compressed encodings we may not transparently decode
        # (urllib handles gzip but not brotli in some builds). Let server choose.
        # Intentionally omit Accept-Encoding.
        "Accept-Language": "en-US,en;q=0.9",
    }
    if origin:
        # Some CDNs apply stricter checks when Origin/Referer are missing.
        default_headers.setdefault("Origin", origin)
        default_headers.setdefault("Referer", origin + "/")
    for k, v in default_headers.items():
        hdrs.setdefault(k, v)
    if headers:
        hdrs.update(headers)
    # Short-circuit when offline unless caller wants to bypass (ping/login)
    try:
        if (not ignore_offline) and is_offline():
            return 0, "offline"
    except Exception:
        pass
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            # Successful response implies connectivity; clear offline if previously set
            try:
                if is_offline():
                    set_offline(False)
            except Exception:
                pass
            _reset_connect_fail()
            return resp.getcode() or 200, txt
    except urllib.error.HTTPError as e:
        try:
            txt = e.read().decode("utf-8", errors="replace")
        except Exception:
            txt = str(e)
        return e.code, txt
    except Exception as e:
        # Only flip to offline on connectivity-type errors. Other exceptions
        # (e.g., JSON/ValueError) should not drop the user offline.
        if _is_connectivity_error(e):
            # Flip to offline only after >=3 consecutive connectivity errors
            st = _read_offline_state() or {}
            fails_before = int(st.get("fails", 0) or 0)
            _mark_connect_fail(f"{type(e).__name__}: {e} @ {url}")
            st2 = _read_offline_state() or {}
            fails_now = int(st2.get("fails", 0) or 0)
            last_ok = int(st2.get("last_ok_ts", 0) or 0)
            # Add a small protection window: don't flip within 5s of a successful call
            if (fails_now >= 3) and (int(time.time()) - last_ok > 5):
                try:
                    set_offline(True, reason=st2.get("last_err") or f"Net error @ {url}")
                except Exception:
                    pass
        dt = round((time.time() - t0) * 1000, 1)
        LOG.log("http.error", url=safe_url, method=method, code=0, ms=dt, error=str(e))
        return 0, str(e)
    finally:
        try:
            dt = round((time.time() - t0) * 1000, 1)
            # only log small bodies for debug
            LOG.log("http.req", url=safe_url, method=method, ms=dt)
        except Exception:
            pass

def login(base_url: str, email: str, password: str) -> Tuple[bool, str]:
    try:
        from . import ems_logging as LOG
        LOG.log("pb.login", base=base_url, email=email)
    except Exception:
        pass
    # PocketBase password auth endpoint
    url = base_url.rstrip("/") + "/api/collections/users/auth-with-password"
    code, txt = _req(url, method="POST", body={"identity": email, "password": password}, ignore_offline=True)
    if code == 200:
        try:
            obj = json.loads(txt)
            token = obj.get("token")
            record = obj.get("record") or {}
            if token and record:
                save_auth({"token": token, "record": record, "base_url": base_url, "ts": int(time.time())})
                try:
                    # Clear offline explicitly after successful login
                    set_offline(False)
                except Exception:
                    pass
                try:
                    LOG.log("pb.login.ok", email=record.get('email') or email)
                except Exception:
                    pass
                return True, f"Logged in as {record.get('email','user')}"
        except Exception as e:
            try:
                LOG.log("pb.login.error", error=str(e))
            except Exception:
                pass
            return False, f"Bad response: {e}"
    try:
        LOG.log("pb.login.fail", code=code)
    except Exception:
        pass
    return False, f"HTTP {code}: {txt[:200]}"

def logout() -> None:
    clear_auth()
    # Logging out should also mark as online (we just stop using PB). Keep offline flag as-is.
    try:
        LOG.log("pb.logout")
    except Exception:
        pass

def whoami() -> Tuple[bool, str]:
    try:
        LOG.log("pb.whoami")
    except Exception:
        pass
    a = load_auth()
    if not a.get("token"):
        return False, "Not logged in"
    base = (a.get("base_url") or "").rstrip("/")
    rid = (a.get("record") or {}).get("id")
    if not (base and rid):
        return False, "No user record"
    url = f"{base}/api/collections/users/records/{rid}"
    code, txt = _req(url, headers={"Authorization": f"Bearer {a['token']}"})
    if code == 200:
        try:
            obj = json.loads(txt)
            email = obj.get("email") or obj.get("id") or "OK"
            try:
                LOG.log("pb.whoami.ok", email=email)
            except Exception:
                pass
            return True, email
        except Exception:
            return True, "OK"
    try:
        LOG.log("pb.whoami.fail", code=code)
    except Exception:
        pass
    return False, f"HTTP {code}: {txt[:200]}"

def register(base_url: str, email: str, password: str, username: Optional[str] = None) -> Tuple[bool, str]:
    """Create a new PocketBase user.

    Attempts to create a user record in the default `users` collection.
    Returns (ok, message). On some servers, email verification may be required
    before login is allowed.
    """
    try:
        from . import ems_logging as LOG
        LOG.log("pb.register", base=base_url, email=email)
    except Exception:
        pass
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return False, "Missing base URL"
    # Generate a username if not provided (many PB setups require one)
    try:
        if not username:
            local = (email or "").split("@")[0]
            suf = str(int(time.time()))[-5:]
            username = (local or "user") + suf
    except Exception:
        username = None
    body: Dict[str, Any] = {"email": email, "password": password, "passwordConfirm": password}
    if username:
        body["username"] = username
    url = f"{base}/api/collections/users/records"
    code, txt = _req(url, method="POST", body=body, ignore_offline=True)
    if code in (200, 201):
        # success – record created (may require verification)
        try:
            obj = json.loads(txt) or {}
            msg = "Account created"
            if not obj.get("verified"):
                msg += "; check your email to verify"
            return True, msg
        except Exception:
            return True, "Account created"
    # Try to extract error
    try:
        obj = json.loads(txt)
        # PocketBase error shape: {code, message, data:{field:{code,message}}}
        data = (obj or {}).get("data") or {}
        if isinstance(data, dict) and data:
            # surface first field error
            for k, v in data.items():
                m = (v or {}).get("message") or ""
                if m:
                    return False, f"{k}: {m}"
        m = (obj or {}).get("message") or ""
        if m:
            return False, m
    except Exception:
        pass
    return False, f"HTTP {code}: {txt[:200]}"

def seed_terms_all() -> Tuple[bool, str]:
    """Trigger server hook to upsert all glossary terms from JSON.

    Requires a logged-in user that is permitted by the server route.
    Returns (ok, message).
    """
    base, headers = _auth_headers()
    if not base:
        return False, "Not logged in"
    url = f"{base.rstrip('/')}/ems/sync-terms"
    code, txt = _req(url, method="POST", headers=headers)
    if code == 200:
        return True, "Seeding started"
    if code == 403:
        return False, "Forbidden (not an allowed seeder)"
    return False, f"HTTP {code}: {txt[:200]}"

# ---------------- Tamagotchi cloud sync (PocketBase) ----------------

def _cfg() -> Dict[str, Any]:
    """Read add-on config and provide defaults for tamagotchi-related keys."""
    try:
        from .__init__ import get_config
        cfg = get_config() or {}
    except Exception:
        cfg = {}
    # Soft defaults if missing in config
    if "pb_tamagotchi_collection" not in cfg:
        cfg["pb_tamagotchi_collection"] = "tamagotchi"
    if "pb_tamagotchi_user_field" not in cfg:
        cfg["pb_tamagotchi_user_field"] = "user"
    if "pb_tamagotchi_data_field" not in cfg:
        cfg["pb_tamagotchi_data_field"] = "data"
    return cfg

def _auth_headers() -> Tuple[Optional[str], Dict[str, str]]:
    a = load_auth()
    token = a.get("token")
    if not token:
        return None, {}
    return a.get("base_url"), {"Authorization": f"Bearer {token}"}

def _parse_pb_time(s: str) -> float:
    """Parse PocketBase ISO time (e.g., '2025-01-01 12:30:00.000Z') to epoch seconds."""
    try:
        # Normalize to ISO 8601 with 'T' and offset for fromisoformat
        iso = s.replace(" ", "T").replace("Z", "+00:00")
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return 0.0

def tamagotchi_fetch() -> Tuple[bool, Optional[Dict[str, Any]], float, Optional[str], str]:
    """Fetch the current user's Tamagotchi record.

    Returns (ok, state_dict_or_None, server_updated_epoch, record_id_or_None, message)
    """
    base_token = _auth_headers()
    if not base_token[0]:
        return False, None, 0.0, None, "Not logged in"
    base, headers = base_token
    cfg = _cfg()
    collection = cfg.get("pb_tamagotchi_collection", "tamagotchi")
    user_field = cfg.get("pb_tamagotchi_user_field", "user")
    a = load_auth()
    user_id = (a.get("record") or {}).get("id")
    if not user_id:
        return False, None, 0.0, None, "No user id"
    # Try known record id first
    rid = (_load_tama_meta() or {}).get("record_id")
    if rid:
        url = f"{base.rstrip('/')}/api/collections/{collection}/records/{rid}"
        code, txt = _req(url, headers=headers)
        if code == 200:
            try:
                obj = json.loads(txt) or {}
                data_field = cfg.get("pb_tamagotchi_data_field", "data")
                updated = obj.get("updated") or obj.get("updatedAt") or ""
                state = obj.get(data_field) or {}
                try:
                    LOG.log("tama.fetch.ok", via="id", updated=updated)
                except Exception:
                    pass
                return True, state, _parse_pb_time(updated), obj.get("id"), "OK"
            except Exception as e:
                return False, None, 0.0, None, f"Bad record: {e}"
        # else fall through to list query

    # Query by user relation
    from urllib.parse import quote
    filt = quote(f"{user_field}='{user_id}'")
    url = f"{base.rstrip('/')}/api/collections/{collection}/records?perPage=1&filter={filt}"
    code, txt = _req(url, headers=headers)
    if code != 200:
        return False, None, 0.0, None, f"HTTP {code}: {txt[:200]}"
    try:
        obj = json.loads(txt) or {}
        items = obj.get("items") or []
        if not items:
            return True, None, 0.0, None, "No record"
        rec = items[0]
        data_field = cfg.get("pb_tamagotchi_data_field", "data")
        updated = rec.get("updated") or rec.get("updatedAt") or ""
        rid = rec.get("id")
        if rid:
            _save_tama_meta({"record_id": rid})
        state = rec.get(data_field) or {}
        try:
            LOG.log("tama.fetch.ok", via="query", updated=updated)
        except Exception:
            pass
        return True, state, _parse_pb_time(updated), rid, "OK"
    except Exception as e:
        return False, None, 0.0, None, f"Bad response: {e}"

def tamagotchi_upsert(state: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Create or update the user's Tamagotchi record with the given state dict.

    Returns (ok, message, record_id)
    """
    base_token = _auth_headers()
    if not base_token[0]:
        return False, "Not logged in", None
    base, headers = base_token
    cfg = _cfg()
    collection = cfg.get("pb_tamagotchi_collection", "tamagotchi")
    user_field = cfg.get("pb_tamagotchi_user_field", "user")
    data_field = cfg.get("pb_tamagotchi_data_field", "data")
    a = load_auth()
    user_id = (a.get("record") or {}).get("id")
    if not user_id:
        return False, "No user id", None

    meta = _load_tama_meta() or {}
    rid = meta.get("record_id")

    # PATCH existing record if we have an id
    body = {data_field: state}
    if rid:
        url = f"{base.rstrip('/')}/api/collections/{collection}/records/{rid}"
        code, txt = _req(url, method="PATCH", body=body, headers=headers)
        if code == 200:
            return True, "Updated", rid
        # Fall back to create if missing

    # Try to find an existing record by user relation first (to avoid duplicates)
    ok, _state, _ts, found_id, _msg = tamagotchi_fetch()
    if ok and found_id:
        url = f"{base.rstrip('/')}/api/collections/{collection}/records/{found_id}"
        code, txt = _req(url, method="PATCH", body=body, headers=headers)
        if code == 200:
            _save_tama_meta({"record_id": found_id})
            return True, "Updated", found_id

    # Create new record
    body_create = {user_field: user_id, data_field: state}
    url = f"{base.rstrip('/')}/api/collections/{collection}/records"
    code, txt = _req(url, method="POST", body=body_create, headers=headers)
    if code == 200 or code == 201:
        try:
            obj = json.loads(txt) or {}
            new_id = obj.get("id")
            if new_id:
                _save_tama_meta({"record_id": new_id})
            return True, "Created", new_id
        except Exception:
            return True, "Created", None
    return False, f"HTTP {code}: {txt[:200]}", None

def tamagotchi_push_async(state: Dict[str, Any]) -> None:
    """Push state in a background thread; no UI feedback, best-effort."""
    def _run():
        try:
            tamagotchi_upsert(state)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

# ---------------- Glossary (ratings, credits, profiles) ----------------

def _base_headers() -> Tuple[Optional[str], Dict[str, str]]:
    return _auth_headers()

def _ensure_term_record(slug: str, title: str | None = None) -> Optional[str]:
    # Fast-path: local cache
    try:
        if slug in _TERM_ID_CACHE:
            return _TERM_ID_CACHE.get(slug)
    except Exception:
        pass
    base, headers = _base_headers()
    if not base: return None
    # Lookup existing by slug
    from urllib.parse import quote
    url = f"{base.rstrip('/')}/api/collections/terms/records?perPage=1&filter=" + quote(f"slug='{slug}'")
    code, txt = _req(url, headers=headers)
    if code == 200:
        try:
            obj = json.loads(txt) or {}
            items = obj.get("items") or []
            if items:
                rid = (items[0] or {}).get("id")
                if rid:
                    try:
                        _TERM_ID_CACHE[slug] = rid
                    except Exception:
                        pass
                return rid
        except Exception:
            pass
    # Create new (user create)
    body = {"slug": slug}
    if title:
        body["title"] = title
    url = f"{base.rstrip('/')}/api/collections/terms/records"
    code, txt = _req(url, method="POST", body=body, headers=headers)
    if code in (200, 201):
        try:
            rid = (json.loads(txt) or {}).get("id")
            if rid:
                try:
                    _TERM_ID_CACHE[slug] = rid
                except Exception:
                    pass
            return rid
        except Exception:
            return None
    # Fallback: call server ensure-term route (superuser upsert) if hook present
    try:
        # try to enrich title from local glossary
        if not title:
            try:
                from .__init__ import GLOSSARY  # type: ignore
                t = (getattr(GLOSSARY, 'terms_by_id', {}) or {}).get(slug) or {}
                names = t.get('names') or []
                if names:
                    title = names[0]
            except Exception:
                pass
        hooks = _load_hooks_state()
        if hooks.get("ensure_term", True):
            ensure_url = f"{base.rstrip('/')}/ems/ensure-term"
            code_e, _ = _req(ensure_url, method="POST", body={"slug": slug, "title": title or slug}, headers=None)
            if code_e == 404:
                _save_hooks_state({"ensure_term": False})
        # Re-query
        url = f"{base.rstrip('/')}/api/collections/terms/records?perPage=1&filter=" + quote(f"slug='{slug}'")
        code2, txt2 = _req(url, headers=headers)
        if code2 == 200:
            try:
                items = (json.loads(txt2) or {}).get("items") or []
                if items:
                    rid = (items[0] or {}).get("id")
                    if rid:
                        try:
                            _TERM_ID_CACHE[slug] = rid
                        except Exception:
                            pass
                    return rid
            except Exception:
                pass
    except Exception:
        pass
    return None

def rating_get(slug: str) -> Tuple[bool, Dict[str, Any]]:
    # Short TTL cache to avoid repeated network calls on frequent opens
    try:
        ent = _RATING_CACHE.get(slug)
        if ent:
            ts = float(ent.get("ts") or 0)
            if (time.time() - ts) < 180:  # 3 minutes
                data = ent.get("data") or {}
                return True, dict(data)
    except Exception:
        pass
    base, headers = _base_headers()
    if not base: return False, {"error": "Not logged in"}
    a = load_auth() or {}
    uid = (a.get("record") or {}).get("id")
    tid = _ensure_term_record(slug, None)
    if not tid: return False, {"error": "Term missing"}
    from urllib.parse import quote
    # Fetch all ratings for term (first 200 is fine for now)
    url = f"{base.rstrip('/')}/api/collections/term_ratings/records?perPage=200&filter=" + quote(f"term='{tid}'")
    code, txt = _req(url, headers=headers)
    stars = []
    if code == 200:
        try:
            items = (json.loads(txt) or {}).get("items") or []
            for it in items:
                try:
                    stars.append(int((it.get("stars") or "0").strip()))
                except Exception:
                    pass
        except Exception:
            pass
    avg = (sum(stars) / len(stars)) if stars else 0.0
    # Fetch my rating
    url = f"{base.rstrip('/')}/api/collections/term_ratings/records?perPage=1&filter=" + quote(f"term='{tid}' && user='{uid}'")
    code2, txt2 = _req(url, headers=headers)
    mine = None; rid = None
    if code2 == 200:
        try:
            items = (json.loads(txt2) or {}).get("items") or []
            if items:
                rid = (items[0] or {}).get("id")
                try:
                    mine = int((items[0] or {}).get("stars") or "0")
                except Exception:
                    mine = None
        except Exception:
            pass
    res = {"avg": avg, "count": len(stars), "mine": mine, "termId": tid, "ratingId": rid}
    try:
        LOG.log("rating.get", id=slug, avg=avg, count=len(stars), mine=mine)
    except Exception:
        pass
    try:
        _RATING_CACHE[slug] = {"ts": time.time(), "data": res}
    except Exception:
        pass
    return True, res

def rating_set(slug: str, stars: int) -> Tuple[bool, Dict[str, Any]]:
    base, headers = _base_headers()
    if not base: return False, {"error": "Not logged in"}
    a = load_auth() or {}
    uid = (a.get("record") or {}).get("id")
    if not uid: return False, {"error": "No user id"}
    # Try to derive a friendly title from the local store
    title = None
    try:
        from .__init__ import GLOSSARY  # type: ignore
        t = (getattr(GLOSSARY, 'terms_by_id', {}) or {}).get(slug) or {}
        names = t.get('names') or []
        if names:
            title = names[0]
    except Exception:
        pass
    tid = _ensure_term_record(slug, title)
    if not tid: return False, {"error": "Term missing"}
    stars = max(1, min(5, int(stars)))
    from urllib.parse import quote
    # Find existing
    url = f"{base.rstrip('/')}/api/collections/term_ratings/records?perPage=1&filter=" + quote(f"term='{tid}' && user='{uid}'")
    code, txt = _req(url, headers=headers)
    rid = None
    if code == 200:
        try:
            items = (json.loads(txt) or {}).get("items") or []
            if items:
                rid = (items[0] or {}).get("id")
        except Exception:
            pass
    body = {"term": tid, "user": uid, "stars": str(stars)}
    if rid:
        url = f"{base.rstrip('/')}/api/collections/term_ratings/records/{rid}"
        _req(url, method="PATCH", body={"stars": str(stars)}, headers=headers)
    else:
        url = f"{base.rstrip('/')}/api/collections/term_ratings/records"
        _req(url, method="POST", body=body, headers=headers)
    # Return updated snapshot
    # Invalidate cached snapshot first
    try:
        if slug in _RATING_CACHE:
            _RATING_CACHE.pop(slug, None)
    except Exception:
        pass
    ok, data = rating_get(slug)
    try:
        LOG.log("rating.set", id=slug, stars=stars, ok=ok)
    except Exception:
        pass
    return ok, data

def credits_get(slug: str) -> Tuple[bool, Dict[str, Any]]:
    """Return credits from local term JSON only (no PB collections).

    This avoids legacy term_credits/user_profiles calls and reflects the
    current design where credits live inside the term JSON itself.
    """
    try:
        from .__init__ import GLOSSARY  # type: ignore
        t = (getattr(GLOSSARY, 'terms_by_id', {}) or {}).get(slug) or {}
        creds = t.get('credits') or []
        out = []
        for c in creds:
            if isinstance(c, dict):
                out.append({
                    'display': c.get('name') or c.get('email') or 'Contributor',
                    'avatar': c.get('avatar') or None,
                    'role': c.get('role') or '',
                })
            elif isinstance(c, str):
                out.append({'display': c, 'avatar': None, 'role': ''})
        return True, {'credits': out}
    except Exception:
        return True, {'credits': []}

def credits_ensure(slug: str, credits_list) -> None:
    """No-op: credits live in the term JSON; we no longer mirror them to PB."""
    return None

def profile_get() -> Tuple[bool, Dict[str, Any]]:
    base, headers = _base_headers()
    if not base: return False, {"error": "Not logged in"}
    a = load_auth() or {}; uid = (a.get("record") or {}).get("id")
    if not uid: return False, {"error": "No user id"}
    from urllib.parse import quote
    url = f"{base.rstrip('/')}/api/collections/user_profiles/records?perPage=1&filter=" + quote(f"user='{uid}'")
    code, txt = _req(url, headers=headers)
    if code == 200:
        try:
            items = (json.loads(txt) or {}).get("items") or []
            if items:
                return True, items[0]
        except Exception:
            pass
    return True, {}

def profile_upsert(display_name: str, avatar_url: str, about: str) -> Tuple[bool, str]:
    base, headers = _base_headers()
    if not base: return False, "Not logged in"
    a = load_auth() or {}; uid = (a.get("record") or {}).get("id")
    if not uid: return False, "No user id"
    ok, cur = profile_get()
    body = {"user": uid, "display_name": display_name or "", "avatar_url": avatar_url or "", "about": about or ""}
    if ok and cur and cur.get("id"):
        url = f"{base.rstrip('/')}/api/collections/user_profiles/records/{cur.get('id')}"
        c, _ = _req(url, method="PATCH", body=body, headers=headers)
        return (c == 200), ("Updated" if c == 200 else f"HTTP {c}")
    else:
        url = f"{base.rstrip('/')}/api/collections/user_profiles/records"
        c, _ = _req(url, method="POST", body=body, headers=headers)
        return (c in (200,201)), ("Created" if c in (200,201) else f"HTTP {c}")

# ---------------- Comments (PocketBase) ----------------

def comments_get(slug: str) -> Tuple[bool, Dict[str, Any]]:
    """Fetch comments for a term. Returns a payload suitable for UI rendering.

    Structure: { items: [{id, body, parentId, created, user:{id,display}}], canPost: bool }
    """
    # Determine posting capability from auth and offline state
    can_post = False
    try:
        a = load_auth() or {}
        can_post = bool(a.get("token")) and (not is_offline())
    except Exception:
        can_post = False

    # Resolve base URL (works without login for public reads)
    base, headers = _base_headers()
    if not base:
        try:
            from .__init__ import get_config
            base = (get_config() or {}).get("pb_base_url")
        except Exception:
            base = None
        headers = None
    if not base:
        return True, {"items": [], "canPost": False}

    # Resolve the term record id without requiring auth (public list on terms)
    from urllib.parse import quote
    tid: Optional[str] = None
    try:
        url = f"{base.rstrip('/')}/api/collections/terms/records?perPage=1&filter=" + quote(f"slug='{slug}'")
        code0, txt0 = _req(url, headers=headers)
        if code0 == 200:
            try:
                items0 = (json.loads(txt0) or {}).get("items") or []
                if items0:
                    tid = (items0[0] or {}).get("id")
            except Exception:
                tid = None
    except Exception:
        tid = None
    if not tid:
        return True, {"items": [], "canPost": can_post}

    # Avoid sorting on 'created' to prevent PB servers without the field in schema from rejecting the query
    url = f"{base.rstrip('/')}/api/collections/term_comments/records?perPage=200&expand=user&filter=" + quote(f"term='{tid}'")
    code, txt = _req(url, headers=headers)
    items: list[dict[str, Any]] = []
    if code == 200:
        try:
            obj = json.loads(txt) or {}
            for it in (obj.get("items") or []):
                try:
                    raw_user = it.get("user")
                    uid = raw_user if isinstance(raw_user, str) else ((raw_user or {}).get("id") or "")
                    disp = None
                    try:
                        exp = (it.get("expand") or {}).get("user")
                        if isinstance(exp, dict):
                            disp = (exp.get("name") or exp.get("email") or "").split("@")[0]
                    except Exception:
                        disp = None
                    items.append({
                        "id": it.get("id"),
                        "body": it.get("body") or "",
                        "parentId": (it.get("parent") if isinstance(it.get("parent"), str) else (it.get("parent") or {}).get("id")) or None,
                        "created": it.get("created") or it.get("createdAt") or "",
                        "user": {"id": uid, "display": disp or "User"},
                    })
                except Exception:
                    pass
        except Exception:
            pass
    return True, {"items": items, "canPost": can_post}

_COMMENT_POST_GUARD: Dict[str, Any] = {}

def comment_add(slug: str, body: str, parent_id: Optional[str] = None) -> Tuple[bool, str]:
    """Create a new comment or reply for a term."""
    body = (body or "").strip()
    if not body:
        return False, "Empty"
    base, headers = _base_headers()
    if not base:
        return False, "Not logged in"
    a = load_auth() or {}
    uid = (a.get("record") or {}).get("id")
    if not uid:
        return False, "No user id"
    # In-process guard against accidental double clicks
    try:
        key = f"{uid}:{slug}:{hash(body)}"
        now = time.time()
        last = _COMMENT_POST_GUARD.get(key)
        if last and (now - float(last)) < 1.0:
            return True, "OK"
        _COMMENT_POST_GUARD[key] = now
    except Exception:
        pass
    # Derive human title for term creation if needed
    title = None
    try:
        from .__init__ import GLOSSARY  # type: ignore
        t = (getattr(GLOSSARY, 'terms_by_id', {}) or {}).get(slug) or {}
        names = t.get('names') or []
        if names:
            title = names[0]
    except Exception:
        pass
    tid = _ensure_term_record(slug, title)
    if not tid:
        return False, "Term missing"
    payload: Dict[str, Any] = {"term": tid, "user": uid, "body": body}
    if parent_id:
        payload["parent"] = parent_id
    url = f"{base.rstrip('/')}/api/collections/term_comments/records"
    c, txt = _req(url, method="POST", body=payload, headers=headers)
    if c in (200, 201):
        try:
            LOG.log("comments.add", id=slug)
        except Exception:
            pass
        return True, "OK"
    return False, f"HTTP {c}: {txt[:200]}"
