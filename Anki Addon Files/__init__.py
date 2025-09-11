
from __future__ import annotations
import json, os, re, time, urllib.request, urllib.error, threading, shutil, html, uuid, hashlib
import urllib.parse
from typing import Any, Dict, List, Tuple
from aqt import mw, gui_hooks
from aqt.qt import QAction, qconnect, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox, QLineEdit, QIcon, QPlainTextEdit, QScrollArea, QWidget, QTabWidget, QFileDialog, QMessageBox, QFrame, QColorDialog, QPixmap, Qt
from aqt.webview import AnkiWebView
from . import ems_logging as LOG
from aqt.utils import openFolder, showInfo, showText, tooltip, openLink
from anki.notes import Note

MODULE = __name__
ADDON_DIR = os.path.dirname(__file__)
WEB_DIR = os.path.join(ADDON_DIR, "web")
USER_FILES_DIR = os.path.join(ADDON_DIR, "user_files")
TERMS_DIR = os.path.join(USER_FILES_DIR, "terms")
MY_TERMS_DIR = os.path.join(USER_FILES_DIR, "my terms")
STATE_DIR = os.path.join(USER_FILES_DIR, "_state")
LOG_PATH = os.path.join(USER_FILES_DIR, "log.txt")
LAST_INDEX_SNAPSHOT = os.path.join(STATE_DIR, "last_index.json")
LAST_DIFF = os.path.join(STATE_DIR, "last_diff.json")
LAST_VERSION = os.path.join(STATE_DIR, "version.txt")
SEEN_VERSION = os.path.join(STATE_DIR, "seen_version.txt")
TAGS_JSON_PATH = os.path.join(STATE_DIR, "tags.json")
FETCHED_INDEX_RAW = os.path.join(STATE_DIR, "fetched_index_raw.json")
FETCHED_INDEX_PARSED = os.path.join(STATE_DIR, "fetched_index_parsed.json")
SUGGEST_DRAFT_PATH = os.path.join(STATE_DIR, "suggest_draft.json")
LOGO_PATH = os.path.join(WEB_DIR, "ems_logo.png")
THEME_JSON_PATH = os.path.join(STATE_DIR, "theme.json")

RAW_INDEX = "https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary/index.json"
RAW_TERMS_BASE = "https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary/terms"

AUTO_UPDATE_DAYS = 1

DEFAULT_CONFIG = {
    "tooltip_width_px": 640,
    "popup_font_px": 16,
    "hover_mode": "click",
    "hover_delay_ms": 120,
    "open_with_click_anywhere": True,
    "max_highlights": 100,
    "mute_tags": "",
    "scan_fields": "Front,Back,Extra",
    "last_update_check": 0,
    "fuzzy_enabled": True,
    "fuzzy_min_len": 5,
    "fuzzy_max_add": 6,
    "ship_index_if_no_matches": True,
    "ship_index_limit": 3000,

    # Learn cards
    "learn_target": "dedicated",           # "dedicated" or "current"
    "learn_deck_name": "EnterMedSchool - Terms",

    # Appearance: popup (overrides CSS variables in web/popup.css)
    "popup_bg": "rgba(15,18,26,.96)",      # --ems-bg
    "popup_fg": "#edf1f7",                 # --ems-fg
    "popup_muted": "#a4afbf",              # --ems-muted
    "popup_border": "rgba(255,255,255,.10)", # --ems-border
    "popup_accent": "#8b5cf6",             # --ems-accent
    "popup_accent2": "#06b6d4",            # --ems-accent-2
    "popup_radius_px": 14,                  # --ems-radius
    "popup_custom_css": "",                 # extra CSS appended in head

    # Appearance: fonts (overrides popup.css variables if provided)
    "font_title": "'Baloo 2'",
    "font_body": "'Montserrat'",
    "font_url": "https://fonts.googleapis.com/css2?family=Baloo+2:wght@400;600;700&family=Montserrat:wght@400;500;600;700&display=swap",

    # Appearance: dialogs/editors (Suggest Term, etc.)
    "ui_bg": "#0f121a",
    "ui_fg": "#edf1f7",
    "ui_accent": "#8b5cf6",
    "ui_control_bg": "rgba(255,255,255,.04)",
    "ui_control_border": "rgba(255,255,255,.12)",
    "ui_button_bg": "#7c3aed",
    "ui_button_border": "#a78bfa",
    "ui_custom_css": ""
    ,
    # Logging
    "log_level": "INFO",  # INFO or DEBUG
    # Live services (PocketBase)
    "live_enabled": False,
    # Hosted PocketBase (reverse-proxied behind Cloudflare)
    "pb_base_url": "https://anki.entermedschool.com",
    # Prompt login once on startup when not logged-in
    "pb_login_prompt_never": False,
    # Tamagotchi cloud schema (PocketBase collection + fields)
    "pb_tamagotchi_collection": "tamagotchi",
    "pb_tamagotchi_user_field": "user",
    "pb_tamagotchi_data_field": "data",
}

# Safely eval JS on a given Anki webview context (Reviewer web or pyqt eval)
def _safe_eval_js_on_context(ctx, script: str) -> bool:
    try:
        fn = getattr(ctx, 'eval', None)
        if callable(fn):
            fn(script)
            return True
    except Exception:
        pass
    try:
        web = getattr(ctx, 'web', None)
        if web is not None:
            ev = getattr(web, 'eval', None)
            if callable(ev):
                ev(script)
                return True
    except Exception:
        pass
    # Fallback to current reviewer web if available
    try:
        from aqt import mw as _mw
        rev = getattr(_mw, 'reviewer', None)
        if rev is not None:
            web = getattr(rev, 'web', None)
            ev = getattr(web, 'eval', None)
            if callable(ev):
                ev(script)
                return True
    except Exception:
        pass
    return False

def _log(msg: str):
    try:
        os.makedirs(USER_FILES_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")
    except Exception:
        pass

# ------------------------------ Leo Tamagotchi ------------------------------
# Initialize lightweight hooks (XP awards on correct answers). If anything
# fails here, we just log and continue; the rest of the add-on must not be
# impacted.
try:
    from .LeoTamagotchi import gui as _leo_tamagotchi
    try:
        _leo_tamagotchi.setup_hooks()
    except Exception as e:
        _log(f"Tamagotchi setup_hooks failed: {e}")
except Exception as e:
    _log(f"Tamagotchi import failed: {e}")

# Add a Tools menu entry to open the Tamagotchi window
_tama_menu_guard = False
_login_prompt_shown = False

def _add_tamagotchi_menu_entry():
    """Idempotently add Tamagotchi actions to the Tools menu.

    Guards against duplicate actions if the hook fires multiple times
    (e.g. profile reopen, add-on reload)."""
    global _tama_menu_guard
    try:
        from aqt.qt import QAction, qconnect

        # Prefer Tools menu if available, otherwise create a dedicated menu
        try:
            menu = mw.form.menuTools
        except Exception:
            menu = None

        if menu is None:
            try:
                menu = mw.menuBar().addMenu("Leo Tamagotchi")
            except Exception:
                menu = None

        if menu is None:
            return

        # Proactively remove duplicate actions by text (from previous runs)
        try:
            wanted = {
                "Open Leo Tamagotchi",
                "Reset Leo Tamagotchi Progress",
                "Sync Leo Tamagotchi Now",
            }
            seen = set()
            for a in list(menu.actions()):
                try:
                    t = a.text()
                except Exception:
                    t = None
                if t in wanted:
                    if t in seen:
                        try:
                            menu.removeAction(a)
                        except Exception:
                            pass
                    else:
                        seen.add(t)
        except Exception:
            pass

        # Helper to ensure a single action with a fixed objectName
        def ensure_action(obj_name: str, text: str, handler):
            # Check by objectName first, then by text as a fallback
            for a in menu.actions():
                try:
                    if a.objectName() == obj_name or a.text() == text:
                        return a  # already present
                except Exception:
                    pass
            act = QAction(text, mw)
            try:
                act.setObjectName(obj_name)
            except Exception:
                pass
            qconnect(act.triggered, handler)
            menu.addAction(act)
            return act

        # Actions
        def _open():
            try:
                from .LeoTamagotchi import gui as _leo_tamagotchi
                _leo_tamagotchi.show_tamagotchi()
            except Exception as e:
                _log(f"Open Leo Tamagotchi failed: {e}")
        def _reset():
            try:
                from .LeoTamagotchi import gui as _leo_tamagotchi
                _leo_tamagotchi.reset_progress()
                try:
                    tooltip("Leo Tamagotchi progress reset.")
                except Exception:
                    pass
            except Exception as e:
                _log(f"Reset Tamagotchi failed: {e}")
        def _sync():
            try:
                from .LeoTamagotchi import gui as _leo_tamagotchi
                _leo_tamagotchi.sync_now()
            except Exception as e:
                _log(f"Sync Tamagotchi failed: {e}")

        ensure_action("ems_tama_open", "Open Leo Tamagotchi", _open)
        ensure_action("ems_tama_reset", "Reset Leo Tamagotchi Progress", _reset)
        ensure_action("ems_tama_sync", "Sync Leo Tamagotchi Now", _sync)

        _tama_menu_guard = True
    except Exception as e:
        _log(f"Add Tamagotchi menu entry failed: {e}")

try:
    gui_hooks.profile_did_open.append(_add_tamagotchi_menu_entry)
except Exception as e:
    _log(f"Hook Tamagotchi menu failed: {e}")

# Auto-open the floating Tamagotchi window on profile load so it overlays
# all Anki pages (home + reviewer). Safe to call repeatedly.
def _open_tamagotchi_on_profile_open():
    try:
        from .LeoTamagotchi import gui as _leo_tamagotchi
        _leo_tamagotchi.show_tamagotchi()
    except Exception as e:
        _log(f"Auto-open Tamagotchi failed: {e}")

try:
    gui_hooks.profile_did_open.append(_open_tamagotchi_on_profile_open)
except Exception as e:
    _log(f"Hook Tamagotchi auto-open failed: {e}")

def get_config() -> Dict[str, Any]:
    try:
        cfg = mw.addonManager.getConfig(MODULE) or {}
    except Exception as e:
        _log(f"getConfig failed: {e}")
        cfg = {}
    changed = False
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    # Merge optional theme overrides persisted in STATE_DIR/theme.json
    try:
        if os.path.exists(THEME_JSON_PATH):
            t = json.load(open(THEME_JSON_PATH, 'r', encoding='utf-8')) or {}
            for k, v in (t or {}).items():
                cfg[k] = v
    except Exception as e:
        _log(f"read theme overrides failed: {e}")
    # Migrate legacy local PocketBase URLs to the hosted endpoint
    try:
        cur = str(cfg.get("pb_base_url") or "").strip()
        if (not cur) or cur.startswith("http://127.0.0.1") or ("localhost" in cur):
            cfg["pb_base_url"] = DEFAULT_CONFIG.get("pb_base_url", "https://anki.entermedschool.com")
            changed = True
    except Exception:
        pass
    if changed:
        try:
            mw.addonManager.writeConfig(MODULE, cfg)
        except Exception as e:
            _log(f"writeConfig failed: {e}")
    return cfg

def write_config(cfg: Dict[str, Any]) -> None:
    try:
        mw.addonManager.writeConfig(MODULE, cfg)
    except Exception as e:
        _log(f"writeConfig failed: {e}")
    # Also persist a copy of appearance keys for robustness
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        keys = [
            "tooltip_width_px","popup_font_px","popup_bg","popup_fg","popup_muted","popup_border","popup_accent","popup_accent2","popup_radius_px","popup_custom_css",
            "ui_bg","ui_fg","ui_accent","ui_control_bg","ui_control_border","ui_button_bg","ui_button_border","ui_custom_css",
            "hover_mode","hover_delay_ms","open_with_click_anywhere","max_highlights","scan_fields","mute_tags",
            "live_enabled","pb_base_url",
        ]
        out = {k: cfg.get(k) for k in keys if k in cfg}
        # include fonts
        out["font_title"] = cfg.get("font_title", DEFAULT_CONFIG.get("font_title"))
        out["font_body"] = cfg.get("font_body", DEFAULT_CONFIG.get("font_body"))
        out["font_url"] = cfg.get("font_url", DEFAULT_CONFIG.get("font_url"))
        with open(THEME_JSON_PATH, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        _log(f"write theme overrides failed: {e}")

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _cache_bust(url: str, token: str) -> str:
    return url + (("&" if "?" in url else "?") + "_ems=" + token)

def _http_text(url: str, timeout: int = 25, bust: bool = False, token: str = "") -> str:
    final = _cache_bust(url, token) if bust else url
    req = urllib.request.Request(final, headers={
        "User-Agent": "EMSGlossary/2.0 (+anki)",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def _json_relaxed(text: str) -> Dict[str, Any]:
    s = text.lstrip("\ufeff").strip()
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"(^|[^:])//.*?$", r"\1", s, flags=re.M)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return json.loads(s)

def _http_json(url: str, timeout: int = 25, bust: bool = False, token: str = "") -> Dict[str, Any]:
    raw = _http_text(url, timeout=timeout, bust=bust, token=token)
    try:
        data = json.loads(raw)
    except Exception:
        try:
            data = _json_relaxed(raw)
        except Exception as e2:
            preview = raw[:800]
            raise RuntimeError(f"Could not parse JSON from {url}.\n{str(e2)}\nPreview follows:\n\n{preview}")
    try:
        with open(FETCHED_INDEX_RAW, "w", encoding="utf-8") as fh: fh.write(raw)
        with open(FETCHED_INDEX_PARSED, "w", encoding="utf-8") as fh: json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return data

class GlossaryStore:
    def __init__(self, terms_dir: str):
        self.terms_dir = terms_dir
        self.terms_by_id: Dict[str, Dict[str, Any]] = {}
        self.patterns_by_id: Dict[str, List[str]] = {}
        self.tags_meta: Dict[str, Dict[str, str]] = {}
        self.surface_claims: Dict[str, List[str]] = {}
        self.single_word_surfaces: Dict[int, List[str]] = {}
        self.card_cache: Dict[int, Dict[str, Any]] = {}
        os.makedirs(self.terms_dir, exist_ok=True)
        os.makedirs(STATE_DIR, exist_ok=True)
        self._load_tags_palette()
        self.reload()

    def _load_tags_palette(self):
        self.tags_meta = {}
        try:
            if os.path.exists(TAGS_JSON_PATH):
                raw = open(TAGS_JSON_PATH, "r", encoding="utf-8").read()
                data = _json_relaxed(raw)
                for k, v in (data or {}).items():
                    if isinstance(v, str):
                        self.tags_meta[k] = {"accent": v, "icon": ""}
                    elif isinstance(v, dict):
                        self.tags_meta[k] = {"accent": v.get("accent", ""), "icon": v.get("icon", "")}
        except Exception as e:
            _log(f"load tags palette failed: {e}")

    _on_attr_rx  = re.compile(r'\son[a-zA-Z]+\s*=\s*"[^"]*"', re.IGNORECASE)
    _on_attr_rx2 = re.compile(r"\son[a-zA-Z]+\s*=\s*'[^']*'", re.IGNORECASE)
    _js_href_rx  = re.compile(r'href\s*=\s*"(?:\s*javascript:.*?)"', re.IGNORECASE)
    _js_href_rx2 = re.compile(r"href\s*=\s*'(?:\s*javascript:.*?)'", re.IGNORECASE)
    _script_block_rx = re.compile(r"(?is)<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.S)

    def _sanitize_html(self, value: str) -> str:
        s = value or ""
        s = self._script_block_rx.sub("", s)
        s = self._on_attr_rx.sub("", s)
        s = self._on_attr_rx2.sub("", s)
        s = self._js_href_rx.sub('href="#"', s)
        s = self._js_href_rx2.sub("href='#'", s)
        s = re.sub(r"\[\[([a-z0-9\-]+)\]\]", r"<a href='#' data-ems-link='\1'>\1</a>", s, flags=re.IGNORECASE)
        return s

    def _variants_for(self, surface: str) -> List[str]:
        out = set([surface]); s = surface
        out.add(s.replace("-", "–")); out.add(s.replace("–", "-"))
        out.add(s.replace("'", "’")); out.add(s.replace("’", "'"))
        if re.fullmatch(r"[A-Za-z]+", s):
            out.add(s + "s")
            if s.endswith("y") and len(s) > 1 and s[-2].lower() not in "aeiou":
                out.add(s[:-1] + "ies")
            elif s.endswith(("s", "x", "z", "ch", "sh")):
                out.add(s + "es")
        greek = {"alpha": "a", "beta": "ß", "gamma": "?", "delta": "d"}
        for name, sym in greek.items():
            if s.lower() == name: out.add(sym)
            if s == sym: out.add(name)
        return [x for x in out if x]

    def reload(self):
        try:
            self.terms_by_id.clear(); self.patterns_by_id.clear()
            self.surface_claims.clear(); self.single_word_surfaces.clear()
            mutes = set(x.strip().lower() for x in (get_config().get("mute_tags", "") or "").split(",") if x.strip())
            for name in sorted(os.listdir(self.terms_dir)):
                if not name.lower().endswith(".json"): continue
                p = os.path.join(self.terms_dir, name)
                try:
                    term = json.load(open(p, "r", encoding="utf-8"))
                except Exception as e:
                    _log(f"load term {name} failed: {e}"); continue
                tid = term.get("id") or os.path.splitext(name)[0]
                term["id"] = tid
                self.terms_by_id[tid] = term

                patterns = []
                def add_many(values):
                    nonlocal patterns
                    if not values: return
                    if isinstance(values, str): values = [values]
                    for v in values:
                        v = (v or "").strip()
                        if v: patterns.append(v)
                add_many(term.get("names"))
                add_many(term.get("aliases"))
                add_many(term.get("abbr"))
                add_many(term.get("patterns"))
                if not patterns and term.get("names"):
                    patterns = term["names"]

                expanded = []
                for ptn in patterns:
                    expanded.append(ptn)
                    if " " not in ptn:
                        expanded.extend(self._variants_for(ptn))

                uniq, seen = [], set()
                for ptn in expanded:
                    k = (ptn or "").lower()
                    if not k or k in seen: continue
                    seen.add(k); uniq.append(ptn)
                    if not any((t or "").lower() in mutes for t in (term.get("tags") or [])):
                        self.surface_claims.setdefault(k, []).append(tid)
                        if " " not in k and "-" not in k and "/" not in k:
                            self.single_word_surfaces.setdefault(len(k), []).append(k)
                self.patterns_by_id[tid] = uniq

            if self.surface_claims:
                alts = sorted(self.surface_claims.keys(), key=len, reverse=True)
                def esc(s: str):
                    import re as _re
                    return _re.escape(s).replace(r"\ ", " ").replace(r"\'", "'").replace(r"\-", "-").replace(r"\/", "/")
                joined = "|".join(esc(a) for a in alts)
                try:
                    self.big_regex = re.compile(r"(?<![A-Za-z0-9])(?:" + joined + r")(?![A-Za-z0-9])", re.IGNORECASE)
                except Exception as e:
                    _log(f"regex compile failed: {e}"); self.big_regex = None
            else:
                self.big_regex = None

            self.card_cache.clear()
        except Exception as e:
            _log(f"reload failed: {e}")

    def _note_text_for_fields(self, card) -> str:
        try:
            cfg = get_config()
            wanted = [x.strip() for x in cfg.get("scan_fields", "Front,Back,Extra").split(",") if x.strip()]
            n = card.note(); vals = []
            if wanted:
                for fname in wanted:
                    if fname in n: vals.append(str(n[fname]))
            else:
                vals = [str(v) for v in n.values()]
            return " \n ".join(vals)
        except Exception as e:
            _log(f"note text fields error: {e}")
            return ""

    def _edit_distance_limited(self, a: str, b: str, maxd: int) -> int:
        if abs(len(a)-len(b)) > maxd: return maxd+1
        if a == b: return 0
        if maxd == 0: return maxd+1
        if len(a) > len(b): a,b = b,a
        prev = list(range(len(a)+1))
        for i,cb in enumerate(b,1):
            cur=[i]
            start=max(1,i-maxd); end=min(len(a),i+maxd)
            if start>1: cur.extend([maxd+1]*(start-1))
            for j in range(start,end+1):
                cost = 0 if a[j-1]==cb else 1
                cur.append(min(prev[j]+1, cur[j-1]+1, prev[j-1]+cost))
            if end<len(a): cur.extend([maxd+1]*(len(a)-end))
            prev=cur
            if min(prev)>maxd: return maxd+1
        return prev[-1]

    def _fuzzy_candidates_for_token(self, token: str, maxd: int) -> List[str]:
        L = len(token); cand = []
        cfg = get_config(); minlen = int(cfg.get("fuzzy_min_len", 5) or 5)
        if L < minlen: return []
        for ln in range(L-maxd, L+maxd+1):
            lst = self.single_word_surfaces.get(ln)
            if not lst: continue
            for s in lst:
                if token[0] != s[0]: continue
                if self._edit_distance_limited(token, s, 1) <= 1:
                    claimants = self.surface_claims.get(s.lower()) or []
                    if len(claimants) == 1:
                        cand.append(s)
        return cand

    def _payload_for_ids_and_claims(self, ids: List[str], claims_on_card: Dict[str, List[str]]) -> Dict[str, Any]:
        meta = {}
        for tid in ids:
            t = self.terms_by_id.get(tid) or {}
            title = (t.get("names") or [t.get("id")])[0]
            tags = t.get("tags", [])
            accent = icon = None
            primary = (t.get("primary_tag") or "").strip()
            if primary and isinstance(tags, list) and primary not in tags:
                tags = [primary] + (tags or [])
            for tag in tags or []:
                tm = (self.tags_meta.get(tag) or {})
                if tm.get("accent") and not accent: accent = tm.get("accent")
                if tm.get("icon") and not icon: icon = tm.get("icon")
            meta[tid] = {"title": title, "tags": tags, "accent": accent, "icon": icon}
        terms = [{"id": tid, "patterns": self.patterns_by_id.get(tid, [])} for tid in ids]
        obj = {"terms": terms, "meta": meta, "claims": claims_on_card}
        # Attach live flags for UI (offline, loggedIn)
        try:
            from . import ems_pocketbase as PB
            a = PB.load_auth() if hasattr(PB, 'load_auth') else {}
            obj["live"] = {"offline": bool(PB.is_offline() if hasattr(PB, 'is_offline') else False),
                           "loggedIn": bool((a or {}).get("token"))}
        except Exception:
            obj["live"] = {"offline": False, "loggedIn": False}
        return obj

    def index_payload(self, limit: int | None = None) -> Dict[str, Any]:
        ids = sorted(self.terms_by_id.keys())
        if limit: ids = ids[:int(limit)]
        meta = {}
        for tid in ids:
            t = self.terms_by_id.get(tid) or {}
            title = (t.get("names") or [t.get("id")])[0]
            tags = t.get("tags", [])
            accent = icon = None
            primary = (t.get("primary_tag") or "").strip()
            if primary and isinstance(tags, list) and primary not in tags:
                tags = [primary] + (tags or [])
            for tag in tags or []:
                tm = (self.tags_meta.get(tag) or {})
                if tm.get("accent") and not accent: accent = tm.get("accent")
                if tm.get("icon") and not icon: icon = tm.get("icon")
            meta[tid] = {"title": title, "tags": tags, "accent": accent, "icon": icon}
        terms = [{"id": tid, "patterns": self.patterns_by_id.get(tid, [])} for tid in ids]
        obj = {"terms": terms, "meta": meta, "claims": {}}
        try:
            from . import ems_pocketbase as PB
            a = PB.load_auth() if hasattr(PB, 'load_auth') else {}
            obj["live"] = {"offline": bool(PB.is_offline() if hasattr(PB, 'is_offline') else False),
                           "loggedIn": bool((a or {}).get("token"))}
        except Exception:
            obj["live"] = {"offline": False, "loggedIn": False}
        return obj

    def matches_for_card(self, card) -> Dict[str, Any]:
        try:
            text = self._note_text_for_fields(card)
            if not text or not self.big_regex:
                return {"terms": [], "meta": {}}
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()
            cache = self.card_cache.get(card.id)
            if cache and cache.get("hash") == h:
                return cache.get("payload") or {"terms": [], "meta": {}}

            maxh = int(get_config().get("max_highlights", 100) or 100)
            found_ids, seen_ids = [], set()
            claims_on_card: Dict[str, List[str]] = {}
            count = 0
            for m in self.big_regex.finditer(text):
                surface = m.group(0); key = surface.lower()
                claimants = self.surface_claims.get(key) or []
                if not claimants: continue
                claims_on_card[key] = claimants
                for tid in claimants:
                    if tid not in seen_ids:
                        seen_ids.add(tid); found_ids.append(tid)
                count += 1
                if count >= maxh: break

            cfg = get_config()
            if cfg.get("fuzzy_enabled", True):
                tokens = set(t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", text))
                added = 0; max_add = int(cfg.get("fuzzy_max_add", 6) or 6)
                for tok in tokens:
                    if tok in claims_on_card: continue
                    cands = self._fuzzy_candidates_for_token(tok, 1)
                    if not cands: continue
                    claimants = self.surface_claims.get(cands[0].lower()) or []
                    if len(claimants) == 1:
                        claims_on_card[cands[0].lower()] = claimants
                        tid = claimants[0]
                        if tid not in seen_ids:
                            seen_ids.add(tid); found_ids.append(tid); added += 1
                            if added >= max_add: break

            payload = self._payload_for_ids_and_claims(found_ids, claims_on_card)
            self.card_cache[card.id] = {"hash": h, "payload": payload}
            return payload
        except Exception as e:
            _log(f"matches_for_card error: {e}")
            return {"terms": [], "meta": {}}

GLOSSARY = GlossaryStore(TERMS_DIR)

# -------------------------- Updater (unchanged core) ---------------------------

def _download_index_and_terms(index_url: str, terms_base: str, tmp_dir: str, bypass_cache: bool):
    token = str(int(time.time())) + "-" + uuid.uuid4().hex[:6] if bypass_cache else ""
    try:
        idx = _http_json(index_url, bust=bypass_cache, token=token)
    except Exception as e:
        raise RuntimeError(f"Index parse error:\n{e}")
    files = idx.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("index.json must contain a non-empty 'files' array.")
    os.makedirs(tmp_dir, exist_ok=True)
    hashes = {}; raw = {}; fetch_errors = {}
    for entry in files:
        fname = entry if isinstance(entry, str) else entry.get("file")
        if not fname: continue
        url = fname if isinstance(fname, str) and fname.startswith("http") else f"{terms_base.rstrip('/')}/{fname}"
        try:
            data = _http_text(url, bust=bypass_cache, token=token)
            try:
                json.loads(data)
            except Exception as e:
                fetch_errors[os.path.basename(fname)] = f"Invalid JSON: {e}"
            local = os.path.join(tmp_dir, os.path.basename(fname))
            with open(local, "w", encoding="utf-8") as fh: fh.write(data)
            raw[os.path.basename(fname)] = data
            hashes[os.path.basename(fname)] = _sha1(data)
        except Exception as e:
            fetch_errors[os.path.basename(fname)] = f"Download failed: {e}"
    meta = {"version": idx.get("version", "?")}
    return raw, hashes, meta, fetch_errors

def _validate_term_json(text: str, fname: str):
    try: obj = json.loads(text)
    except Exception as e: return False, f"JSON parse error: {str(e)}", {}
    idv = obj.get("id") or os.path.splitext(os.path.basename(fname))[0]
    obj["id"] = idv
    if not (obj.get("html") or obj.get("names")):
        return False, "Missing required field: either 'html' or 'names[]' must be present.", {}
    for listy in ["images","actions","how_youll_see_it","problem_solving","differentials","tricks","exam_appearance","treatment","red_flags","algorithm","cases","mnemonics","pitfalls","see_also","prerequisites","sources","tags"]:
        if listy in obj and not isinstance(obj[listy], list):
            return False, f"Field '{listy}' must be a list.", {}
    return True, "", obj

def _download_optional(urls: list, bypass_cache: bool):
    token = str(int(time.time()))
    for u in urls:
        try: return _http_text(u, bust=bypass_cache, token=token)
        except Exception as e: _log(f"optional fetch failed for {u}: {e}")
    return ""

def _download_tags(tmp_state_dir: str, bypass_cache: bool):
    data = _download_optional(["https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary/tags.json"], bypass_cache=bypass_cache)
    if data:
        os.makedirs(tmp_state_dir, exist_ok=True)
        with open(os.path.join(tmp_state_dir, "tags.json"), "w", encoding="utf-8") as fh:
            fh.write(data)

def _changelog(prev: Dict[str, str], new: Dict[str, str]):
    prev_names = set(prev.keys()); new_names = set(new.keys())
    added = sorted(list(new_names - prev_names))
    removed = sorted(list(prev_names - new_names))
    updated = sorted([n for n in (new_names & prev_names) if prev.get(n) != new.get(n)])
    return added, updated, removed

def update_from_remote(bypass_cache: bool = True):
    index_url = RAW_INDEX; terms_base = RAW_TERMS_BASE
    try:
        LOG.log("glossary.update.start", bypass_cache=bool(bypass_cache))
    except Exception:
        pass
    tmp = os.path.join(USER_FILES_DIR, f"tmp_fetch_{int(time.time())}")
    tmp_state = os.path.join(USER_FILES_DIR, f"tmp_state_{int(time.time())}")
    try:
        raw, hashes, meta, fetch_errors = _download_index_and_terms(index_url, terms_base, tmp, bypass_cache=bypass_cache)
        _download_tags(tmp_state, bypass_cache=bypass_cache)
        ok_files = {}; errors = dict(fetch_errors)
        for fname, text in raw.items():
            ok, err, obj = _validate_term_json(text, fname)
            if ok: ok_files[fname] = text
            else: errors[fname] = err
        if not ok_files and errors:
            raise RuntimeError("All files invalid.\n" + "\n".join(f"{k}: {v}" for k, v in errors.items()))

        prev = {}
        if os.path.exists(LAST_INDEX_SNAPSHOT):
            try: prev = json.load(open(LAST_INDEX_SNAPSHOT, "r", encoding="utf-8")) or {}
            except Exception: prev = {}
        valid_hashes = {k: v for k, v in hashes.items() if k in ok_files}
        added, updated, removed = _changelog(prev, valid_hashes)

        if os.path.isdir(TERMS_DIR): shutil.rmtree(TERMS_DIR, ignore_errors=True)
        os.makedirs(TERMS_DIR, exist_ok=True)
        for fname, text in ok_files.items():
            with open(os.path.join(TERMS_DIR, fname), "w", encoding="utf-8") as fh: fh.write(text)
        try: shutil.move(os.path.join(tmp_state, "tags.json"), TAGS_JSON_PATH)
        except Exception: pass

        json.dump(valid_hashes, open(LAST_INDEX_SNAPSHOT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump({"added": added, "updated": updated, "removed": removed}, open(LAST_DIFF, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        with open(LAST_VERSION, "w", encoding="utf-8") as fh: fh.write(str(meta.get("version", "?")))
        try: os.remove(SEEN_VERSION)
        except Exception: pass

        GLOSSARY._load_tags_palette(); GLOSSARY.reload()
        cfg = get_config(); cfg["last_update_check"] = int(time.time()); write_config(cfg)

        summary = f"EMS Glossary updated to {meta.get('version','?')}.  Added {len(added)}, Updated {len(updated)}, Removed {len(removed)}."
        try:
            LOG.log("glossary.update.done", version=str(meta.get('version','?')), added=len(added), updated=len(updated), removed=len(removed), skipped=len(errors))
        except Exception:
            pass
        details = ""
        if errors:
            details = "Some files were skipped:\n\n" + "\n".join(f"• {fn}: {msg}" for fn, msg in errors.items())
            details += "\n\nValid files were applied successfully."
        return True, summary, details
    except Exception as e:
        details = f"Update failed.\n\n{index_url} ? {e}\n\nTip: open the URL above in a browser and verify it's valid JSON."
        try:
            LOG.log("glossary.update.error", error=str(e))
        except Exception:
            pass
        return False, "Update failed - see details.", details
    finally:
        try: shutil.rmtree(tmp, ignore_errors=True)
        except Exception: pass
        try: shutil.rmtree(tmp_state, ignore_errors=True)
        except Exception: pass

# ------------------------------ Web injection ---------------------------------

mw.addonManager.setWebExports(MODULE, r"web/.*\.(css|js|png|jpg|jpeg|gif|webp|svg)")

def on_webview_will_set_content(web_content, context) -> None:
    try:
        from aqt.reviewer import Reviewer; is_reviewer = isinstance(context, Reviewer)
    except Exception:
        is_reviewer = False
    klass = context.__class__.__name__ if context else ""
    want = is_reviewer or klass in ("Previewer", "CardLayout")
    if not want:
        try:
            LOG.log("web.inject.skip", context=klass)
        except Exception:
            pass
        return

    cfg = get_config()
    pkg = mw.addonManager.addonFromModule(MODULE)
    web_content.css.append(f"/_addons/{pkg}/web/popup.css")
    web_content.js.append(f"/_addons/{pkg}/web/popup.js")
    try:
        LOG.log("web.inject", context=klass)
    except Exception:
        pass

    width = int(cfg.get("tooltip_width_px", 640))
    font_px = int(cfg.get("popup_font_px", 16))
    hover_mode = str(cfg.get("hover_mode", "click")).strip().lower()
    if hover_mode not in ("click", "hover"):
        hover_mode = "click"
    hover_delay_ms = int(cfg.get("hover_delay_ms", 120))
    click_anywhere = bool(cfg.get("open_with_click_anywhere", True))

    # Appearance overrides (CSS variables) and custom CSS
    css_popup_bg = cfg.get("popup_bg", "rgba(15,18,26,.96)")
    css_popup_fg = cfg.get("popup_fg", "#edf1f7")
    try:
        if isinstance(css_popup_bg, str) and css_popup_bg.endswith(")c"):
            css_popup_bg = css_popup_bg[:-1]
    except Exception:
        pass
    css_popup_muted = cfg.get("popup_muted", "#a4afbf")
    css_popup_border = cfg.get("popup_border", "rgba(255,255,255,.10)")
    css_popup_accent = cfg.get("popup_accent", "#8b5cf6")
    css_popup_accent2 = cfg.get("popup_accent2", "#06b6d4")
    css_popup_radius = int(cfg.get("popup_radius_px", 14))
    extra_css = cfg.get("popup_custom_css", "") or ""

    font_url = str(cfg.get("font_url", "")).strip()
    font_title = cfg.get("font_title", "'Baloo 2'")
    font_body = cfg.get("font_body", "'Montserrat'")
    font_links = ""
    try:
        if font_url:
            font_links = (
                "<link rel='preconnect' href='https://fonts.googleapis.com'>"
                "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
                f"<link rel='stylesheet' href='{html.escape(font_url)}'>"
            )
    except Exception:
        pass

    theme = f"""
    <style>
      :root{{
        --ems-bg: {css_popup_bg};
        --ems-fg: {css_popup_fg};
        --ems-muted: {css_popup_muted};
        --ems-border: {css_popup_border};
        --ems-accent: {css_popup_accent};
        --ems-accent-2: {css_popup_accent2};
        --ems-radius: {css_popup_radius}px;
        --ems-font-title: {font_title}, system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, Arial, sans-serif;
        --ems-font-body:  {font_body}, system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, Arial, sans-serif;
      }}
      .ems-popover{{ max-width: {width}px; font-size: {font_px}px; background: {css_popup_bg} !important; }}
      .ems-topbar{{ background: {css_popup_bg}; }}
      {extra_css}
    </style>
    {font_links}
    <script>window.EMS_CFG = {{
        hoverMode: {json.dumps(hover_mode)},
        hoverDelay: {hover_delay_ms},
        clickAnywhere: {str(click_anywhere).lower()}
    }};</script>
    """
    web_content.head += theme

gui_hooks.webview_will_set_content.append(on_webview_will_set_content)

# Apply updated theme to currently open reviewer/previewer without reload
def _apply_theme_runtime():
    try:
        cfg = get_config()
        width = int(cfg.get("tooltip_width_px", 640))
        font_px = int(cfg.get("popup_font_px", 16))
        css_popup_bg = cfg.get("popup_bg", "rgba(15,18,26,.96)")
        try:
            if isinstance(css_popup_bg, str) and css_popup_bg.endswith(")c"):
                css_popup_bg = css_popup_bg[:-1]
        except Exception:
            pass
        css_popup_fg = cfg.get("popup_fg", "#edf1f7")
        css_popup_muted = cfg.get("popup_muted", "#a4afbf")
        css_popup_border = cfg.get("popup_border", "rgba(255,255,255,.10)")
        css_popup_accent = cfg.get("popup_accent", "#8b5cf6")
        css_popup_accent2 = cfg.get("popup_accent2", "#06b6d4")
        css_popup_radius = int(cfg.get("popup_radius_px", 14))
        extra_css = cfg.get("popup_custom_css", "") or ""
        hover_mode = str(cfg.get("hover_mode", "click")).strip().lower()
        hover_delay_ms = int(cfg.get("hover_delay_ms", 120))
        click_anywhere = bool(cfg.get("open_with_click_anywhere", True))

        font_url = str(cfg.get("font_url", "")).strip()
        font_title = cfg.get("font_title", "'Baloo 2'")
        font_body = cfg.get("font_body", "'Montserrat'")
        css = (
            f":root{{--ems-bg:{css_popup_bg};--ems-fg:{css_popup_fg};--ems-muted:{css_popup_muted};--ems-border:{css_popup_border};--ems-accent:{css_popup_accent};--ems-accent-2:{css_popup_accent2};--ems-radius:{css_popup_radius}px;--ems-font-title:{font_title},system-ui,-apple-system,'Segoe UI',Roboto,Ubuntu,Arial,sans-serif;--ems-font-body:{font_body},system-ui,-apple-system,'Segoe UI',Roboto,Ubuntu,Arial,sans-serif;}} "
            f".ems-popover{{max-width:{width}px;font-size:{font_px}px;background:{css_popup_bg} !important;}} "
            f".ems-topbar{{background:{css_popup_bg};}} "
            + (extra_css or "")
        )
        js = (
            "(function(){"
            "var id='emsUserTheme';var el=document.getElementById(id);"
            "if(!el){el=document.createElement('style');el.id=id;document.head.appendChild(el);}"
            f"el.textContent={json.dumps(css)};"
            "var fid='emsUserFont';var url=" + json.dumps(font_url) + ";"
            "if(url && !document.getElementById(fid)){var ln=document.createElement('link');ln.rel='stylesheet';ln.id=fid;ln.href=url;document.head.appendChild(ln);}"
            "window.EMS_CFG=window.EMS_CFG||{};"
            f"window.EMS_CFG.hoverMode={json.dumps(hover_mode)};"
            f"window.EMS_CFG.hoverDelay={hover_delay_ms};"
            f"window.EMS_CFG.clickAnywhere={(str(click_anywhere).lower())};"
            "})();"
        )
        # Reviewer webview
        try:
            if getattr(mw, 'reviewer', None) and getattr(mw.reviewer, 'web', None):
                mw.reviewer.web.eval(js)
        except Exception:
            pass
        # Card layout/previewer if open
        try:
            from aqt.dialogs import _dialogs
            for key in ("CardLayout", "Previewer"):
                try:
                    inst = _dialogs.get((key, None))
                    if inst and inst[1] and getattr(inst[1], 'web', None):
                        inst[1].web.eval(js)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception as e:
        _log(f"apply theme runtime failed: {e}")

# ---------------------------- Popup Rendering ---------------------------------

def _brand_block_html(tid: str) -> str:
    pkg = mw.addonManager.addonFromModule(MODULE)
    return ("<div class='ems-brand'><div class='ems-brand-inner'>"
            f"<img class='ems-logo' src='/_addons/{pkg}/web/ems_logo.png' alt='EMS'/> "
            "<a class='ems-site' href='https://entermedschool.com' target='_blank' rel='noopener'><span class='ems-brand-name'>EnterMedSchool</span></a> "
            "<span class='ems-by'>&nbsp;by <a class='ems-contact' href='mailto:contact@arihoresh.com'>Ari Horesh</a></span>"
            "</div><div class='ems-small'><a class='ems-suggest' href='https://github.com/EnterMedSchool/Anki/issues/new?title=Glossary%20edit%20suggestion%20for%20"
            + html.escape(tid) + "' target='_blank' rel='noopener'>Suggest edit &rarr;</a></div></div>")

def _sanitize_html(value: str) -> str:
    return GLOSSARY._sanitize_html(value)

def _bullets(items):
    items = [x for x in (items or []) if x]
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>"

def _section_html(name: str, icon: str, content_html: str, sec_id: str, extra_class: str = "") -> str:
    # Hide obviously corrupted icons like '' or replacement chars
    try:
        sicon = (icon or "").strip()
        if (not sicon) or (sicon.replace('?', '').strip() == '') or ('·' in sicon):
            sicon = ""
    except Exception:
        sicon = ""
    label = (sicon + " " if sicon else "") + name
    if not content_html:
        return f"<details class='ems-section is-disabled {extra_class}' data-sec='{sec_id}'><summary>{label}<button class='ems-learn' disabled title='No content'>+ Learn</button></summary></details>"
    return f"<details open class='ems-section {extra_class}' data-sec='{sec_id}'><summary>{label}<button class='ems-learn' title='Add this as a card'>+ Learn</button></summary>{content_html}</details>"

def _algo_html(steps: List[str]) -> str:
    if not steps: return ""
    return "<div class='ems-algo'>" + "".join(f"<div class='step'><span class='n'>{i+1}</span> {html.escape(s)}</div>" for i, s in enumerate(steps)) + "</div>"

def _cases_html(cases: List[Dict[str, Any]]) -> str:
    if not cases: return ""
    rows = []
    for i, c in enumerate(cases, 1):
        stem = html.escape(c.get("stem", "")); clues = _bullets(c.get("clues") or [])
        ans = html.escape(c.get("answer", "")); teach = html.escape(c.get("teaching", ""))
        rows.append(f"<details open class='ems-case'><summary>Case {i}</summary><div class='stem'>{stem}</div>{clues}<div class='ans'><b>Dx:</b> {ans}</div><div class='teach'>{teach}</div></details>")
    return "<div class='ems-cases'>" + "".join(rows) + "</div>"

def _term_html_from_schema(t: Dict[str, Any]) -> str:
    try:
        _names = t.get("names") or []
        title = _names[0] if _names else (t.get("id") or "Untitled")
    except Exception:
        title = str(t.get("id") or "Untitled")
    definition = t.get("definition", "")
    actions = t.get("actions") or []
    imgs = t.get("images") or []
    if not imgs and "image" in t:
        img = t["image"]
        if isinstance(img, str): imgs = [{"src": img, "alt": ""}]
        elif isinstance(img, dict): imgs = [img]

    parts = []
    if imgs:
        if len(imgs) == 1:
            im = imgs[0]
            src = html.escape(im.get("src", "")); alt = html.escape(im.get("alt", ""))
            credit = im.get("credit") or {}
            if isinstance(credit, str):
                credit_text, credit_href = "image credit", credit
            elif isinstance(credit, dict):
                credit_text = credit.get("text") or "image credit"; credit_href = credit.get("href") or src
            else:
                credit_text, credit_href = "image credit", src
            parts.append(f"<div class='ems-media'><img class='ems-img' src='{src}' alt='{alt}'/>"
                         f"<div class='ems-credit'><a href='{credit_href}' target='_blank' rel='noopener'>{html.escape(credit_text)}</a></div></div>")
        else:
            parts.append("<div class='ems-gallery'>")
            for im in imgs:
                src = html.escape(im.get("src", "")); alt = html.escape(im.get("alt", ""))
                parts.append(f"<figure><img class='ems-img' src='{src}' alt='{alt}'/><figcaption class='ems-credit'><a href='{src}' target='_blank' rel='noopener'>image credit</a></figcaption></figure>")
            parts.append("</div>")

    parts.append("<div class='ems-content'>")
    # Rating + credits header (fetched via bridge on open)
    try:
        tid = html.escape(t.get("id") or "")
        stars_html = "".join([f"<button type='button' class='ems-star' data-star='{i}' aria-label='{i} star'>&#9733;</button>" for i in range(1,6)])
        # Build initial credits from JSON if present; PB credits will be appended by JS
        json_creds = []
        init_credits = []
        try:
            for c in (t.get('credits') or []):
                disp = (c.get('display') or c.get('email') or 'User')
                role = (c.get('role') or 'Contributor')
                avatar = (c.get('avatar') or '')
                json_creds.append(f"<span class='ems-creditchip' title='{html.escape(role)}'>{html.escape(disp)}</span>")
                try:
                    init_credits.append({"display": disp, "avatar": avatar})
                except Exception:
                    pass
        except Exception:
            json_creds = []
        credits_html = " ".join(json_creds)
        try:
            s = json.dumps(init_credits, ensure_ascii=False)
            s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            init_credits_attr = s
        except Exception:
            init_credits_attr = "[]"
        rating_block = (
            f"<div class='ems-ratingbar' data-ems-tid='{tid}'>"
            f"  <div class='ems-rating-stars' role='radiogroup' aria-label='Rate'>{stars_html}</div>"
            f"  <div class='ems-rating-avg' title='Average rating'>-</div>"
            f"</div>"
        )
        parts.append(rating_block)
        parts.append(
            f"<div class='ems-creditsblock' data-ems-tid='{tid}' data-init-credits='{init_credits_attr}'>"
            f"  <div class='ems-credtitle'>Contributors</div>"
            f"  <div class='ems-credits'>{credits_html}</div>"
            f"</div>"
        )
    except Exception:
        pass
    parts.append(f"<h3>{html.escape(title)}</h3>")
    if definition:
        parts.append(_section_html("Definition", "", f"<p class='ems-lead'>{html.escape(definition)}</p>", "definition"))

    parts.append(_section_html("Why it matters", "", f"<p>{html.escape(t.get('why_it_matters',''))}</p>" if t.get("why_it_matters") else "", "why_it_matters"))
    parts.append(_section_html("How you'll see it", "", _bullets(t.get("how_youll_see_it")), "how_youll_see_it"))
    parts.append(_section_html("Problem solving — quick approach", "", _bullets(t.get("problem_solving")), "problem_solving"))
    diffs = t.get("differentials") or []
    if diffs:
        items = []
        for d in diffs:
            if isinstance(d, str):
                items.append(f"<li>{html.escape(d)}</li>")
            elif isinstance(d, dict):
                name = html.escape(d.get("name") or d.get("id", "?"))
                ref = d.get("id"); hint = html.escape(d.get("hint", ""))
                if ref: items.append(f"<li><a href='#' data-ems-link='{html.escape(ref)}'>{name}</a> — {hint}</li>")
                else: items.append(f"<li>{name} — {hint}</li>")
        parts.append(_section_html("Differentials & Look-alikes", "", "<ul>" + "".join(items) + "</ul>", "differentials"))
    else:
        parts.append(_section_html("Differentials & Look-alikes", "", "", "differentials"))
    parts.append(_section_html("Tricks to avoid traps", "", _bullets(t.get("tricks")), "tricks"))
    parts.append(_section_html("How exams like to ask it", "", _bullets(t.get("exam_appearance")), "exam_appearance"))
    parts.append(_section_html("Treatment — exam/wards version", "", _bullets(t.get("treatment")), "treatment", "is-success"))
    parts.append(_section_html("Red flags — do not miss", "", _bullets(t.get("red_flags")), "red_flags", "is-danger"))
    parts.append(_section_html("1-minute algorithm", "?", _algo_html(t.get("algorithm") or []), "algorithm", "is-algo"))
    parts.append(_section_html("Mini-cases", "", _cases_html(t.get("cases") or []), "cases"))

    related = []
    for sid in (t.get("see_also") or []): related.append(f"<a href='#' data-ems-link='{sid}'>[{sid}]</a>")
    for sid in (t.get("prerequisites") or []): related.append(f"<a href='#' data-ems-link='{sid}'>[{sid}]</a>")
    if related: parts.append("<div class='ems-related ems-section'>" + " · ".join(related) + "</div>")
    if t.get("sources"):
        srcs = " · ".join(f"<a href='{html.escape(s.get('url',''))}' target='_blank' rel='noopener'>{html.escape(s.get('title','Source'))}</a>" for s in (t.get('sources') or []) if s.get('url'))
        parts.append(f"<div class='ems-sources ems-section'>{srcs}</div>")
    if actions := (t.get("actions") or []):
        btns = []
        for a in actions:
            btns.append(f"<a class='ems-btn ems-btn--{a.get('variant','primary')}' href='{html.escape(a.get('href','#'))}' target='_blank' rel='noopener'>{html.escape(a.get('label','Open'))}</a>")
        parts.append("<div class='ems-actions'>" + " ".join(btns) + "</div>")

    parts.append("</div>")
    parts.append(_brand_block_html(t.get("id")))
    html_out = "<div class='ems-body'>" + "".join(parts) + "</div>"
    return _sanitize_html(html_out)

def GlossaryStore_popup_payload(self, term_id: str) -> Dict[str, Any]:
    t = self.terms_by_id.get(term_id)
    if not t:
        return {"id": term_id, "html": "<div class='ems-popover'><em>No entry.</em></div>", "title": term_id}
    if t.get("html"):
        core = _sanitize_html(t.get("html", ""))
        if "<div class='ems-brand'" not in core: core += _brand_block_html(t.get("id"))
        obj = {"id": t.get("id"), "html": "<div class='ems-body'>" + core + "</div>", "title": (t.get("names") or [t.get("id")])[0]}
        try:
            from . import ems_pocketbase as PB
            a = PB.load_auth() if hasattr(PB, 'load_auth') else {}
            obj["live"] = {"offline": bool(PB.is_offline() if hasattr(PB, 'is_offline') else False),
                           "loggedIn": bool((a or {}).get("token"))}
        except Exception:
            obj["live"] = {"offline": False, "loggedIn": False}
        return obj
    html_out = _term_html_from_schema(t); title = (t.get("names") or [t.get("id")])[0]
    obj = {"id": t.get("id"), "html": html_out, "title": title}
    try:
        from . import ems_pocketbase as PB
        a = PB.load_auth() if hasattr(PB, 'load_auth') else {}
        obj["live"] = {"offline": bool(PB.is_offline() if hasattr(PB, 'is_offline') else False),
                       "loggedIn": bool((a or {}).get("token"))}
    except Exception:
        obj["live"] = {"offline": False, "loggedIn": False}
    return obj
GlossaryStore.popup_payload = GlossaryStore_popup_payload

# ---------------------------- Learning cards ----------------------------------

LEARN_SECTIONS = [
    ("definition", "Definition"),
    ("why_it_matters", "Why it matters"),
    ("how_youll_see_it", "How you'll see it"),
    ("problem_solving", "Problem solving — quick approach"),
    ("differentials", "Differentials & Look-alikes"),
    ("tricks", "Tricks to avoid traps"),
    ("exam_appearance", "How exams like to ask it"),
    ("treatment", "Treatment — exam/wards version"),
    ("red_flags", "Red flags — do not miss"),
    ("algorithm", "1-minute algorithm"),
    ("cases", "Mini-cases"),
]

def _section_content_html(t: Dict[str, Any], sec_id: str) -> str:
    if sec_id == "definition":
        txt = t.get("definition", "")
        return f"<p class='ems-lead'>{html.escape(txt)}</p>" if txt else ""
    if sec_id == "why_it_matters":
        txt = t.get("why_it_matters", "")
        return f"<p>{html.escape(txt)}</p>" if txt else ""
    if sec_id == "how_youll_see_it":
        return _bullets(t.get("how_youll_see_it"))
    if sec_id == "problem_solving":
        return _bullets(t.get("problem_solving"))
    if sec_id == "differentials":
        diffs = t.get("differentials") or []
        if not diffs: return ""
        items = []
        for d in diffs:
            if isinstance(d, str): items.append(f"<li>{html.escape(d)}</li>")
            elif isinstance(d, dict):
                name = html.escape(d.get("name") or d.get("id","?"))
                hint = html.escape(d.get("hint",""))
                items.append(f"<li>{name} — {hint}</li>")
        return "<ul>" + "".join(items) + "</ul>"
    if sec_id == "tricks":
        return _bullets(t.get("tricks"))
    if sec_id == "exam_appearance":
        return _bullets(t.get("exam_appearance"))
    if sec_id == "treatment":
        return _bullets(t.get("treatment"))
    if sec_id == "red_flags":
        return _bullets(t.get("red_flags"))
    if sec_id == "algorithm":
        steps = t.get("algorithm") or []
        return _algo_html(steps)
    if sec_id == "cases":
        return _cases_html(t.get("cases") or [])
    return ""

def _ensure_learn_model() -> Any:
    mm = mw.col.models
    m = mm.by_name("EMS — Learn Card")
    if m:
        return m
    m = mm.new("EMS — Learn Card")
    mm.add_field(m, mm.new_field("Front"))
    mm.add_field(m, mm.new_field("Back"))
    mm.add_field(m, mm.new_field("EMS_UID"))
    css = """
:root{ --ems-bg:#0f1117; --ems-fg:#eaeef7; --ems-muted:#9aa4b2; --ems-border:rgba(255,255,255,.1); }
.card{ background:#0f1117; color:#eaeef7; font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial; }
.ems-front{ font-size:32px; text-align:center; margin:14px auto 16px auto; }
.ems-chip{ display:inline-block; background:rgba(139,92,246,.25); padding:2px 10px; border-radius:12px; border:1px solid rgba(139,92,246,.4); font-size:14px; margin-left:8px; }
hr#answer{ border:none; border-top:1px solid var(--ems-border); margin:14px 0; }
.ems-answer{ max-width:900px; margin:0 auto; line-height:1.6; font-size:20px; }
.ems-answer ul{ margin:8px 0 4px 22px; }
.ems-answer li{ margin:6px 0; }
"""
    m["css"] = css
    t = mm.new_template("Card 1")
    t["qfmt"] = "{{Front}}"
    t["afmt"] = "{{FrontSide}}<hr id=answer>{{Back}}"
    mm.add_template(m, t)
    mm.add(m)
    return m

def _target_deck_id(reviewer) -> int:
    cfg = get_config()
    if cfg.get("learn_target") == "current":
        try:
            return reviewer.card.did if reviewer and reviewer.card else mw.col.decks.get_current_id()
        except Exception:
            return mw.col.decks.get_current_id()
    name = cfg.get("learn_deck_name") or "EnterMedSchool — Terms"
    try:
        return mw.col.decks.id(name)
    except Exception:
        d = mw.col.decks.by_name(name)
        return d["id"] if d else mw.col.decks.id(name)

def _normalize_html_for_uid(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"<[^>]+>", "", s)  # strip tags for stability
    return s

def _add_learn_card(term: Dict[str, Any], sec_id: str, reviewer) -> Tuple[bool, str]:
    """Return (added, uid) and skip if duplicate."""
    title = (term.get("names") or [term.get("id")])[0]
    disp = dict(LEARN_SECTIONS).get(sec_id, sec_id)
    content_html = _section_content_html(term, sec_id)
    if not content_html:
        return (False, "empty")
    uid = _sha1(f"{term.get('id')}|{sec_id}|{_normalize_html_for_uid(content_html)}")[:16]
    tag_uid = f"ems_uid_{uid}"

    # Check duplicate
    try:
        existing = mw.col.find_notes(f"tag:{tag_uid}")
        if existing:
            return (False, uid)
    except Exception:
        pass

    # Build note
    m = _ensure_learn_model()
    note = Note(mw.col, m)
    front = f"<div class='ems-front'>{html.escape(title)} <span class='ems-chip'>{html.escape(disp)}</span></div>"
    back = f"<div class='ems-answer'>{content_html}</div>"
    note["Front"] = front
    note["Back"] = back
    note["EMS_UID"] = uid
    note.tags.append("ems_learn")
    note.tags.append(f"term_{term.get('id')}")
    note.tags.append(f"section_{sec_id}")
    note.tags.append(tag_uid)

    did = _target_deck_id(reviewer)
    try:
        mw.col.add_note(note, did)
    except Exception:
        mw.col.addNote(note, did)  # older Anki API
    return (True, uid)

def _add_learn_all(term: Dict[str, Any], reviewer) -> Tuple[int, int]:
    added = skipped = 0
    for sec_id, _disp in LEARN_SECTIONS:
        ok, uid = _add_learn_card(term, sec_id, reviewer)
        if ok: added += 1
        else:
            if uid != "empty":
                skipped += 1
    return added, skipped

# ------------------------- JS bridge (new commands) ----------------------------

def on_js_message(handled, message: str, context):
    # Accept messages from any webview for read-only commands (get),
    # but restrict actions (learn/pin) to the Reviewer.
    if not isinstance(message, str) or not message.startswith("ems_glossary:"): return handled
    try:
        from aqt.reviewer import Reviewer
        is_reviewer = isinstance(context, Reviewer)
    except Exception:
        is_reviewer = False
    parts = message.split(":", 3)
    cmd = parts[1]

    if cmd == "log":
        # ems_log:LEVEL:message:json
        try:
            level = (parts[2] if len(parts) > 2 else "INFO").upper()
            rest = parts[3] if len(parts) > 3 else ""
            try:
                msg, payload = rest.split(":", 1)
            except ValueError:
                msg, payload = rest, "{}"
            try:
                import urllib.parse, json as _json
                msg = urllib.parse.unquote(msg)
                payload = urllib.parse.unquote(payload)
                data = _json.loads(payload or "{}") if payload else {}
            except Exception:
                data = {"raw": rest}
            LOG.log("js", level=level, message=msg, **(data or {}))
        except Exception:
            pass
        return (True, {"ok": True})

    if cmd == "suggest":
        # open suggest dialog with prefilled name; reviewer only
        if not is_reviewer:
            return (True, {"ok": False})
        try:
            text = urllib.parse.unquote(parts[2].strip())
        except Exception:
            text = parts[2].strip()
        try:
            d = SuggestTermDialog(mw)
            try:
                if text:
                    d.namesLE.setText(text)
                    try: d._update_live_preview()
                    except Exception: pass
            except Exception:
                pass
            try:
                LOG.log("glossary.suggest.open")
            except Exception:
                pass
            d.exec()
            return (True, {"ok": True})
        except Exception as e:
            try:
                LOG.log("glossary.suggest.error", error=str(e))
            except Exception:
                pass
            return (True, {"ok": False})

    if cmd == "get":
        term_id = parts[2].strip()
        try:
            LOG.log("glossary.open", id=term_id)
            try:
                from .LeoTamagotchi import gui as _leo_tamagotchi
                _leo_tamagotchi.show_temp_character("LeoCuriousLearning", seconds=10)
            except Exception as e:
                LOG.log("tamagotchi.error", where="on term open", error=str(e))
            payload = GLOSSARY.popup_payload(term_id)
            # Best-effort: ensure PB has JSON credits for analytics; run in background
            try:
                t = (GLOSSARY.terms_by_id or {}).get(term_id) or {}
                creds = t.get("credits") or []
                if creds:
                    import threading
                    def _run():
                        try:
                            from . import ems_pocketbase as PB
                            PB.credits_ensure(term_id, creds)
                        except Exception:
                            pass
                    threading.Thread(target=_run, daemon=True).start()
            except Exception:
                pass
            LOG.log("glossary.payload", id=term_id, bytes=len((payload.get('html') or '').encode('utf-8')))
            return (True, payload)
        except Exception:
            LOG.log("glossary.error", id=term_id, error="payload build failed")
            return (True, {"id": term_id, "html": "<div class='ems-body'><div class='ems-small'>No entry.</div></div>", "title": term_id})

    if cmd == "rate":
        # rating commands: rate:get:tid  or rate:set:tid:stars
        sub = parts[2].strip() if len(parts) > 2 else ""
        if sub == "get":
            tid = parts[3].strip() if len(parts) > 3 else ""
            try:
                from . import ems_pocketbase as PB
            except Exception:
                PB = None
            # Kick off background fetch to avoid blocking UI; return fast placeholder

            def _bg():
                try:
                    if not PB:
                        return
                    ok, data = PB.rating_get(tid)
                    if not ok or not isinstance(data, dict):
                        return
                    avg = data.get("avg") or 0
                    count = data.get("count") or 0
                    mine = data.get("mine", None)
                    import json as _json
                    js_tid = _json.dumps(tid)
                    js_avg = "0" if not isinstance(avg, (int, float)) else str(float(avg))
                    js_count = "0" if not isinstance(count, (int, float)) else str(int(count))
                    js_mine = "null"
                    try:
                        if isinstance(mine, (int, float)):
                            js_mine = str(int(mine))
                    except Exception:
                        js_mine = "null"
                    # Escape JS braces in f-string by doubling them
                    js = f"try{{ if(window.EMSGlossary && EMSGlossary.updateRating) EMSGlossary.updateRating({js_tid}, {js_avg}, {js_count}, {js_mine}); }}catch(e){{}}"
                    try:
                        mw.taskman.run_on_main(lambda: _safe_eval_js_on_context(context, js))
                    except Exception:
                        try:
                            _safe_eval_js_on_context(context, js)
                        except Exception:
                            pass
                except Exception as e:
                    try:
                        LOG.log("rating.error", id=tid, error=str(e))
                    except Exception:
                        pass
            try:
                import threading
                threading.Thread(target=_bg, daemon=True).start()
            except Exception:
                pass
            # Return immediately; JS will update via EMSGlossary.updateRating when ready
            return (True, {"ok": True})
        if sub == "set":
            tail = parts[3] if len(parts) > 3 else ""
            try:
                tid, val = tail.split(":", 1)
                stars = int(val)
            except Exception:
                return (True, {"ok": False, "error": "Bad args"})
            try:
                from . import ems_pocketbase as PB
                ok, data = PB.rating_set(tid, stars)
                LOG.log("rating.set", id=tid, stars=stars, ok=ok)
                return (True, {"ok": ok, **(data or {})})
            except Exception as e:
                LOG.log("rating.error", id=tid, error=str(e))
                return (True, {"ok": False, "error": str(e)})

    if cmd == "credits":
        # credits:get:tid
        sub = parts[2].strip() if len(parts) > 2 else ""
        if sub == "get":
            tid = parts[3].strip() if len(parts) > 3 else ""
            try:
                from . import ems_pocketbase as PB
                ok, data = PB.credits_get(tid)
                return (True, {"ok": ok, **(data or {})})
            except Exception as e:
                return (True, {"ok": False, "error": str(e)})

    # COMMENTS FEATURE DISABLED
    # if cmd == "comments":
    #     ...

    if cmd == "auth":
        sub = parts[2].strip() if len(parts) > 2 else ""
        if sub == "login":
            try:
                d = PocketBaseLoginDialog(mw)
                d.exec()
                return (True, {"ok": True})
            except Exception as e:
                return (True, {"ok": False, "error": str(e)})

    if cmd == "profile":
        # profile:get   or  profile:set:display|avatar|about (url encoded using \t as separator via JS)
        sub = parts[2].strip() if len(parts) > 2 else ""
        try:
            from . import ems_pocketbase as PB
        except Exception:
            PB = None
        if sub == "get":
            if not PB: return (True, {"ok": False})
            ok, data = PB.profile_get()
            return (True, {"ok": ok, **(data if isinstance(data, dict) else {})})
        if sub == "set":
            tail = parts[3] if len(parts) > 3 else ""
            try:
                disp, avatar, about = [urllib.parse.unquote_plus(x) for x in tail.split("\t", 2)]
            except Exception:
                disp = avatar = about = ""
            ok, msg = PB.profile_upsert(disp, avatar, about)
            return (True, {"ok": ok, "message": msg})

    if cmd == "pin":
        if not is_reviewer:
            return (True, {"ok": False})
        tid = parts[2].strip()
        payload = GLOSSARY.popup_payload(tid)
        pid = f"pin{int(time.time()*1000)%100000}"
        obj = {"id": pid, "tid": tid, "title": payload.get("title") or tid, "html": payload.get("html",""), "x": 60, "y": 60}
        try:
            LOG.log("glossary.pin", id=tid, pid=pid)
        except Exception:
            pass
        return (True, obj)

    if cmd == "learn":
        if not is_reviewer:
            return (True, {"ok": False, "message": "Unavailable here."})
        tid = parts[2].strip()
        sec = parts[3].strip() if len(parts) > 3 else ""
        t = GLOSSARY.terms_by_id.get(tid)
        if not t or not sec: return (True, {"ok": False, "message": "Missing content."})
        ok, uid = _add_learn_card(t, sec, context)
        if ok: 
            mw.reset()
            try:
                LOG.log("glossary.learn", id=tid, section=sec, ok=True)
            except Exception:
                pass
            return (True, {"ok": True, "message": "Added ?"})
        else:
            if uid == "empty": return (True, {"ok": False, "message": "Nothing to add."})
            try:
                LOG.log("glossary.learn", id=tid, section=sec, ok=False)
            except Exception:
                pass
            return (True, {"ok": False, "message": "Already added."})

    if cmd == "learnall":
        if not is_reviewer:
            return (True, {"ok": False, "message": "Unavailable here."})
        tid = parts[2].strip()
        t = GLOSSARY.terms_by_id.get(tid)
        if not t: return (True, {"ok": False, "message": "No term."})
        a, s = _add_learn_all(t, context)
        if a or s: mw.reset()
        return (True, {"ok": True, "message": f"Added {a}, skipped {s} (dupes/empty)."})

    if cmd == "whatsnew":
        try:
            diff = {"added":[], "updated":[], "removed":[]}
            if os.path.exists(LAST_DIFF):
                try: diff = json.load(open(LAST_DIFF,"r",encoding="utf-8")) or diff
                except Exception: pass
            version = ""
            if os.path.exists(LAST_VERSION):
                try: version = open(LAST_VERSION,"r",encoding="utf-8").read().strip()
                except Exception: pass
            seen = ""
            if os.path.exists(SEEN_VERSION):
                try: seen = open(SEEN_VERSION,"r",encoding="utf-8").read().strip()
                except Exception: pass
            should_show = False
            if version and (version != seen) and (diff.get("added") or diff.get("updated")):
                should_show = True
                try: open(SEEN_VERSION,"w",encoding="utf-8").write(version)
                except Exception: pass
            return (True, {"shouldShow": should_show})
        except Exception:
            return (True, {"shouldShow": False})

    return handled

gui_hooks.webview_did_receive_js_message.append(on_js_message)

# ------------------------------- Injection ------------------------------------

def inject_on_card(text: str, card, kind: str) -> str:
    try:
        payload = GLOSSARY.matches_for_card(card)
        if not payload.get("terms"):
            cfg = get_config()
            if cfg.get("ship_index_if_no_matches", True):
                limit = int(cfg.get("ship_index_limit", 3000) or 3000)
                payload = GLOSSARY.index_payload(limit=limit)
                if not payload.get("terms"):
                    return text
        js = f"""
<script>(function(p){{window.__EMS_PAYLOAD = window.__EMS_PAYLOAD || []; window.__EMS_PAYLOAD.push(p); if (window.EMSGlossary && window.EMSGlossary.setup) {{ try {{ window.EMSGlossary.setup(p); }} catch(e){{ console && console.warn('EMS setup error', e); }} }} }})
({json.dumps(payload)});
</script>
"""
        return text + js
    except Exception as e:
        _log(f"inject_on_card error: {e}")
        return text

gui_hooks.card_will_show.append(inject_on_card)

# ------------------------------- Settings UI ----------------------------------

def _ensure_logo_icon() -> QIcon:
    try: return QIcon(LOGO_PATH) if os.path.exists(LOGO_PATH) else QIcon()
    except Exception: return QIcon()

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("EnterMedSchool — Glossary Settings")
        self.setMinimumWidth(540)
        self.setWindowIcon(_ensure_logo_icon())
        self._cfg = get_config()

        lay = QVBoxLayout(self)
        header = QHBoxLayout()
        logo = QLabel(f"<img width=24 height=24 src='/_addons/{mw.addonManager.addonFromModule(MODULE)}/web/ems_logo.png'>")
        title = QLabel("<b>EnterMedSchool — Glossary Settings</b>")
        header.addWidget(logo); header.addWidget(title); header.addStretch(1)
        lay.addLayout(header)

        self._section(lay, "Typography & Size")
        self.widthSB = self._spin_row(lay, "Popup width (px)", 360, 900, "tooltip_width_px")
        self.fontSB = self._spin_row(lay, "Popup font size (px)", 12, 22, "popup_font_px")

        self._section(lay, "Behavior")
        self.hoverModeCB = self._combo_row(lay, "Open mode", ["hover","click"], "hover_mode")
        self.hoverDelaySB = self._spin_row(lay, "Hover delay (ms)", 0, 800, "hover_delay_ms")
        self.maxHL = self._spin_row(lay, "Max highlights per card", 5, 200, "max_highlights")
        self.clickAnyCB = QCheckBox("Clicking a term opens immediately")
        self.clickAnyCB.setChecked(bool(self._cfg.get("open_with_click_anywhere", True)))
        lay.addWidget(self.clickAnyCB)

        self._section(lay, "Field scanning & Mute tags")
        self.scanFieldsLE = QLineEdit(self._cfg.get("scan_fields","Front,Back,Extra"))
        lay2 = QHBoxLayout(); lay2.addWidget(QLabel("Fields (comma-separated):")); lay2.addWidget(self.scanFieldsLE,1); lay.addLayout(lay2)
        self.muteTagsLE = QLineEdit(self._cfg.get("mute_tags",""))
        lay3 = QHBoxLayout(); lay3.addWidget(QLabel("Mute tags (comma-separated):")); lay3.addWidget(self.muteTagsLE,1); lay.addLayout(lay3)

        self._section(lay, "Learning Cards")
        self.learnTargetCB = self._combo_row(lay, "Send new cards to…", ["dedicated","current"], "learn_target")
        self.deckLE = QLineEdit(self._cfg.get("learn_deck_name","EnterMedSchool — Terms"))
        lay4 = QHBoxLayout(); lay4.addWidget(QLabel("Dedicated deck name:")); lay4.addWidget(self.deckLE,1); lay.addLayout(lay4)

        btns = QHBoxLayout()
        save = QPushButton("Save"); reset = QPushButton("Reset"); close = QPushButton("Close")
        btns.addStretch(1); btns.addWidget(reset); btns.addWidget(save); btns.addWidget(close)
        lay.addLayout(btns)

        save.clicked.connect(self._on_save)
        reset.clicked.connect(self._on_reset)
        close.clicked.connect(self.close)

    def _section(self, lay, text):
        w = QLabel(text); w.setStyleSheet("margin-top:10px;margin-bottom:4px;font-weight:600;"); lay.addWidget(w)
    def _combo_row(self, lay, label, items, key):
        row = QHBoxLayout(); lab = QLabel(label); cb = QComboBox(); cb.addItems(items)
        val = self._cfg.get(key, items[0])
        if val in items: cb.setCurrentText(val)
        row.addWidget(lab); row.addWidget(cb,1); lay.addLayout(row); return cb
    def _spin_row(self, lay, label, lo, hi, key):
        row = QHBoxLayout(); lab = QLabel(label); sb = QSpinBox(); sb.setRange(lo,hi); sb.setValue(int(self._cfg.get(key, lo)))
        row.addWidget(lab); row.addWidget(sb,1); lay.addLayout(row); return sb

    def _on_save(self):
        cfg = get_config()
        cfg["tooltip_width_px"] = int(self.widthSB.value())
        cfg["popup_font_px"] = int(self.fontSB.value())
        cfg["hover_mode"] = self.hoverModeCB.currentText()
        cfg["hover_delay_ms"] = int(self.hoverDelaySB.value())
        cfg["max_highlights"] = int(self.maxHL.value())
        cfg["open_with_click_anywhere"] = bool(self.clickAnyCB.isChecked())
        cfg["scan_fields"] = self.scanFieldsLE.text().strip()
        cfg["mute_tags"] = self.muteTagsLE.text().strip()
        cfg["learn_target"] = self.learnTargetCB.currentText()
        cfg["learn_deck_name"] = self.deckLE.text().strip() or "EnterMedSchool — Terms"
        write_config(cfg); showInfo("Saved. ?")
        try:
            LOG.log("ui.appearance.save", cfg_keys=list(cfg.keys()))
        except Exception:
            pass

    def _on_reset(self):
        cfg = get_config()
        for k, v in DEFAULT_CONFIG.items():
            if k == "last_update_check": continue
            cfg[k] = v
        write_config(cfg); showInfo("Reset to defaults.")
        try:
            LOG.log("ui.appearance.reset")
        except Exception:
            pass

    # ------ Live preview helpers (class-scoped) ------
    def _connect_preview_signals(self):
        self.presetCB.currentTextChanged.connect(lambda *_: self._apply_preset(self.presetCB.currentText()))
        for sb in [self.widthSB, self.fontSB, self.radiusSB]:
            sb.valueChanged.connect(self._render_popup_preview)
        for le in [self.popupBgLE, self.popupFgLE, self.popupMutedLE, self.popupBorderLE, self.popupAccentLE, self.popupAccent2LE]:
            le.textChanged.connect(self._render_popup_preview)
        self.popupCssTE.textChanged.connect(self._render_popup_preview)
        self.copyPopupCssBtn.clicked.connect(self._copy_popup_css)
        self.resetPopupBtn.clicked.connect(self._reset_popup_section)
        for le in [self.uiBgLE, self.uiFgLE, self.uiAccentLE, self.uiCtrlBgLE, self.uiCtrlBorderLE, self.uiBtnBgLE, self.uiBtnBorderLE]:
            le.textChanged.connect(self._render_ui_preview)
        self.uiCssTE.textChanged.connect(self._render_ui_preview)
        self.resetUiBtn.clicked.connect(self._reset_ui_section)

    def _popup_vars(self) -> dict:
        return {
            "bg": (self.popupBgLE.text() or DEFAULT_CONFIG["popup_bg"]).strip(),
            "fg": (self.popupFgLE.text() or DEFAULT_CONFIG["popup_fg"]).strip(),
            "muted": (self.popupMutedLE.text() or DEFAULT_CONFIG["popup_muted"]).strip(),
            "border": (self.popupBorderLE.text() or DEFAULT_CONFIG["popup_border"]).strip(),
            "accent": (self.popupAccentLE.text() or DEFAULT_CONFIG["popup_accent"]).strip(),
            "accent2": (self.popupAccent2LE.text() or DEFAULT_CONFIG["popup_accent2"]).strip(),
            "radius": int(self.radiusSB.value()),
            "width": int(self.widthSB.value()),
            "font": int(self.fontSB.value()),
            "extra": self.popupCssTE.toPlainText(),
        }

    def _render_popup_preview(self):
        vars = self._popup_vars()
        pkg = mw.addonManager.addonFromModule(MODULE)
        page = f"""
<!doctype html>
<html>
  <head>
    <meta charset='utf-8'>
    <link rel='stylesheet' href='/_addons/{pkg}/web/popup.css'>
    <style>
      :root{{
        --ems-bg:{vars['bg']}; --ems-fg:{vars['fg']}; --ems-muted:{vars['muted']};
        --ems-border:{vars['border']}; --ems-accent:{vars['accent']}; --ems-accent-2:{vars['accent2']}; --ems-radius:{vars['radius']}px;
      }}
      .ems-popover{{ max-width:{vars['width']}px; font-size:{vars['font']}px; position:relative; left:auto; top:auto; transform:none; margin:8px auto; }}
      body{{ background:#0f121a; color:#edf1f7; margin:0; padding:8px; }}
      {vars['extra']}
    </style>
  </head>
  <body>
    <div class='ems-popover'>
      <div class='ems-topbar'>
        <span class='ems-pill'><span class='i'>?</span> Sample</span>
        <button class='ems-iconbtn'>i</button>
      </div>
      <div class='ems-body'>
        <div class='ems-content'>
          <h3>Sample Term</h3>
          <p class='ems-lead'>Concise definition preview with your styles.</p>
          <div class='ems-section'>
            <h4>Bullets</h4>
            <ul><li>First point</li><li>Second point</li></ul>
          </div>
        </div>
      </div>
      <div class='ems-brand'><div class='ems-brand-inner'><span class='ems-brand-name'>EnterMedSchool</span></div></div>
    </div>
  </body>
 </html>
        """
        # Update hidden inline preview (fallback)
        try:
            if getattr(self, "popupPreview", None) and hasattr(self.popupPreview, "stdHtml"):
                self.popupPreview.stdHtml(page)
        except Exception:
            try:
                if getattr(self, "popupPreview", None):
                    self.popupPreview.setHtml(page)
            except Exception:
                pass
        # Update floating preview window
        try:
            if getattr(self, "previewWin", None) and hasattr(self.previewWin, "web"):
                try:
                    self.previewWin.web.stdHtml(page)
                except Exception:
                    self.previewWin.web.setHtml(page)
        except Exception:
            pass

    def _ui_style(self) -> str:
        bg = (self.uiBgLE.text() or DEFAULT_CONFIG["ui_bg"]).strip()
        fg = (self.uiFgLE.text() or DEFAULT_CONFIG["ui_fg"]).strip()
        ac = (self.uiAccentLE.text() or DEFAULT_CONFIG["ui_accent"]).strip()
        cbg = (self.uiCtrlBgLE.text() or DEFAULT_CONFIG["ui_control_bg"]).strip()
        cbrd = (self.uiCtrlBorderLE.text() or DEFAULT_CONFIG["ui_control_border"]).strip()
        bbg = (self.uiBtnBgLE.text() or DEFAULT_CONFIG["ui_button_bg"]).strip()
        bbrd = (self.uiBtnBorderLE.text() or DEFAULT_CONFIG["ui_button_border"]).strip()
        extra = self.uiCssTE.toPlainText() or ""
        style = (
            f"QWidget{{background:{bg};color:{fg};}}"
            f"QLabel{{color:{fg};}}"
            f"QLineEdit,QPlainTextEdit,QComboBox{{background:{cbg};color:{fg};border:1px solid {cbrd};border-radius:10px;padding:6px 8px;}}"
            f"QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus{{border:1px solid {ac};}}"
            f"QPushButton{{background:{bbg};color:#fff;border:1px solid {bbrd};border-radius:10px;padding:8px 12px;font-weight:700;}}"
            f"QPushButton:hover{{filter:brightness(1.05);}}"
        )
        return style + extra

    def _render_ui_preview(self):
        try:
            self.uiPreview.setStyleSheet(self._ui_style())
        except Exception:
            pass

    def _copy_popup_css(self):
        vars = self._popup_vars()
        css = (
            ":root{\n"
            f"  --ems-bg: {vars['bg']};\n"
            f"  --ems-fg: {vars['fg']};\n"
            f"  --ems-muted: {vars['muted']};\n"
            f"  --ems-border: {vars['border']};\n"
            f"  --ems-accent: {vars['accent']};\n"
            f"  --ems-accent-2: {vars['accent2']};\n"
            f"  --ems-radius: {vars['radius']}px;\n"
            "}\n"
        )
        try:
            showText(css, title="Popup CSS Variables")
        except Exception:
            pass

    def _reset_popup_section(self):
        try:
            self.widthSB.setValue(DEFAULT_CONFIG.get("tooltip_width_px", 640))
            self.fontSB.setValue(DEFAULT_CONFIG.get("popup_font_px", 16))
            self.radiusSB.setValue(DEFAULT_CONFIG.get("popup_radius_px", 14))
            self.popupBgLE.setText(DEFAULT_CONFIG.get("popup_bg", ""))
            self.popupFgLE.setText(DEFAULT_CONFIG.get("popup_fg", ""))
            self.popupMutedLE.setText(DEFAULT_CONFIG.get("popup_muted", ""))
            self.popupBorderLE.setText(DEFAULT_CONFIG.get("popup_border", ""))
            self.popupAccentLE.setText(DEFAULT_CONFIG.get("popup_accent", ""))
            self.popupAccent2LE.setText(DEFAULT_CONFIG.get("popup_accent2", ""))
            self.popupCssTE.setPlainText(DEFAULT_CONFIG.get("popup_custom_css", ""))
            self._render_popup_preview()
        except Exception:
            pass

    def _reset_ui_section(self):
        try:
            self.uiBgLE.setText(DEFAULT_CONFIG.get("ui_bg", ""))
            self.uiFgLE.setText(DEFAULT_CONFIG.get("ui_fg", ""))
            self.uiAccentLE.setText(DEFAULT_CONFIG.get("ui_accent", ""))
            self.uiCtrlBgLE.setText(DEFAULT_CONFIG.get("ui_control_bg", ""))
            self.uiCtrlBorderLE.setText(DEFAULT_CONFIG.get("ui_control_border", ""))
            self.uiBtnBgLE.setText(DEFAULT_CONFIG.get("ui_button_bg", ""))
            self.uiBtnBorderLE.setText(DEFAULT_CONFIG.get("ui_button_border", ""))
            self.uiCssTE.setPlainText(DEFAULT_CONFIG.get("ui_custom_css", ""))
            self._render_ui_preview()
        except Exception:
            pass

    def _apply_preset(self, name: str):
        try:
            n = (name or "").strip().lower()
            def slug(s: str) -> str:
                s = (s or "").lower()
                if "default" in s: return "default"
                if "solarized" in s and "light" in s: return "solarized-light"
                if "solarized" in s: return "solarized-dark"
                if "high" in s and "contrast" in s: return "high-contrast"
                if "retro" in s or "bios" in s: return "retro-bios"
                if "vintage" in s or "beige" in s: return "vintage-beige"
                if "modern" in s or "slate" in s: return "modern-slate"
                if "terminal" in s or "mono" in s: return "terminal-mono"
                for k in ["light","violet","cyan","emerald","dracula"]:
                    if k in s: return k
                return "default"

            presets = {
                "default": dict(bg="#0f121a", fg="#edf1f7", muted="#a4afbf", border="rgba(255,255,255,.10)", ac="#8b5cf6", ac2="#06b6d4", radius=14, css="", ftitle="'Baloo 2'", fbody="'Montserrat'", furl=DEFAULT_CONFIG.get("font_url","")),
                "light":   dict(bg="#ffffff", fg="#0f121a", muted="#4b5563", border="rgba(0,0,0,.12)", ac="#2563eb", ac2="#06b6d4", radius=14, css="", ftitle="'Inter'", fbody="'Inter'", furl="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap"),
                "high-contrast": dict(bg="#000000", fg="#ffffff", muted="#e5e7eb", border="#ffffff", ac="#ff006e", ac2="#ffd60a", radius=14, css="", ftitle="'Roboto'", fbody="'Roboto'", furl="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap"),
                "violet":  dict(bg="#0f121a", fg="#edf1f7", muted="#a4afbf", border="rgba(255,255,255,.15)", ac="#8b5cf6", ac2="#22d3ee", radius=14, css="", ftitle="'Baloo 2'", fbody="'Montserrat'", furl=DEFAULT_CONFIG.get("font_url","")),
                "cyan":    dict(bg="#0f121a", fg="#e6fbff", muted="#9adbe1", border="rgba(6,182,212,.35)", ac="#06b6d4", ac2="#60a5fa", radius=14, css="", ftitle="'Poppins'", fbody="'Poppins'", furl="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap"),
                "solarized-dark": dict(bg="#002b36", fg="#eee8d5", muted="#93a1a1", border="#073642", ac="#b58900", ac2="#268bd2", radius=14, css="", ftitle="'Roboto Slab'", fbody="'Source Sans 3'", furl="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap"),
                "solarized-light": dict(bg="#fdf6e3", fg="#073642", muted="#657b83", border="#eee8d5", ac="#268bd2", ac2="#2aa198", radius=14, css="", ftitle="'Roboto Slab'", fbody="'Source Sans 3'", furl="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap"),
                "vintage-beige": dict(bg="#f6edd9", fg="#2b2b2b", muted="#6b5e4a", border="rgba(0,0,0,.18)", ac="#a67c52", ac2="#d4a373", radius=10, css=".ems-lead{background:linear-gradient(180deg,#f3e9ce,#f0e2bf);border-color:rgba(0,0,0,.18);} .ems-pill{box-shadow:none;border-color:#a67c52;}", ftitle="'Special Elite'", fbody="'Lora'", furl="https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&family=Special+Elite&display=swap"),
                "cute-pink": dict(bg="#fff1f5", fg="#4a1d2a", muted="#9d4b73", border="#f8b4d9", ac="#ec4899", ac2="#f472b6", radius=14, css="", ftitle="'Nunito'", fbody="'Nunito'", furl="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap"),
                "modern-slate": dict(bg="#0f172a", fg="#e5e7eb", muted="#94a3b8", border="rgba(148,163,184,.35)", ac="#6366f1", ac2="#06b6d4", radius=14, css="", ftitle="'Inter'", fbody="'Inter'", furl="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap"),
                "emerald": dict(bg="#081c15", fg="#d8f3dc", muted="#74c69d", border="#1b4332", ac="#2d6a4f", ac2="#40916c", radius=14, css="", ftitle="'Urbanist'", fbody="'Inter'", furl="https://fonts.googleapis.com/css2?family=Urbanist:wght@700&family=Inter:wght@400;600&display=swap"),
                "dracula": dict(bg="#282a36", fg="#f8f8f2", muted="#b6b7c2", border="#44475a", ac="#bd93f9", ac2="#50fa7b", radius=14, css="", ftitle="'Rubik'", fbody="'Rubik'", furl="https://fonts.googleapis.com/css2?family=Rubik:wght@400;600;800&display=swap"),
                "retro-bios": dict(
                    bg="#001b00", fg="#99ff99", muted="#66cc66", border="#1a3d1a", ac="#00ff66", ac2="#39ff14", radius=2,
                    css="*{letter-spacing:0.3px;} .ems-popover{border-radius:2px;box-shadow:none;} .ems-body, .ems-content, .ems-popover{font-family: 'IBM Plex Mono', monospace !important;} .ems-popover::after{content:'';position:absolute;inset:0;background:repeating-linear-gradient(transparent,transparent 1px,rgba(0,255,128,.06) 2px,rgba(0,255,128,.06) 3px);pointer-events:none;} .ems-pill{background:transparent;border-color:#00ff66;color:#99ff99;} .ems-section{border-color:#00ff66;} .ems-lead{background:rgba(0,255,102,.06);border-color:#00ff66;}",
                    ftitle="'IBM Plex Mono'", fbody="'IBM Plex Mono'",
                    furl="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&display=swap"
                ),
                "terminal-mono": dict(bg="#111111", fg="#d1fae5", muted="#86efac", border="#22c55e", ac="#22c55e", ac2="#14b8a6", radius=14, css="", ftitle="'VT323'", fbody="'IBM Plex Mono'", furl="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=VT323&display=swap"),
            }

            key = slug(n)
            p = presets.get(key)
            if not p:
                self._reset_popup_section(); self._reset_ui_section()
            else:
                self.popupBgLE.setText(p["bg"]) ; self.popupFgLE.setText(p["fg"]) ; self.popupMutedLE.setText(p["muted"]) ; self.popupBorderLE.setText(p["border"]) ; self.popupAccentLE.setText(p["ac"]) ; self.popupAccent2LE.setText(p["ac2"]) ; self.radiusSB.setValue(int(p.get("radius",14)))
                self.fontTitleLE.setText(p["ftitle"]) ; self.fontBodyLE.setText(p["fbody"]) ; self.fontUrlLE.setText(p.get("furl",""))
                if p.get("css") is not None:
                    self.popupCssTE.setPlainText(p.get("css",""))
            self._render_popup_preview(); self._render_ui_preview()
        except Exception:
            pass

    # ------ Live preview helpers ------
    def _connect_preview_signals(self):
        # Popup inputs
        self.presetCB.currentTextChanged.connect(lambda *_: self._apply_preset(self.presetCB.currentText()))
        for sb in [self.widthSB, self.fontSB, self.radiusSB]:
            sb.valueChanged.connect(self._render_popup_preview)
        for le in [self.popupBgLE, self.popupFgLE, self.popupMutedLE, self.popupBorderLE, self.popupAccentLE, self.popupAccent2LE]:
            le.textChanged.connect(self._render_popup_preview)
        self.popupCssTE.textChanged.connect(self._render_popup_preview)
        self.copyPopupCssBtn.clicked.connect(self._copy_popup_css)
        self.resetPopupBtn.clicked.connect(self._reset_popup_section)
        # UI inputs
        for le in [self.uiBgLE, self.uiFgLE, self.uiAccentLE, self.uiCtrlBgLE, self.uiCtrlBorderLE, self.uiBtnBgLE, self.uiBtnBorderLE]:
            le.textChanged.connect(self._render_ui_preview)
        self.uiCssTE.textChanged.connect(self._render_ui_preview)
        self.resetUiBtn.clicked.connect(self._reset_ui_section)

    def _popup_vars(self) -> dict:
        return {
            "bg": (self.popupBgLE.text() or DEFAULT_CONFIG["popup_bg"]).strip(),
            "fg": (self.popupFgLE.text() or DEFAULT_CONFIG["popup_fg"]).strip(),
            "muted": (self.popupMutedLE.text() or DEFAULT_CONFIG["popup_muted"]).strip(),
            "border": (self.popupBorderLE.text() or DEFAULT_CONFIG["popup_border"]).strip(),
            "accent": (self.popupAccentLE.text() or DEFAULT_CONFIG["popup_accent"]).strip(),
            "accent2": (self.popupAccent2LE.text() or DEFAULT_CONFIG["popup_accent2"]).strip(),
            "radius": int(self.radiusSB.value()),
            "width": int(self.widthSB.value()),
            "font": int(self.fontSB.value()),
            "extra": self.popupCssTE.toPlainText(),
        }

    def _render_popup_preview(self):
        if not getattr(self, "popupPreview", None) or not hasattr(self.popupPreview, "stdHtml"):
            return
        vars = self._popup_vars()
        pkg = mw.addonManager.addonFromModule(MODULE)
        page = f"""
<!doctype html>
<html>
  <head>
    <meta charset='utf-8'>
    <link rel='stylesheet' href='/_addons/{pkg}/web/popup.css'>
    <style>
      :root{{
        --ems-bg:{vars['bg']}; --ems-fg:{vars['fg']}; --ems-muted:{vars['muted']};
        --ems-border:{vars['border']}; --ems-accent:{vars['accent']}; --ems-accent-2:{vars['accent2']}; --ems-radius:{vars['radius']}px;
      }}
      .ems-popover{{ max-width:{vars['width']}px; font-size:{vars['font']}px; position:relative; left:auto; top:auto; transform:none; margin:8px auto; }}
      body{{ background:#0f121a; color:#edf1f7; margin:0; padding:8px; }}
      {vars['extra']}
    </style>
  </head>
  <body>
    <div class='ems-popover'>
      <div class='ems-topbar'>
        <span class='ems-pill'><span class='i'>?</span> Sample</span>
        <button class='ems-iconbtn'>i</button>
      </div>
      <div class='ems-body'>
        <div class='ems-content'>
          <h3>Sample Term</h3>
          <p class='ems-lead'>Concise definition preview with your styles.</p>
          <div class='ems-section'>
            <h4>Bullets</h4>
            <ul><li>First point</li><li>Second point</li></ul>
          </div>
        </div>
      </div>
      <div class='ems-brand'><div class='ems-brand-inner'><span class='ems-brand-name'>EnterMedSchool</span></div></div>
    </div>
  </body>
 </html>
        """
        try:
            self.popupPreview.stdHtml(page)
        except Exception:
            try:
                self.popupPreview.setHtml(page)
            except Exception:
                pass

    def _ui_style(self) -> str:
        bg = (self.uiBgLE.text() or DEFAULT_CONFIG["ui_bg"]).strip()
        fg = (self.uiFgLE.text() or DEFAULT_CONFIG["ui_fg"]).strip()
        ac = (self.uiAccentLE.text() or DEFAULT_CONFIG["ui_accent"]).strip()
        cbg = (self.uiCtrlBgLE.text() or DEFAULT_CONFIG["ui_control_bg"]).strip()
        cbrd = (self.uiCtrlBorderLE.text() or DEFAULT_CONFIG["ui_control_border"]).strip()
        bbg = (self.uiBtnBgLE.text() or DEFAULT_CONFIG["ui_button_bg"]).strip()
        bbrd = (self.uiBtnBorderLE.text() or DEFAULT_CONFIG["ui_button_border"]).strip()
        extra = self.uiCssTE.toPlainText() or ""
        style = (
            f"QWidget{{background:{bg};color:{fg};}}"
            f"QLabel{{color:{fg};}}"
            f"QLineEdit,QPlainTextEdit,QComboBox{{background:{cbg};color:{fg};border:1px solid {cbrd};border-radius:10px;padding:6px 8px;}}"
            f"QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus{{border:1px solid {ac};}}"
            f"QPushButton{{background:{bbg};color:#fff;border:1px solid {bbrd};border-radius:10px;padding:8px 12px;font-weight:700;}}"
            f"QPushButton:hover{{filter:brightness(1.05);}}"
        )
        return style + extra

    def _render_ui_preview(self):
        try:
            self.uiPreview.setStyleSheet(self._ui_style())
        except Exception:
            pass

    def _copy_popup_css(self):
        vars = self._popup_vars()
        css = (
            ":root{\n"
            f"  --ems-bg: {vars['bg']};\n"
            f"  --ems-fg: {vars['fg']};\n"
            f"  --ems-muted: {vars['muted']};\n"
            f"  --ems-border: {vars['border']};\n"
            f"  --ems-accent: {vars['accent']};\n"
            f"  --ems-accent-2: {vars['accent2']};\n"
            f"  --ems-radius: {vars['radius']}px;\n"
            "}\n"
        )
        try:
            showText(css, title="Popup CSS Variables")
        except Exception:
            pass

    def _reset_popup_section(self):
        try:
            self.widthSB.setValue(DEFAULT_CONFIG.get("tooltip_width_px", 640))
            self.fontSB.setValue(DEFAULT_CONFIG.get("popup_font_px", 16))
            self.radiusSB.setValue(DEFAULT_CONFIG.get("popup_radius_px", 14))
            self.popupBgLE.setText(DEFAULT_CONFIG.get("popup_bg", ""))
            self.popupFgLE.setText(DEFAULT_CONFIG.get("popup_fg", ""))
            self.popupMutedLE.setText(DEFAULT_CONFIG.get("popup_muted", ""))
            self.popupBorderLE.setText(DEFAULT_CONFIG.get("popup_border", ""))
            self.popupAccentLE.setText(DEFAULT_CONFIG.get("popup_accent", ""))
            self.popupAccent2LE.setText(DEFAULT_CONFIG.get("popup_accent2", ""))
            self.popupCssTE.setPlainText(DEFAULT_CONFIG.get("popup_custom_css", ""))
            self._render_popup_preview()
        except Exception:
            pass

    def _reset_ui_section(self):
        try:
            self.uiBgLE.setText(DEFAULT_CONFIG.get("ui_bg", ""))
            self.uiFgLE.setText(DEFAULT_CONFIG.get("ui_fg", ""))
            self.uiAccentLE.setText(DEFAULT_CONFIG.get("ui_accent", ""))
            self.uiCtrlBgLE.setText(DEFAULT_CONFIG.get("ui_control_bg", ""))
            self.uiCtrlBorderLE.setText(DEFAULT_CONFIG.get("ui_control_border", ""))
            self.uiBtnBgLE.setText(DEFAULT_CONFIG.get("ui_button_bg", ""))
            self.uiBtnBorderLE.setText(DEFAULT_CONFIG.get("ui_button_border", ""))
            self.uiCssTE.setPlainText(DEFAULT_CONFIG.get("ui_custom_css", ""))
            self._render_ui_preview()
        except Exception:
            pass

    def _apply_preset(self, name: str):
        try:
            n = (name or "").lower()
            try:
                LOG.log("ui.appearance.preset", preset=n)
            except Exception:
                pass
            if "light" in n:
                self.popupBgLE.setText("#ffffff"); self.popupFgLE.setText("#0f121a"); self.popupMutedLE.setText("#4b5563"); self.popupBorderLE.setText("rgba(0,0,0,.12)"); self.popupAccentLE.setText("#2563eb"); self.popupAccent2LE.setText("#06b6d4")
                self.uiBgLE.setText("#f7fafc"); self.uiFgLE.setText("#111827"); self.uiAccentLE.setText("#2563eb"); self.uiCtrlBgLE.setText("#ffffff"); self.uiCtrlBorderLE.setText("rgba(0,0,0,.16)"); self.uiBtnBgLE.setText("#2563eb"); self.uiBtnBorderLE.setText("#60a5fa")
                self.fontTitleLE.setText("'Inter'"); self.fontBodyLE.setText("'Inter'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap")
            elif "contrast" in n or "high" in n:
                self.popupBgLE.setText("#000000"); self.popupFgLE.setText("#ffffff"); self.popupMutedLE.setText("#e5e7eb"); self.popupBorderLE.setText("#ffffff"); self.popupAccentLE.setText("#ff006e"); self.popupAccent2LE.setText("#ffd60a")
                self.uiBgLE.setText("#000000"); self.uiFgLE.setText("#ffffff"); self.uiAccentLE.setText("#ff006e"); self.uiCtrlBgLE.setText("#111111"); self.uiCtrlBorderLE.setText("#ffffff"); self.uiBtnBgLE.setText("#ff006e"); self.uiBtnBorderLE.setText("#ffd60a")
                self.fontTitleLE.setText("'Roboto'"); self.fontBodyLE.setText("'Roboto'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap")
            elif "violet" in n:
                self.popupBgLE.setText("#0f121a"); self.popupFgLE.setText("#edf1f7"); self.popupMutedLE.setText("#a4afbf"); self.popupBorderLE.setText("rgba(255,255,255,.15)"); self.popupAccentLE.setText("#8b5cf6"); self.popupAccent2LE.setText("#22d3ee")
                self.uiBgLE.setText("#0f121a"); self.uiFgLE.setText("#edf1f7"); self.uiAccentLE.setText("#8b5cf6"); self.uiBtnBgLE.setText("#7c3aed"); self.uiBtnBorderLE.setText("#a78bfa")
                self.fontTitleLE.setText("'Baloo 2'"); self.fontBodyLE.setText("'Montserrat'"); self.fontUrlLE.setText(DEFAULT_CONFIG.get("font_url",""))
            elif "cyan" in n:
                self.popupBgLE.setText("#0f121a"); self.popupFgLE.setText("#e6fbff"); self.popupMutedLE.setText("#9adbe1"); self.popupBorderLE.setText("rgba(6,182,212,.35)"); self.popupAccentLE.setText("#06b6d4"); self.popupAccent2LE.setText("#60a5fa")
                self.uiBgLE.setText("#0f121a"); self.uiFgLE.setText("#e6fbff"); self.uiAccentLE.setText("#06b6d4"); self.uiBtnBgLE.setText("#06b6d4"); self.uiBtnBorderLE.setText("#67e8f9")
                self.fontTitleLE.setText("'Poppins'"); self.fontBodyLE.setText("'Poppins'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap")
            elif "solarized" in n and "light" in n:
                self.popupBgLE.setText("#fdf6e3"); self.popupFgLE.setText("#073642"); self.popupMutedLE.setText("#657b83"); self.popupBorderLE.setText("#eee8d5"); self.popupAccentLE.setText("#268bd2"); self.popupAccent2LE.setText("#2aa198")
                self.fontTitleLE.setText("'Roboto Slab'"); self.fontBodyLE.setText("'Source Sans 3'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap")
            elif "solarized" in n:
                self.popupBgLE.setText("#002b36"); self.popupFgLE.setText("#eee8d5"); self.popupMutedLE.setText("#93a1a1"); self.popupBorderLE.setText("#073642"); self.popupAccentLE.setText("#b58900"); self.popupAccent2LE.setText("#268bd2")
                self.fontTitleLE.setText("'Roboto Slab'"); self.fontBodyLE.setText("'Source Sans 3'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap")
            elif "vintage" in n or "beige" in n:
                self.popupBgLE.setText("#f6edd9"); self.popupFgLE.setText("#2b2b2b"); self.popupMutedLE.setText("#6b5e4a"); self.popupBorderLE.setText("rgba(0,0,0,.18)"); self.popupAccentLE.setText("#a67c52"); self.popupAccent2LE.setText("#d4a373")
                self.fontTitleLE.setText("'Special Elite'"); self.fontBodyLE.setText("'Lora'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&family=Special+Elite&display=swap")
                self.radiusSB.setValue(10)
                self.popupCssTE.setPlainText(".ems-lead{background:linear-gradient(180deg,#f3e9ce,#f0e2bf);border-color:rgba(0,0,0,.18);} .ems-pill{box-shadow:none;border-color:#a67c52;}")
            elif "pink" in n or "cute" in n:
                self.popupBgLE.setText("#fff1f5"); self.popupFgLE.setText("#4a1d2a"); self.popupMutedLE.setText("#9d4b73"); self.popupBorderLE.setText("#f8b4d9"); self.popupAccentLE.setText("#ec4899"); self.popupAccent2LE.setText("#f472b6")
                self.fontTitleLE.setText("'Nunito'"); self.fontBodyLE.setText("'Nunito'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap")
            elif "modern" in n or "slate" in n:
                self.popupBgLE.setText("#0f172a"); self.popupFgLE.setText("#e5e7eb"); self.popupMutedLE.setText("#94a3b8"); self.popupBorderLE.setText("rgba(148,163,184,.35)"); self.popupAccentLE.setText("#6366f1"); self.popupAccent2LE.setText("#06b6d4")
                self.fontTitleLE.setText("'Inter'"); self.fontBodyLE.setText("'Inter'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap")
            elif "emerald" in n:
                self.popupBgLE.setText("#081c15"); self.popupFgLE.setText("#d8f3dc"); self.popupMutedLE.setText("#74c69d"); self.popupBorderLE.setText("#1b4332"); self.popupAccentLE.setText("#2d6a4f"); self.popupAccent2LE.setText("#40916c")
                self.fontTitleLE.setText("'Urbanist'"); self.fontBodyLE.setText("'Inter'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Urbanist:wght@700&family=Inter:wght@400;600&display=swap")
            elif "dracula" in n:
                self.popupBgLE.setText("#282a36"); self.popupFgLE.setText("#f8f8f2"); self.popupMutedLE.setText("#b6b7c2"); self.popupBorderLE.setText("#44475a"); self.popupAccentLE.setText("#bd93f9"); self.popupAccent2LE.setText("#50fa7b")
                self.fontTitleLE.setText("'Rubik'"); self.fontBodyLE.setText("'Rubik'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=Rubik:wght@400;600;800&display=swap")
            elif "terminal" in n or "mono" in n:
                self.popupBgLE.setText("#111111"); self.popupFgLE.setText("#d1fae5"); self.popupMutedLE.setText("#86efac"); self.popupBorderLE.setText("#22c55e"); self.popupAccentLE.setText("#22c55e"); self.popupAccent2LE.setText("#14b8a6")
                self.fontTitleLE.setText("'VT323'"); self.fontBodyLE.setText("'IBM Plex Mono'"); self.fontUrlLE.setText("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=VT323&display=swap")
            else:
                # default (dark)
                self._reset_popup_section(); self._reset_ui_section()
            self._render_popup_preview(); self._render_ui_preview()
        except Exception:
            pass

# New unified appearance dialog (replaces the legacy settings UI)
class AppearanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("EMS - Appearance & Settings")
        self.setMinimumWidth(620)
        self.setWindowIcon(_ensure_logo_icon())
        self._cfg = get_config()

        lay = QVBoxLayout(self)
        header = QHBoxLayout()
        logo = QLabel(f"<img width=24 height=24 src='/_addons/{mw.addonManager.addonFromModule(MODULE)}/web/ems_logo.png'>")
        title = QLabel("<b>Appearance & Settings</b>")
        header.addWidget(logo); header.addWidget(title); header.addStretch(1)
        lay.addLayout(header)

        tabs = QTabWidget(self); lay.addWidget(tabs, 1)

        # Popup tab
        popupW = QWidget(); popupL = QVBoxLayout(popupW)
        self._section(popupL, "Theme Preset")
        rowPreset = QHBoxLayout(); self.presetCB = QComboBox(); self.presetCB.addItems([
            "Default (Dark)",
            "Light",
            "High Contrast",
            "Violet",
            "Cyan",
            "Solarized Dark",
            "Solarized Light",
            "Vintage Beige",
            "Retro BIOS",
            "Estella's Pink",
            "Modern Slate",
            "Emerald",
            "Dracula",
            "Terminal Mono"
        ])
        rowPreset.addWidget(QLabel("Preset:")); rowPreset.addWidget(self.presetCB, 1)
        popupL.addLayout(rowPreset)

        self._section(popupL, "Popup Size")
        self.widthSB = self._spin_row(popupL, "Max width (px)", 360, 1200, "tooltip_width_px")
        self.fontSB = self._spin_row(popupL, "Base font size (px)", 10, 28, "popup_font_px")
        self._section(popupL, "Popup Colors & Corners")
        self.popupBgLE = self._color_row(popupL, "Background", "popup_bg")
        self.popupFgLE = self._color_row(popupL, "Text", "popup_fg")
        self.popupMutedLE = self._color_row(popupL, "Muted text", "popup_muted")
        self.popupBorderLE = self._color_row(popupL, "Border", "popup_border")
        self.popupAccentLE = self._color_row(popupL, "Accent", "popup_accent")
        self.popupAccent2LE = self._color_row(popupL, "Accent 2", "popup_accent2")
        self.radiusSB = self._spin_row(popupL, "Corner radius (px)", 0, 30, "popup_radius_px")

        self._section(popupL, "Fonts")
        rowFT = QHBoxLayout(); rowFT.addWidget(QLabel("Title font:")); self.fontTitleLE = QLineEdit(self._cfg.get("font_title", "'Baloo 2'")); rowFT.addWidget(self.fontTitleLE, 1); popupL.addLayout(rowFT)
        rowFB = QHBoxLayout(); rowFB.addWidget(QLabel("Body font:")); self.fontBodyLE = QLineEdit(self._cfg.get("font_body", "'Montserrat'")); rowFB.addWidget(self.fontBodyLE, 1); popupL.addLayout(rowFB)
        rowFU = QHBoxLayout(); rowFU.addWidget(QLabel("Font CSS URL:")); self.fontUrlLE = QLineEdit(self._cfg.get("font_url", "")); rowFU.addWidget(self.fontUrlLE, 1); popupL.addLayout(rowFU)
        self._section(popupL, "Extra CSS for popup (optional)")
        self.popupCssTE = QPlainTextEdit(self._cfg.get("popup_custom_css", ""))
        self.popupCssTE.setPlaceholderText("/* Any extra CSS here will apply to the popup */")
        popupL.addWidget(self.popupCssTE)

        # Popup live preview (uses the real popup.css and injected CSS vars)
        self._section(popupL, "Live Preview")
        self.popupPreview = AnkiWebView(self)
        popupL.addWidget(self.popupPreview, 1)
        # We'll render in a separate window; hide the inline one by default
        try:
            self.popupPreview.setVisible(False)
        except Exception:
            pass

        # Popup actions
        rowActions = QHBoxLayout(); rowActions.addStretch(1)
        self.copyPopupCssBtn = QPushButton("Copy Popup CSS")
        self.resetPopupBtn = QPushButton("Reset Popup")
        rowActions.addWidget(self.resetPopupBtn)
        rowActions.addWidget(self.copyPopupCssBtn)
        popupL.addLayout(rowActions)

        tabs.addTab(popupW, "Popup")

        # Dialogs tab (Suggest/Editors)
        uiW = QWidget(); uiL = QVBoxLayout(uiW)
        self._section(uiL, "Dialog Theme")
        self.uiBgLE = self._color_row(uiL, "Background", "ui_bg")
        self.uiFgLE = self._color_row(uiL, "Text", "ui_fg")
        self.uiAccentLE = self._color_row(uiL, "Accent", "ui_accent")
        self.uiCtrlBgLE = self._color_row(uiL, "Control background", "ui_control_bg")
        self.uiCtrlBorderLE = self._color_row(uiL, "Control border", "ui_control_border")
        self.uiBtnBgLE = self._color_row(uiL, "Button background", "ui_button_bg")
        self.uiBtnBorderLE = self._color_row(uiL, "Button border", "ui_button_border")
        self._section(uiL, "Extra CSS for dialogs (optional)")
        self.uiCssTE = QPlainTextEdit(self._cfg.get("ui_custom_css", ""))
        self.uiCssTE.setPlaceholderText("/* Applies to settings/editor dialogs */")
        uiL.addWidget(self.uiCssTE)

        # UI live preview panel
        self._section(uiL, "Live Preview")
        self.uiPreview = QWidget(); uiPrevLay = QVBoxLayout(self.uiPreview)
        uiPrevLay.addWidget(QLabel("Sample label"))
        uiPrevLay.addWidget(QLineEdit("Sample single-line input"))
        cbrow = QHBoxLayout(); cbrow.addWidget(QLabel("Sample dropdown:")); _cb = QComboBox(); _cb.addItems(["One","Two","Three"]); cbrow.addWidget(_cb, 1)
        uiPrevLay.addLayout(cbrow)
        uiPrevLay.addWidget(QPlainTextEdit("Sample multi-line text\nSecond line"))
        btnrow = QHBoxLayout(); btnrow.addWidget(QPushButton("Primary")); btnrow.addWidget(QPushButton("Secondary")); btnrow.addStretch(1)
        uiPrevLay.addLayout(btnrow)
        uiL.addWidget(self.uiPreview, 1)

        # UI actions
        rowUIActions = QHBoxLayout(); rowUIActions.addStretch(1)
        self.resetUiBtn = QPushButton("Reset Dialogs")
        rowUIActions.addWidget(self.resetUiBtn)
        uiL.addLayout(rowUIActions)

        tabs.addTab(uiW, "Dialogs")

        # Behavior tab
        behW = QWidget(); behL = QVBoxLayout(behW)
        self._section(behL, "Hover & Click Behavior")
        self.hoverModeCB = QComboBox(); self.hoverModeCB.addItems(["hover","click"])
        val = str(self._cfg.get("hover_mode", "click"))
        if val in ("hover","click"): self.hoverModeCB.setCurrentText(val)
        row = QHBoxLayout(); row.addWidget(QLabel("Open mode:")); row.addWidget(self.hoverModeCB,1); behL.addLayout(row)
        self.hoverDelaySB = self._spin_row(behL, "Hover delay (ms)", 0, 1200, "hover_delay_ms")
        self.maxHL = self._spin_row(behL, "Max highlights per card", 5, 1000, "max_highlights")
        self.clickAnyCB = QCheckBox("Clicking a term opens immediately")
        self.clickAnyCB.setChecked(bool(self._cfg.get("open_with_click_anywhere", True)))
        behL.addWidget(self.clickAnyCB)
        self._section(behL, "Fields & Mute Tags")
        self.scanFieldsLE = QLineEdit(self._cfg.get("scan_fields","Front,Back,Extra"))
        lay2 = QHBoxLayout(); lay2.addWidget(QLabel("Fields (comma-separated):")); lay2.addWidget(self.scanFieldsLE,1); behL.addLayout(lay2)
        self.muteTagsLE = QLineEdit(self._cfg.get("mute_tags",""))
        lay3 = QHBoxLayout(); lay3.addWidget(QLabel("Mute tags (comma-separated):")); lay3.addWidget(self.muteTagsLE,1); behL.addLayout(lay3)
        self._section(behL, "Learning Cards")
        self.learnTargetCB = QComboBox(); self.learnTargetCB.addItems(["dedicated","current"])
        self.learnTargetCB.setCurrentText(self._cfg.get("learn_target","dedicated"))
        rowL = QHBoxLayout(); rowL.addWidget(QLabel("Send new cards to:")); rowL.addWidget(self.learnTargetCB,1); behL.addLayout(rowL)
        self.deckLE = QLineEdit(self._cfg.get("learn_deck_name","EnterMedSchool - Terms"))
        rowD = QHBoxLayout(); rowD.addWidget(QLabel("Dedicated deck name:")); rowD.addWidget(self.deckLE,1); behL.addLayout(rowD)
        tabs.addTab(behW, "Behavior")

        # Tamagotchi tab
        tamaW = QWidget(); tamaL = QVBoxLayout(tamaW)
        self._section(tamaL, "Tamagotchi Device (Skin)")
        # discover devices
        try:
            devices_dir = os.path.join(ADDON_DIR, "LeoTamagotchi", "Devices")
            dev_files = []
            if os.path.isdir(devices_dir):
                for fn in sorted(os.listdir(devices_dir)):
                    if fn.lower().endswith('.png'):
                        dev_files.append(fn)
        except Exception:
            devices_dir = os.path.join(ADDON_DIR, "LeoTamagotchi", "Devices"); dev_files = []
        rowDev = QHBoxLayout();
        self.deviceCB = QComboBox();
        self.deviceCB.addItem("CleanUI")
        for fn in dev_files:
            self.deviceCB.addItem(os.path.splitext(fn)[0])
        rowDev.addWidget(QLabel("Device:")); rowDev.addWidget(self.deviceCB,1)
        tamaL.addLayout(rowDev)
        # preview
        self.devicePreview = QLabel(" "); self.devicePreview.setMinimumHeight(260)
        try:
            self.devicePreview.setAlignment(Qt.AlignCenter)
        except Exception:
            try:
                # Qt6 style enum location
                self.devicePreview.setAlignment(getattr(Qt, 'AlignmentFlag').AlignCenter)
            except Exception:
                pass
        tamaL.addWidget(self.devicePreview, 1)
        applyBtn = QPushButton("Apply Now")
        tamaL.addWidget(applyBtn)
        tabs.addTab(tamaW, "Tamagotchi")

        # Init device from local state
        try:
            from .LeoTamagotchi.gui import _read_state  # type: ignore
            st = _read_state() or {}
            cur_dev = str(st.get("device","CleanUI") or "CleanUI")
            idx = self.deviceCB.findText(cur_dev if cur_dev.lower() != 'cleanui' else 'CleanUI')
            if idx >= 0: self.deviceCB.setCurrentIndex(idx)
        except Exception:
            pass

        def _render_dev_preview():
            try:
                name = self.deviceCB.currentText().strip()
                if name.lower() == 'cleanui':
                    path = os.path.join(ADDON_DIR, 'LeoTamagotchi', 'UI', 'CleanUI.png')
                else:
                    path = os.path.join(ADDON_DIR, 'LeoTamagotchi', 'Devices', name + '.png')
                pm = QPixmap(path)
                if not pm.isNull():
                    # scale to fit label
                    w = max(300, self.devicePreview.width())
                    self.devicePreview.setPixmap(pm.scaledToWidth(w))
            except Exception:
                pass
        try:
            self.deviceCB.currentTextChanged.connect(lambda *_: _render_dev_preview())
            # Apply immediately on change so users see it live
            self.deviceCB.currentTextChanged.connect(lambda *_: self._apply_device_now())
            applyBtn.clicked.connect(lambda *_: self._apply_device_now())
        except Exception:
            pass
        _render_dev_preview()

        # Buttons
        btns = QHBoxLayout(); lay.addLayout(btns)
        save = QPushButton("Save"); reset = QPushButton("Reset to Defaults"); close = QPushButton("Close")
        btns.addStretch(1); btns.addWidget(reset); btns.addWidget(save); btns.addWidget(close)
        save.clicked.connect(self._on_save)
        reset.clicked.connect(self._on_reset)
        close.clicked.connect(self.close)

        # Wire live preview updates
        try:
            self._connect_preview_signals()
            self._render_popup_preview()
            self._render_ui_preview()
        except Exception:
            pass

        # Open floating preview window next to this dialog
        try:
            self.previewWin = AppearancePreviewWindow(self)
            self._position_preview_window()
            self.previewWin.show()
            self._render_popup_preview()
        except Exception:
            self.previewWin = None

    def _apply_device_now(self) -> None:
        try:
            name = self.deviceCB.currentText().strip() or 'CleanUI'
            from .LeoTamagotchi import gui as T  # type: ignore
            # Update running window and persist to state/cloud
            T.show_tamagotchi()  # ensure window exists
            try:
                # access singleton window via module-global
                if hasattr(T, '_window_singleton') and T._window_singleton is not None:
                    T._window_singleton.set_device(name)
                else:
                    # fallback: persist directly
                    st = T._read_state(); st['device'] = name; T._write_state(st)
            except Exception:
                st = T._read_state(); st['device'] = name; T._write_state(st)
        except Exception as e:
            try:
                showInfo(f"Apply device failed: {e}")
            except Exception:
                pass

    def _section(self, lay, text):
        w = QLabel(text); w.setStyleSheet("margin-top:10px;margin-bottom:4px;font-weight:600;"); lay.addWidget(w)

    def _spin_row(self, lay, label, lo, hi, key):
        row = QHBoxLayout(); lab = QLabel(label); sb = QSpinBox(); sb.setRange(lo,hi); sb.setValue(int(self._cfg.get(key, lo)))
        row.addWidget(lab); row.addWidget(sb,1); lay.addLayout(row); return sb

    def _color_row(self, lay, label, key):
        row = QHBoxLayout(); lab = QLabel(label); le = QLineEdit(self._cfg.get(key, "")); pick = QPushButton("Pick…")
        def on_pick():
            try:
                col = QColorDialog.getColor()
                if col and col.isValid():
                    le.setText(col.name())
            except Exception:
                pass
        pick.clicked.connect(on_pick)
        row.addWidget(lab); row.addWidget(le,1); row.addWidget(pick)
        lay.addLayout(row); return le

    # ---- Live preview helpers (class methods) ----
    def _connect_preview_signals(self):
        try:
            self.presetCB.currentTextChanged.connect(lambda *_: self._apply_preset(self.presetCB.currentText()))
            try: self.presetCB.currentIndexChanged.connect(lambda *_: self._apply_preset(self.presetCB.currentText()))
            except Exception: pass
        except Exception:
            pass
        for sb in [self.widthSB, self.fontSB, self.radiusSB]:
            try: sb.valueChanged.connect(self._render_popup_preview)
            except Exception: pass
        for le in [self.popupBgLE, self.popupFgLE, self.popupMutedLE, self.popupBorderLE, self.popupAccentLE, self.popupAccent2LE]:
            try: le.textChanged.connect(self._render_popup_preview)
            except Exception: pass
        for le in [self.fontTitleLE, self.fontBodyLE, self.fontUrlLE]:
            try: le.textChanged.connect(self._render_popup_preview)
            except Exception: pass
        try: self.popupCssTE.textChanged.connect(self._render_popup_preview)
        except Exception: pass
        try: self.copyPopupCssBtn.clicked.connect(self._copy_popup_css)
        except Exception: pass
        try: self.resetPopupBtn.clicked.connect(self._reset_popup_section)
        except Exception: pass
        for le in [self.uiBgLE, self.uiFgLE, self.uiAccentLE, self.uiCtrlBgLE, self.uiCtrlBorderLE, self.uiBtnBgLE, self.uiBtnBorderLE]:
            try: le.textChanged.connect(self._render_ui_preview)
            except Exception: pass
        try: self.uiCssTE.textChanged.connect(self._render_ui_preview)
        except Exception: pass
        try: self.resetUiBtn.clicked.connect(self._reset_ui_section)
        except Exception: pass

    def _popup_vars(self) -> dict:
        bg = (self.popupBgLE.text() or DEFAULT_CONFIG["popup_bg"]).strip()
        try:
            if isinstance(bg, str) and bg.endswith(")c"):
                bg = bg[:-1]
        except Exception:
            pass
        return {
            "bg": bg,
            "fg": (self.popupFgLE.text() or DEFAULT_CONFIG["popup_fg"]).strip(),
            "muted": (self.popupMutedLE.text() or DEFAULT_CONFIG["popup_muted"]).strip(),
            "border": (self.popupBorderLE.text() or DEFAULT_CONFIG["popup_border"]).strip(),
            "accent": (self.popupAccentLE.text() or DEFAULT_CONFIG["popup_accent"]).strip(),
            "accent2": (self.popupAccent2LE.text() or DEFAULT_CONFIG["popup_accent2"]).strip(),
            "radius": int(self.radiusSB.value()),
            "width": int(self.widthSB.value()),
            "font": int(self.fontSB.value()),
            "extra": self.popupCssTE.toPlainText(),
        }

    def _render_popup_preview(self):
        vars = self._popup_vars()
        pkg = mw.addonManager.addonFromModule(MODULE)
        font_url = (self.fontUrlLE.text() or '').strip()
        font_title = (self.fontTitleLE.text() or "'Baloo 2'").strip()
        font_body = (self.fontBodyLE.text() or "'Montserrat'").strip()
        # Optional font links (safe to embed in f-string)
        font_links = ""
        try:
            if font_url:
                font_links = (
                    "<link rel='preconnect' href='https://fonts.googleapis.com'>"
                    "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
                    f"<link rel='stylesheet' href='{html.escape(font_url)}'>"
                )
        except Exception:
            pass

        page = f"""
<!doctype html>
<html>
  <head>
    <meta charset='utf-8'>
    <link rel='stylesheet' href='/_addons/{pkg}/web/popup.css'>
    {font_links}
    <style>
      :root{{
        --ems-bg:{vars['bg']}; --ems-fg:{vars['fg']}; --ems-muted:{vars['muted']};
        --ems-border:{vars['border']}; --ems-accent:{vars['accent']}; --ems-accent-2:{vars['accent2']}; --ems-radius:{vars['radius']}px;
        --ems-font-title:{font_title}, system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, Arial, sans-serif;
        --ems-font-body:{font_body}, system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, Arial, sans-serif;
      }}
      .ems-popover{{ max-width:{vars['width']}px; font-size:{vars['font']}px; position:relative; left:auto; top:auto; transform:none; margin:8px auto; background:{vars['bg']} !important; }}
      .ems-topbar{{ background:{vars['bg']}; }}
      body{{ background:#0f121a; color:#edf1f7; margin:0; padding:8px; }}
      {vars['extra']}
    </style>
  </head>
  <body>
    <div class='ems-popover'>
      <div class='ems-topbar'>
        <span class='ems-pill'><span class='i'>?</span> Sample</span>
        <button class='ems-iconbtn'>i</button>
      </div>
      <div class='ems-body'>
        <div class='ems-content'>
          <h3>Sample Term</h3>
          <p class='ems-lead'>Concise definition preview with your styles.</p>
          <div class='ems-section'>
            <h4>Bullets</h4>
            <ul><li>First point</li><li>Second point</li></ul>
          </div>
        </div>
      </div>
      <div class='ems-brand'><div class='ems-brand-inner'><span class='ems-brand-name'>EnterMedSchool</span></div></div>
    </div>
  </body>
 </html>
        """
        try:
            if getattr(self, "previewWin", None) and hasattr(self.previewWin, "web"):
                try:
                    self.previewWin.web.stdHtml(page)
                except Exception:
                    self.previewWin.web.setHtml(page)
        except Exception:
            pass
        try:
            if getattr(self, "popupPreview", None):
                try:
                    self.popupPreview.stdHtml(page)
                except Exception:
                    self.popupPreview.setHtml(page)
        except Exception:
            pass

    def _ui_style(self) -> str:
        bg = (self.uiBgLE.text() or DEFAULT_CONFIG["ui_bg"]).strip()
        fg = (self.uiFgLE.text() or DEFAULT_CONFIG["ui_fg"]).strip()
        ac = (self.uiAccentLE.text() or DEFAULT_CONFIG["ui_accent"]).strip()
        cbg = (self.uiCtrlBgLE.text() or DEFAULT_CONFIG["ui_control_bg"]).strip()
        cbrd = (self.uiCtrlBorderLE.text() or DEFAULT_CONFIG["ui_control_border"]).strip()
        bbg = (self.uiBtnBgLE.text() or DEFAULT_CONFIG["ui_button_bg"]).strip()
        bbrd = (self.uiBtnBorderLE.text() or DEFAULT_CONFIG["ui_button_border"]).strip()
        extra = self.uiCssTE.toPlainText() or ""
        style = (
            f"QWidget{{background:{bg};color:{fg};}}"
            f"QLabel{{color:{fg};}}"
            f"QLineEdit,QPlainTextEdit,QComboBox{{background:{cbg};color:{fg};border:1px solid {cbrd};border-radius:10px;padding:6px 8px;}}"
            f"QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus{{border:1px solid {ac};}}"
            f"QPushButton{{background:{bbg};color:#fff;border:1px solid {bbrd};border-radius:10px;padding:8px 12px;font-weight:700;}}"
            f"QPushButton:hover{{filter:brightness(1.05);}}"
        )
        return style + extra

    def _render_ui_preview(self):
        try:
            self.uiPreview.setStyleSheet(self._ui_style())
        except Exception:
            pass

    def _copy_popup_css(self):
        vars = self._popup_vars()
        css = (
            ":root{\n" +
            f"  --ems-bg: {vars['bg']};\n" +
            f"  --ems-fg: {vars['fg']};\n" +
            f"  --ems-muted: {vars['muted']};\n" +
            f"  --ems-border: {vars['border']};\n" +
            f"  --ems-accent: {vars['accent']};\n" +
            f"  --ems-accent-2: {vars['accent2']};\n" +
            f"  --ems-radius: {vars['radius']}px;\n" +
            "}\n"
        )
        try:
            showText(css, title="Popup CSS Variables")
        except Exception:
            pass

    def _reset_popup_section(self):
        try:
            self.widthSB.setValue(DEFAULT_CONFIG.get("tooltip_width_px", 640))
            self.fontSB.setValue(DEFAULT_CONFIG.get("popup_font_px", 16))
            self.radiusSB.setValue(DEFAULT_CONFIG.get("popup_radius_px", 14))
            self.popupBgLE.setText(DEFAULT_CONFIG.get("popup_bg", ""))
            self.popupFgLE.setText(DEFAULT_CONFIG.get("popup_fg", ""))
            self.popupMutedLE.setText(DEFAULT_CONFIG.get("popup_muted", ""))
            self.popupBorderLE.setText(DEFAULT_CONFIG.get("popup_border", ""))
            self.popupAccentLE.setText(DEFAULT_CONFIG.get("popup_accent", ""))
            self.popupAccent2LE.setText(DEFAULT_CONFIG.get("popup_accent2", ""))
            self.popupCssTE.setPlainText(DEFAULT_CONFIG.get("popup_custom_css", ""))
            self._render_popup_preview()
        except Exception:
            pass

    def _reset_ui_section(self):
        try:
            self.uiBgLE.setText(DEFAULT_CONFIG.get("ui_bg", ""))
            self.uiFgLE.setText(DEFAULT_CONFIG.get("ui_fg", ""))
            self.uiAccentLE.setText(DEFAULT_CONFIG.get("ui_accent", ""))
            self.uiCtrlBgLE.setText(DEFAULT_CONFIG.get("ui_control_bg", ""))
            self.uiCtrlBorderLE.setText(DEFAULT_CONFIG.get("ui_control_border", ""))
            self.uiBtnBgLE.setText(DEFAULT_CONFIG.get("ui_button_bg", ""))
            self.uiBtnBorderLE.setText(DEFAULT_CONFIG.get("ui_button_border", ""))
            self.uiCssTE.setPlainText(DEFAULT_CONFIG.get("ui_custom_css", ""))
            self._render_ui_preview()
        except Exception:
            pass

    def _apply_preset(self, name: str):
        try:
            n = (name or "").strip().lower()
            def slug(s: str) -> str:
                s = (s or "").lower()
                if "default" in s: return "default"
                if "solarized" in s and "light" in s: return "solarized-light"
                if "solarized" in s: return "solarized-dark"
                if "high" in s and "contrast" in s: return "high-contrast"
                if "retro" in s or "bios" in s: return "retro-bios"
                if "vintage" in s or "beige" in s: return "vintage-beige"
                if "cute" in s or "pink" in s: return "cute-pink"
                if "modern" in s or "slate" in s: return "modern-slate"
                if "terminal" in s or "mono" in s: return "terminal-mono"
                for k in ["light","violet","cyan","emerald","dracula"]:
                    if k in s: return k
                return "default"

            presets = {
                "default": dict(bg="#0f121a", fg="#edf1f7", muted="#a4afbf", border="rgba(255,255,255,.10)", ac="#8b5cf6", ac2="#06b6d4", radius=14, css="", ftitle="'Baloo 2'", fbody="'Montserrat'", furl=DEFAULT_CONFIG.get("font_url","")),
                "light":   dict(bg="#ffffff", fg="#0f121a", muted="#4b5563", border="rgba(0,0,0,.12)", ac="#2563eb", ac2="#06b6d4", radius=14, css="", ftitle="'Inter'", fbody="'Inter'", furl="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap"),
                "high-contrast": dict(bg="#000000", fg="#ffffff", muted="#e5e7eb", border="#ffffff", ac="#ff006e", ac2="#ffd60a", radius=14, css="", ftitle="'Roboto'", fbody="'Roboto'", furl="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap"),
                "violet":  dict(bg="#0f121a", fg="#edf1f7", muted="#a4afbf", border="rgba(255,255,255,.15)", ac="#8b5cf6", ac2="#22d3ee", radius=14, css="", ftitle="'Baloo 2'", fbody="'Montserrat'", furl=DEFAULT_CONFIG.get("font_url","")),
                "cyan":    dict(bg="#0f121a", fg="#e6fbff", muted="#9adbe1", border="rgba(6,182,212,.35)", ac="#06b6d4", ac2="#60a5fa", radius=14, css="", ftitle="'Poppins'", fbody="'Poppins'", furl="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap"),
                "solarized-dark": dict(bg="#002b36", fg="#eee8d5", muted="#93a1a1", border="#073642", ac="#b58900", ac2="#268bd2", radius=14, css="", ftitle="'Roboto Slab'", fbody="'Source Sans 3'", furl="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap"),
                "solarized-light": dict(bg="#fdf6e3", fg="#073642", muted="#657b83", border="#eee8d5", ac="#268bd2", ac2="#2aa198", radius=14, css="", ftitle="'Roboto Slab'", fbody="'Source Sans 3'", furl="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap"),
                "vintage-beige": dict(bg="#f6edd9", fg="#2b2b2b", muted="#6b5e4a", border="rgba(0,0,0,.18)", ac="#a67c52", ac2="#d4a373", radius=10, css=".ems-lead{background:linear-gradient(180deg,#f3e9ce,#f0e2bf);border-color:rgba(0,0,0,.18);} .ems-pill{box-shadow:none;border-color:#a67c52;}", ftitle="'Special Elite'", fbody="'Lora'", furl="https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&family=Special+Elite&display=swap"),
                "retro-bios": dict(bg="#001b00", fg="#99ff99", muted="#66cc66", border="#1a3d1a", ac="#00ff66", ac2="#39ff14", radius=2, css="*{letter-spacing:0.3px;} .ems-popover{border-radius:2px;box-shadow:none;} .ems-body, .ems-content, .ems-popover{font-family: 'IBM Plex Mono', monospace !important;} .ems-popover::after{content:'';position:absolute;inset:0;background:repeating-linear-gradient(transparent,transparent 1px,rgba(0,255,128,.06) 2px,rgba(0,255,128,.06) 3px);pointer-events:none;} .ems-pill{background:transparent;border-color:#00ff66;color:#99ff99;} .ems-section{border-color:#00ff66;} .ems-lead{background:rgba(0,255,102,.06);border-color:#00ff66;}", ftitle="'IBM Plex Mono'", fbody="'IBM Plex Mono'", furl="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&display=swap"),
                "cute-pink": dict(bg="#fff1f5", fg="#4a1d2a", muted="#9d4b73", border="#f8b4d9", ac="#ec4899", ac2="#f472b6", radius=14, css="", ftitle="'Nunito'", fbody="'Nunito'", furl="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800&display=swap"),
                "modern-slate": dict(bg="#0f172a", fg="#e5e7eb", muted="#94a3b8", border="rgba(148,163,184,.35)", ac="#6366f1", ac2="#06b6d4", radius=14, css="", ftitle="'Inter'", fbody="'Inter'", furl="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap"),
                "emerald": dict(bg="#081c15", fg="#d8f3dc", muted="#74c69d", border="#1b4332", ac="#2d6a4f", ac2="#40916c", radius=14, css="", ftitle="'Urbanist'", fbody="'Inter'", furl="https://fonts.googleapis.com/css2?family=Urbanist:wght@700&family=Inter:wght@400;600&display=swap"),
                "dracula": dict(bg="#282a36", fg="#f8f8f2", muted="#b6b7c2", border="#44475a", ac="#bd93f9", ac2="#50fa7b", radius=14, css="", ftitle="'Rubik'", fbody="'Rubik'", furl="https://fonts.googleapis.com/css2?family=Rubik:wght@400;600;800&display=swap"),
                "terminal-mono": dict(bg="#111111", fg="#d1fae5", muted="#86efac", border="#22c55e", ac="#22c55e", ac2="#14b8a6", radius=14, css="", ftitle="'VT323'", fbody="'IBM Plex Mono'", furl="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=VT323&display=swap"),
            }

            key = slug(n)
            p = presets.get(key)
            if not p:
                self._reset_popup_section(); self._reset_ui_section()
            else:
                self.popupBgLE.setText(p["bg"]) ; self.popupFgLE.setText(p["fg"]) ; self.popupMutedLE.setText(p["muted"]) ; self.popupBorderLE.setText(p["border"]) ; self.popupAccentLE.setText(p["ac"]) ; self.popupAccent2LE.setText(p["ac2"]) ; self.radiusSB.setValue(int(p.get("radius",14)))
                self.fontTitleLE.setText(p["ftitle"]) ; self.fontBodyLE.setText(p["fbody"]) ; self.fontUrlLE.setText(p.get("furl",""))
                if p.get("css") is not None:
                    self.popupCssTE.setPlainText(p.get("css",""))
            self._render_popup_preview(); self._render_ui_preview()
        except Exception:
            pass
    def _on_save(self):
        cfg = get_config()
        # Popup
        cfg["tooltip_width_px"] = int(self.widthSB.value())
        cfg["popup_font_px"] = int(self.fontSB.value())
        bgval = (self.popupBgLE.text() or "").strip()
        if bgval.endswith(")c"): bgval = bgval[:-1]
        cfg["popup_bg"] = bgval or DEFAULT_CONFIG["popup_bg"]
        cfg["popup_fg"] = self.popupFgLE.text().strip() or DEFAULT_CONFIG["popup_fg"]
        cfg["popup_muted"] = self.popupMutedLE.text().strip() or DEFAULT_CONFIG["popup_muted"]
        cfg["popup_border"] = self.popupBorderLE.text().strip() or DEFAULT_CONFIG["popup_border"]
        cfg["popup_accent"] = self.popupAccentLE.text().strip() or DEFAULT_CONFIG["popup_accent"]
        cfg["popup_accent2"] = self.popupAccent2LE.text().strip() or DEFAULT_CONFIG["popup_accent2"]
        cfg["popup_radius_px"] = int(self.radiusSB.value())
        cfg["popup_custom_css"] = self.popupCssTE.toPlainText()
        # Fonts
        cfg["font_title"] = (self.fontTitleLE.text() or DEFAULT_CONFIG["font_title"]).strip()
        cfg["font_body"] = (self.fontBodyLE.text() or DEFAULT_CONFIG["font_body"]).strip()
        cfg["font_url"] = (self.fontUrlLE.text() or DEFAULT_CONFIG["font_url"]).strip()
        # Dialogs
        cfg["ui_bg"] = self.uiBgLE.text().strip() or DEFAULT_CONFIG["ui_bg"]
        cfg["ui_fg"] = self.uiFgLE.text().strip() or DEFAULT_CONFIG["ui_fg"]
        cfg["ui_accent"] = self.uiAccentLE.text().strip() or DEFAULT_CONFIG["ui_accent"]
        cfg["ui_control_bg"] = self.uiCtrlBgLE.text().strip() or DEFAULT_CONFIG["ui_control_bg"]
        cfg["ui_control_border"] = self.uiCtrlBorderLE.text().strip() or DEFAULT_CONFIG["ui_control_border"]
        cfg["ui_button_bg"] = self.uiBtnBgLE.text().strip() or DEFAULT_CONFIG["ui_button_bg"]
        cfg["ui_button_border"] = self.uiBtnBorderLE.text().strip() or DEFAULT_CONFIG["ui_button_border"]
        cfg["ui_custom_css"] = self.uiCssTE.toPlainText()
        # Behavior
        cfg["hover_mode"] = self.hoverModeCB.currentText()
        cfg["hover_delay_ms"] = int(self.hoverDelaySB.value())
        cfg["max_highlights"] = int(self.maxHL.value())
        cfg["open_with_click_anywhere"] = bool(self.clickAnyCB.isChecked())
        cfg["scan_fields"] = self.scanFieldsLE.text().strip()
        cfg["mute_tags"] = self.muteTagsLE.text().strip()
        cfg["learn_target"] = self.learnTargetCB.currentText()
        cfg["learn_deck_name"] = self.deckLE.text().strip() or "EnterMedSchool - Terms"
        write_config(cfg)
        try:
            _apply_theme_runtime()
        except Exception:
            pass
        showInfo("Saved and applied.")

    def _on_reset(self):
        cfg = get_config()
        for k, v in DEFAULT_CONFIG.items():
            if k == "last_update_check": continue
            cfg[k] = v
        write_config(cfg); showInfo("Reset to defaults.")

    def _position_preview_window(self):
        try:
            if not getattr(self, "previewWin", None):
                return
            g = self.geometry()
            x = g.x() + g.width() + 12
            y = g.y()
            self.previewWin.move(max(0, x), max(0, y))
        except Exception:
            pass

    def moveEvent(self, evt):
        try:
            self._position_preview_window()
        except Exception:
            pass
        try:
            super().moveEvent(evt)
        except Exception:
            pass

    def resizeEvent(self, evt):
        try:
            self._position_preview_window()
        except Exception:
            pass
        try:
            super().resizeEvent(evt)
        except Exception:
            pass

    def closeEvent(self, evt):
        try:
            if getattr(self, "previewWin", None):
                self.previewWin.close()
        except Exception:
            pass
        try:
            super().closeEvent(evt)
        except Exception:
            pass
def on_show_options():
    try:
        LOG.log("ui.appearance.open")
        d = AppearanceDialog(mw)
        if hasattr(d, "exec"):
            d.exec()
        else:
            d.exec_()
    except Exception as e:
        try:
            LOG.log("ui.appearance.error", error=str(e))
        except Exception:
            pass

# -------------------------- Suggest Term UI -----------------------------------

class LivePreviewWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Glossary Term Preview")
        self.setMinimumSize(720, 520)
        self.setWindowIcon(_ensure_logo_icon())
        lay = QVBoxLayout(self)
        self.web = AnkiWebView(self)
        lay.addWidget(self.web, 1)

    def render(self, obj: dict, errors: List[Any] = None):
        pkg = mw.addonManager.addonFromModule(MODULE)
        # Be defensive: config values can occasionally be bad/strings/None.
        try:
            width = int(get_config().get("tooltip_width_px", 640) or 640)
        except Exception:
            width = 640
        if not width or width < 360:
            width = 360
        try:
            font_px = int(get_config().get("popup_font_px", 16) or 16)
        except Exception:
            font_px = 16
        err_html = ""
        try:
            body_html = _term_html_from_schema(obj or {})
        except Exception as e:
            body_html = f"<div class='ems-body'><em>Failed to render:</em> {html.escape(str(e))}</div>"
            errors = (errors or []) + [f"Renderer error: {str(e)}"]
        if errors:
            items = ''.join(f"<li>{html.escape(str(x))}</li>" for x in errors)
            err_html = f"<div style='margin:10px 0;padding:10px 12px;border:1px solid #ef4444;background:#7f1d1d22;color:#fecaca;border-radius:8px'><b>Issues detected:</b><ul style='margin:6px 0 0 18px'>{items}</ul></div>"
        page = f"""
<!doctype html>
<html>
  <head>
    <meta charset='utf-8'>
    <link rel='stylesheet' href='/_addons/{pkg}/web/popup.css'>
    <style>
      html,body{{background:#0f121a;color:#edf1f7;margin:0;padding:12px}}
      .ems-popover{{position:relative;left:auto;top:auto;transform:none;width:{width}px;font-size:{font_px}px;}}
    </style>
  </head>
  <body>
    {err_html}
    <div class='ems-popover ems-preview'>
      {body_html}
    </div>
  </body>
</html>
"""
        try:
            self.web.stdHtml(page)
        except Exception as e:
            _log(f"Live preview stdHtml error: {e}")
            try:
                self.web.setHtml(page)
            except Exception as e2:
                _log(f"Live preview setHtml error: {e2}")

class AppearancePreviewWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("EMS Popup Preview")
        self.setMinimumSize(520, 420)
        self.setWindowIcon(_ensure_logo_icon())
        lay = QVBoxLayout(self)
        self.web = AnkiWebView(self)
        lay.addWidget(self.web, 1)

class SuggestTermDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        # Internal flag to temporarily pause auto-saving of drafts
        self._suspend_draft = False
        self.setWindowTitle("Create a Glossary Term")
        self.setMinimumWidth(620)
        self.resize(900, 820)
        self.setWindowIcon(_ensure_logo_icon())
        # Outer layout
        outer = QVBoxLayout(self)
        # Apply UI theme from config
        try:
            self._apply_ui_theme()
        except Exception:
            pass

        # Header row with example toggle and preview opener
        header = QHBoxLayout()
        logo = QLabel(f"<img width=24 height=24 src='/_addons/{mw.addonManager.addonFromModule(MODULE)}/web/ems_logo.png'>")
        title = QLabel("<b>Create a Glossary Term</b>")
        self.exampleToggleBtn = QPushButton("Show Example")
        self.openPreviewBtn = QPushButton("Open Live Preview")
        header.addWidget(logo); header.addWidget(title); header.addStretch(1); header.addWidget(self.exampleToggleBtn); header.addWidget(self.openPreviewBtn)
        outer.addLayout(header)

        # Tabs: Editor | Preview
        self.tabs = QTabWidget(self)
        outer.addWidget(self.tabs, 1)

        # Editor tab content uses a scroll area
        editorPage = QWidget(self)
        editorLay = QVBoxLayout(editorPage)
        scroll = QScrollArea(self); self.scroll = scroll
        scroll.setWidgetResizable(True)
        editorLay.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)

        # Attach the editor page to tabs now; preview tab is added below
        self.tabs.addTab(editorPage, "Editor")

        # Hide tab bar (only one tab for editor); preview opens in its own window
        try:
            self.tabs.tabBar().hide()
        except Exception:
            pass
        self.previewWin = None

        # Core fields
        lay.addWidget(QLabel("Core"))
        # Inline error for Names
        self.namesErrFrame, self.namesErrLabel, self.namesErrBtn = self._make_error_banner(action_text="Load existing", action_handler=self._on_load_existing)
        lay.addWidget(self.namesErrFrame); self.namesErrFrame.setVisible(False)
        core1 = QHBoxLayout(); core1.addWidget(QLabel("Name(s) (comma-separated):"))
        self.namesLE = QLineEdit(); self.namesLE.setPlaceholderText("e.g., Cushing syndrome, Hypercortisolism")
        core1.addWidget(self.namesLE, 1); lay.addLayout(core1)

        # Inline error for Definition
        self.defErrFrame, self.defErrLabel, _btn = self._make_error_banner()
        lay.addWidget(self.defErrFrame); self.defErrFrame.setVisible(False)
        core2 = QHBoxLayout(); core2.addWidget(QLabel("Definition:"))
        self.definitionTE = QPlainTextEdit(); self.definitionTE.setPlaceholderText("A clear, concise definition. Example: Excess cortisol exposure causing central obesity, striae, proximal weakness, hypertension, and glucose intolerance."); self.definitionTE.setFixedHeight(110)
        core2.addWidget(self.definitionTE, 1); lay.addLayout(core2)

        # Optional fields
        lay.addWidget(QLabel("Optional"))
        rowA = QHBoxLayout(); rowA.addWidget(QLabel("Aliases (comma-separated):"))
        self.aliasesLE = QLineEdit(); self.aliasesLE.setPlaceholderText("e.g., Hypercortisolism")
        rowA.addWidget(self.aliasesLE, 1); lay.addLayout(rowA)

        rowB = QHBoxLayout(); rowB.addWidget(QLabel("Abbreviations (comma-separated):"))
        self.abbrLE = QLineEdit(); self.abbrLE.setPlaceholderText("e.g., CS")
        rowB.addWidget(self.abbrLE, 1); lay.addLayout(rowB)

        # Primary tag from tags.json (single select)
        # Inline error for Primary tag
        self.tagErrFrame, self.tagErrLabel, _btn2 = self._make_error_banner()
        lay.addWidget(self.tagErrFrame); self.tagErrFrame.setVisible(False)
        rowC = QHBoxLayout(); rowC.addWidget(QLabel("Primary tag:"))
        self.primaryTagCB = QComboBox()
        try:
            tags = sorted((GLOSSARY.tags_meta or {}).keys())
        except Exception:
            tags = []
        if not tags:
            tags = ["general"]
        self.primaryTagCB.addItems(tags)
        rowC.addWidget(self.primaryTagCB, 1); lay.addLayout(rowC)

        self.whyTE = QPlainTextEdit(); self.whyTE.setPlaceholderText("Why it matters (1–2 sentences). Example: Early recognition prevents complications like opportunistic infections and fractures."); self.whyTE.setFixedHeight(80)
        lay.addWidget(QLabel("Why it matters:")); lay.addWidget(self.whyTE)

        self.hysiTE = QPlainTextEdit(); self.hysiTE.setPlaceholderText("One bullet per line. Example:\n• Progressive central obesity, moon facies\n• Purple abdominal striae\n• Proximal muscle weakness"); self.hysiTE.setFixedHeight(100)
        lay.addWidget(QLabel("How you'll see it (bullets):")); lay.addWidget(self.hysiTE)

        self.psTE = QPlainTextEdit(); self.psTE.setPlaceholderText("One bullet per line. Example:\n• Suspect with refractory HTN + diabetes\n• Screen with late-night salivary cortisol or 1 mg overnight dex suppression\n• Confirm with 24-hr urinary free cortisol"); self.psTE.setFixedHeight(110)
        lay.addWidget(QLabel("Problem solving (bullets):")); lay.addWidget(self.psTE)

        self.diffTE = QPlainTextEdit(); self.diffTE.setPlaceholderText("One per line: Name | hint. Examples:\nAddison disease | Look for hyperpigmentation, hypotension\nPCOS | Hyperandrogenism + ovarian cysts, normal cortisol"); self.diffTE.setFixedHeight(100)
        lay.addWidget(QLabel("Differentials (one per line):")); lay.addWidget(self.diffTE)

        self.tricksTE = QPlainTextEdit(); self.tricksTE.setPlaceholderText("One bullet per line. Example:\n• Think ‘CUSHING’ mnemonic: Central obesity, striae, HTN, etc."); self.tricksTE.setFixedHeight(90)
        lay.addWidget(QLabel("Tricks (bullets):")); lay.addWidget(self.tricksTE)

        self.examTE = QPlainTextEdit(); self.examTE.setPlaceholderText("One bullet per line. Example:\n• Woman with resistant HTN, truncal obesity, purple striae"); self.examTE.setFixedHeight(90)
        lay.addWidget(QLabel("Exam appearance (bullets):")); lay.addWidget(self.examTE)

        self.treatTE = QPlainTextEdit(); self.treatTE.setPlaceholderText("One bullet per line. Example:\n• Surgical resection if adrenal or pituitary tumor\n• Ketoconazole or metyrapone if not surgical candidate"); self.treatTE.setFixedHeight(100)
        lay.addWidget(QLabel("Treatment (bullets):")); lay.addWidget(self.treatTE)

        self.rfTE = QPlainTextEdit(); self.rfTE.setPlaceholderText("One bullet per line. Example:\n• Severe hypokalemia\n• Opportunistic infections\n• Pathologic fractures"); self.rfTE.setFixedHeight(90)
        lay.addWidget(QLabel("Red flags (bullets):")); lay.addWidget(self.rfTE)

        self.algoTE = QPlainTextEdit(); self.algoTE.setPlaceholderText("Step per line. Example:\n1) Screen with 1 mg dex suppression\n2) Confirm with 24-hr UFC\n3) Localize with ACTH + imaging"); self.algoTE.setFixedHeight(100)
        lay.addWidget(QLabel("Algorithm (steps, one per line):")); lay.addWidget(self.algoTE)

        # Media (images)
        self.imagesTE = QPlainTextEdit(); self.imagesTE.setPlaceholderText("One per line: URL | alt text | credit text | credit href\nExample: https://example.org/adrenal_mri.png | Adrenal MRI showing mass | Wikimedia | https://commons.wikimedia.org/...")
        self.imagesTE.setFixedHeight(90)
        lay.addWidget(QLabel("Images (one per line):")); lay.addWidget(self.imagesTE)

        # Mini cases
        self.casesTE = QPlainTextEdit(); self.casesTE.setPlaceholderText("One per line: Stem | clue1; clue2; clue3 | Answer | Teaching point\nExample: 35F with resistant HTN and weight gain | truncal obesity; purple striae; proximal weakness | Cushing syndrome | Excess cortisol causes the phenotype")
        self.casesTE.setFixedHeight(100)
        lay.addWidget(QLabel("Mini cases (one per line):")); lay.addWidget(self.casesTE)

        # Cross-links
        self.seeAlsoTE = QPlainTextEdit(); self.seeAlsoTE.setPlaceholderText("IDs of related terms, one per line. Example:\nadrenal-adenoma\npituitary-adenoma")
        self.seeAlsoTE.setFixedHeight(70)
        lay.addWidget(QLabel("See also (IDs, one per line):")); lay.addWidget(self.seeAlsoTE)

        self.prereqTE = QPlainTextEdit(); self.prereqTE.setPlaceholderText("IDs of prerequisite terms, one per line. Example:\nadrenal-cortex-hormones")
        self.prereqTE.setFixedHeight(70)
        lay.addWidget(QLabel("Prerequisites (IDs, one per line):")); lay.addWidget(self.prereqTE)

        self.sourcesTE = QPlainTextEdit(); self.sourcesTE.setPlaceholderText("One per line: Title | URL OR just URL\nExample: Endocrine Society Guideline | https://...\nUptodate | https://...\nhttps://reputable.source/article")
        self.sourcesTE.setFixedHeight(90)
        lay.addWidget(QLabel("Sources:")); lay.addWidget(self.sourcesTE)

        # Credits (optional): one per line => email | role | display name | avatar url
        self.creditsTE = QPlainTextEdit();
        self.creditsTE.setPlaceholderText("One per line: email | role | display (optional) | avatar (optional)\nExample:\nuser@example.com | Author | Jane Doe | https://example.org/avatar.jpg")
        self.creditsTE.setFixedHeight(70)
        lay.addWidget(QLabel("Credits (email | role | display | avatar):")); lay.addWidget(self.creditsTE)
        try:
            # Prefill current user when logged in to PocketBase
            from . import ems_pocketbase as PB
            a = PB.load_auth() or {}
            rec = a.get('record') or {}
            email = (rec.get('email') or '').strip()
            display = (rec.get('name') or '').strip()
            avatar = ''
            try:
                ok, prof = PB.profile_get()
                if ok and isinstance(prof, dict):
                    display = prof.get('display_name', display) or display
                    avatar = prof.get('avatar_url') or ''
            except Exception:
                pass
            if email and not self.creditsTE.toPlainText().strip():
                self.creditsTE.setPlainText(f"{email} | Author | {display} | {avatar}")
        except Exception:
            pass

        # Example viewer (collapsible)
        lay.addWidget(QLabel("Example (complete term JSON):"))
        self.exampleTE = QPlainTextEdit(); self.exampleTE.setReadOnly(True)
        self.exampleTE.setPlainText(self._example_json_text())
        self.exampleTE.setVisible(False)
        lay.addWidget(self.exampleTE)

        # Bottom buttons (pinned)
        btns = QHBoxLayout(); btns.addStretch(1)
        exampleLoadBtn = QPushButton("Load Example")
        previewBtn = QPushButton("Preview JSON")
        saveBtn = QPushButton("Save to File")
        resetBtn = QPushButton("Reset Form")
        submitBtn = QPushButton("Submit")
        submitBtn.setToolTip("GitHub is the website we use to host all of our terms, the code of this add-on, and more. To submit you will need to quickly create a free GitHub account — it lets you keep track and a backup of all your submissions. Thank you!")
        # Styling is applied via dialog stylesheet for brand consistency
        closeBtn = QPushButton("Close")
        btns.addWidget(exampleLoadBtn); btns.addWidget(previewBtn); btns.addWidget(saveBtn); btns.addWidget(resetBtn); btns.addWidget(submitBtn); btns.addWidget(closeBtn)
        outer.addLayout(btns)

        # Wire up
        self.exampleToggleBtn.clicked.connect(self._toggle_example)
        self.openPreviewBtn.clicked.connect(self._open_preview_window)
        exampleLoadBtn.clicked.connect(self._on_load_example)
        previewBtn.clicked.connect(self._on_preview)
        saveBtn.clicked.connect(self._on_save_file)
        resetBtn.clicked.connect(self._on_reset_form)
        submitBtn.clicked.connect(self._on_submit)
        closeBtn.clicked.connect(self.close)

        # Live preview signals
        try:
            for w in [self.namesLE, self.aliasesLE, self.abbrLE]:
                w.textChanged.connect(self._update_live_preview)
                w.textChanged.connect(self._save_draft)
            for te in [
                self.definitionTE, self.whyTE, self.hysiTE, self.psTE,
                self.diffTE, self.tricksTE, self.examTE, self.treatTE,
                self.rfTE, self.algoTE, self.sourcesTE, self.imagesTE,
                self.casesTE, self.seeAlsoTE, self.prereqTE
            ]:
                te.textChanged.connect(self._update_live_preview)
                te.textChanged.connect(self._save_draft)
            self.primaryTagCB.currentTextChanged.connect(self._update_live_preview)
            self.primaryTagCB.currentTextChanged.connect(self._save_draft)
        except Exception:
            pass
        # Inline validation hooks
        try:
            self.namesLE.textChanged.connect(self._validate_inline)
            self.definitionTE.textChanged.connect(self._validate_inline)
            self.primaryTagCB.currentTextChanged.connect(self._validate_inline)
        except Exception:
            pass
        self._update_live_preview(); self._validate_inline()

        # Ensure "my terms" folder exists
        try:
            os.makedirs(MY_TERMS_DIR, exist_ok=True)
        except Exception:
            pass

        # Load saved draft, if any
        try:
            if os.path.exists(SUGGEST_DRAFT_PATH):
                data = open(SUGGEST_DRAFT_PATH, 'r', encoding='utf-8').read()
                obj = json.loads(data)
                self._populate_from(obj)
                self._update_live_preview(); self._validate_inline()
        except Exception as e:
            _log(f"load draft failed: {e}")

    def _apply_ui_theme(self):
        cfg = get_config()
        bg = cfg.get("ui_bg", "#0f121a")
        fg = cfg.get("ui_fg", "#edf1f7")
        ac = cfg.get("ui_accent", "#8b5cf6")
        cbg = cfg.get("ui_control_bg", "rgba(255,255,255,.04)")
        cbrd = cfg.get("ui_control_border", "rgba(255,255,255,.12)")
        bbg = cfg.get("ui_button_bg", "#7c3aed")
        bbrd = cfg.get("ui_button_border", "#a78bfa")
        extra = cfg.get("ui_custom_css", "") or ""
        style = (
            # Set a sane default background on all child widgets of this dialog
            # so content inside QScrollArea doesn't fall back to a white palette
            # (which makes near-white label text look invisible).
            f"QDialog{{background:{bg};color:{fg};}}"
            f"QWidget{{background:{bg};color:{fg};}}"
            f"QLabel{{color:{fg};}}"
            f"QLineEdit,QPlainTextEdit,QComboBox{{background:{cbg};color:{fg};border:1px solid {cbrd};border-radius:10px;padding:6px 8px;}}"
            f"QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus{{border:1px solid {ac};}}"
            f"QPushButton{{background:{bbg};color:#fff;border:1px solid {bbrd};border-radius:10px;padding:8px 12px;font-weight:700;}}"
            f"QPushButton:hover{{filter:brightness(1.05);}}"
            # Ensure the scroll area viewport also inherits the dark background
            f"QScrollArea{{border:none;background:{bg};}}"
        )
        try:
            self.setStyleSheet(style + extra)
        except Exception:
            self.setStyleSheet(style)

    def _open_preview_window(self):
        try:
            if getattr(self, "previewWin", None) is None:
                self.previewWin = LivePreviewWindow(self)
                try:
                    # position beside the editor window
                    g = self.geometry()
                    x = g.x() + g.width() + 12
                    y = g.y()
                    self.previewWin.move(max(0, x), max(0, y))
                except Exception:
                    pass
            self.previewWin.show()
            self._update_live_preview()
        except Exception:
            pass

    def _collect_errors(self, obj: dict) -> list:
        errs = []
        if not (obj.get("names") or []):
            errs.append("Add at least one Name.")
        if not obj.get("definition"):
            errs.append("Add a Definition (1–2 sentences).")
        # primary tag optional but recommended
        if not obj.get("primary_tag"):
            errs.append("Select a Primary tag.")
        try:
            names = obj.get("names") or []
            if names and self._find_existing_by_names(names):
                errs.append("A term with this name already exists.")
        except Exception:
            pass
        return errs

    def _find_existing_by_names(self, names: list) -> dict:
        try:
            want = set((n or "").strip().lower() for n in names if (n or "").strip())
            if not want:
                return {}
            # quick id check by slug
            slug = self._slugify(names[0]) if names else ""
            if slug and slug in GLOSSARY.terms_by_id:
                return GLOSSARY.terms_by_id.get(slug) or {}
            for t in (GLOSSARY.terms_by_id or {}).values():
                for n in (t.get("names") or []):
                    if (n or "").strip().lower() in want:
                        return t
        except Exception:
            pass
        return {}

    def _on_save_file(self):
        try:
            os.makedirs(MY_TERMS_DIR, exist_ok=True)
        except Exception:
            pass
        try:
            obj = self._build_payload()
            # default filename from first name/slug
            base = (obj.get("id") or (self._slugify((obj.get("names") or [""])[0])) or "term").strip()
            if not base:
                base = "term"
            default = os.path.join(MY_TERMS_DIR, base + ".json")
            path, _filter = QFileDialog.getSaveFileName(self, "Save Glossary Term JSON", default, "JSON Files (*.json)")
            if not path:
                return
            # write file
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=2)
            tooltip(f"Saved to {path}")
        except Exception as e:
            showInfo(f"Save failed: {e}")

    def _save_draft(self):
        # Respect suspension flag (e.g., during Clean Form)
        if getattr(self, "_suspend_draft", False):
            return
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
        except Exception:
            pass
        try:
            obj = self._build_payload()
            # Only persist if there is meaningful user content
            # Ignore metadata-only keys like id/tags/primary_tag
            keys = set(obj.keys())
            for meta in ("id", "primary_tag", "tags"):
                keys.discard(meta)
            if not keys:
                # No substantive fields, remove any existing draft
                try:
                    if os.path.exists(SUGGEST_DRAFT_PATH):
                        os.remove(SUGGEST_DRAFT_PATH)
                except Exception:
                    pass
                return
            with open(SUGGEST_DRAFT_PATH, 'w', encoding='utf-8') as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            _log(f"save draft failed: {e}")

    def _on_reset_form(self):
        """Reset only user-entered text without changing selections.
        Also clears the persisted draft so the reset sticks across restarts.
        """
        try:
            # Pause auto-save and block signals so clears don't trigger re-save
            self._suspend_draft = True

            blockers = []
            def _block(obj):
                try:
                    if obj is not None:
                        obj.blockSignals(True)
                        blockers.append(obj)
                except Exception:
                    pass

            # Clear line edits (user text inputs)
            for name in [
                "namesLE", "aliasesLE", "abbrLE",
                "contribNameLE", "contribLinkLE", "contribIdLE",
            ]:
                w = getattr(self, name, None)
                _block(w)
                try:
                    if w is not None:
                        try:
                            w.clear()
                        except Exception:
                            w.setText("")
                except Exception:
                    pass

            # Clear multi-line text edits
            for name in [
                "definitionTE", "whyTE", "hysiTE", "psTE", "diffTE",
                "tricksTE", "examTE", "treatTE", "rfTE", "algoTE",
                "sourcesTE", "imagesTE", "casesTE", "seeAlsoTE", "prereqTE",
            ]:
                te = getattr(self, name, None)
                _block(te)
                try:
                    if te is not None:
                        te.setPlainText("")
                except Exception:
                    pass

            # Do not change dropdowns or other non-text selections

            # Remove saved draft so reset persists across reopen
            try:
                if os.path.exists(SUGGEST_DRAFT_PATH):
                    os.remove(SUGGEST_DRAFT_PATH)
            except Exception:
                pass

            # Unblock signals
            try:
                for obj in blockers:
                    try:
                        obj.blockSignals(False)
                    except Exception:
                        pass
            except Exception:
                pass

            # Resume auto-save
            self._suspend_draft = False

            # Update preview/validation for clean state
            try:
                self._update_live_preview()
                self._validate_inline()
            except Exception:
                pass
        except Exception:
            pass

    def closeEvent(self, evt):
        try:
            self._save_draft()
        except Exception:
            pass
        try:
            super().closeEvent(evt)
        except Exception:
            pass

    # ---------- Inline errors & helpers ----------
    def _make_error_banner(self, action_text: str = "", action_handler=None):
        frame = QFrame(self); frame.setObjectName("emsInlineError")
        style = (
            "QFrame#emsInlineError{background:rgba(127,29,29,.18);border:1px solid #ef4444;border-radius:8px;padding:6px 8px;margin:4px 0;}"
            "QLabel{color:#fecaca;font-weight:600;}"
            "QPushButton{background:linear-gradient(180deg, rgba(139,92,246,.35), rgba(139,92,246,.20));"
            "border:1px solid rgba(139,92,246,.65);color:#fff;border-radius:8px;padding:6px 10px;font-weight:700;}"
            "QPushButton:hover{filter:brightness(1.08);}"
        )
        frame.setStyleSheet(style)
        row = QHBoxLayout(frame)
        lab = QLabel("")
        row.addWidget(lab, 1)
        btn = QPushButton(action_text) if action_text else QPushButton()
        if action_text:
            row.addWidget(btn, 0)
            if action_handler:
                btn.clicked.connect(action_handler)
        else:
            btn.setVisible(False)
        return frame, lab, btn

    def _set_error(self, which: str, text: str, show_action: bool = False):
        if which == "name":
            self.namesErrLabel.setText(("? " + text) if text else "")
            self.namesErrBtn.setVisible(show_action)
            self.namesErrFrame.setVisible(bool(text))
            try:
                self.scroll.ensureWidgetVisible(self.namesLE)
            except Exception:
                pass
            try:
                self.namesLE.setStyleSheet("border:1px solid #ef4444;border-radius:6px;" if text else "")
            except Exception:
                pass
        elif which == "definition":
            self.defErrLabel.setText(("? " + text) if text else "")
            self.defErrFrame.setVisible(bool(text))
            try:
                self.definitionTE.setStyleSheet("border:1px solid #ef4444;border-radius:6px;" if text else "")
            except Exception:
                pass
        elif which == "tag":
            self.tagErrLabel.setText(("? " + text) if text else "")
            self.tagErrFrame.setVisible(bool(text))

    def _validate_inline(self):
        try:
            # Names: duplicate detection
            names = self._csv_list(self.namesLE.text())
            dup = self._find_existing_by_names(names)
            if names and dup:
                n0 = names[0]
                self._set_error("name", f"A term named ‘{n0}’ already exists.", show_action=True)
            else:
                self._set_error("name", "", show_action=False)
            # Definition required
            if not self.definitionTE.toPlainText().strip():
                self._set_error("definition", "Add a Definition (1–2 sentences).")
            else:
                self._set_error("definition", "")
            # Primary tag — ensure selected
            if not (self.primaryTagCB.currentText() or "").strip():
                self._set_error("tag", "Select a Primary tag.")
            else:
                self._set_error("tag", "")
        except Exception:
            pass

    def _on_load_existing(self):
        try:
            names = self._csv_list(self.namesLE.text())
            existing = self._find_existing_by_names(names)
            if existing:
                self._populate_from(existing)
                self._set_error("name", "", show_action=False)
                tooltip("Loaded existing term — you can edit and submit as an edit suggestion.")
                self._update_live_preview()
        except Exception:
            pass

    def _csv_list(self, s: str) -> list:
        return [x.strip() for x in (s or "").split(",") if x.strip()]

    def _lines_list(self, s: str) -> list:
        return [x.strip() for x in (s or "").splitlines() if x.strip()]

    def _parse_differentials(self, s: str) -> list:
        out = []
        for line in self._lines_list(s):
            if "|" in line:
                name, hint = line.split("|", 1)
                out.append({"name": name.strip(), "hint": hint.strip()})
            else:
                out.append(line)
        return out

    def _parse_sources(self, s: str) -> list:
        out = []
        for line in self._lines_list(s):
            if "|" in line:
                title, url = line.split("|", 1)
                out.append({"title": title.strip(), "url": url.strip()})
            else:
                out.append({"title": line.strip(), "url": line.strip()})
        return out

    def _parse_images(self, s: str) -> list:
        out = []
        for line in self._lines_list(s):
            parts = [p.strip() for p in line.split("|")]
            if not parts:
                continue
            src = parts[0] if len(parts) >= 1 else ""
            alt = parts[1] if len(parts) >= 2 else ""
            ctext = parts[2] if len(parts) >= 3 else ""
            chref = parts[3] if len(parts) >= 4 else ""
            item = {"src": src}
            if alt:
                item["alt"] = alt
            if ctext or chref:
                credit = {}
                if ctext:
                    credit["text"] = ctext
                if chref:
                    credit["href"] = chref
                item["credit"] = credit
            if item.get("src"):
                out.append(item)
        return out

    def _parse_credits(self, s: str) -> list:
        out = []
        for line in self._lines_list(s):
            parts = [p.strip() for p in line.split("|")]
            if not parts:
                continue
            email = parts[0] if len(parts) >= 1 else ""
            role = parts[1] if len(parts) >= 2 else ""
            display = parts[2] if len(parts) >= 3 else ""
            avatar = parts[3] if len(parts) >= 4 else ""
            obj = {}
            if email:
                obj["email"] = email
            if role:
                obj["role"] = role
            if display:
                obj["display"] = display
            if avatar:
                obj["avatar"] = avatar
            if obj:
                out.append(obj)
        return out

    def _parse_cases(self, s: str) -> list:
        out = []
        for line in self._lines_list(s):
            parts = [p.strip() for p in line.split("|")]
            if not parts:
                continue
            stem = parts[0] if len(parts) >= 1 else ""
            clues = [c.strip() for c in (parts[1].split(";") if len(parts) >= 2 else []) if c.strip()]
            ans = parts[2] if len(parts) >= 3 else ""
            teach = parts[3] if len(parts) >= 4 else ""
            item = {}
            if stem:
                item["stem"] = stem
            if clues:
                item["clues"] = clues
            if ans:
                item["answer"] = ans
            if teach:
                item["teaching"] = teach
            if item:
                out.append(item)
        return out

    def _update_live_preview(self):
        try:
            obj = self._build_payload()
            errs = self._collect_errors(obj)
            if getattr(self, "previewWin", None):
                self.previewWin.render(obj, errors=errs)
        except Exception as e:
            if getattr(self, "previewWin", None):
                try:
                    self.previewWin.render({}, errors=[f"Unexpected preview error: {str(e)}"]) 
                except Exception as e2:
                    # Last-resort log to avoid silent failures
                    _log(f"Live preview secondary render failed: {e2}")

    def _slugify(self, s: str) -> str:
        base = re.sub(r"[^A-Za-z0-9]+", "-", (s or "").strip().lower()).strip("-")
        return base or str(uuid.uuid4())[:8]

    def _toggle_example(self):
        vis = not self.exampleTE.isVisible()
        self.exampleTE.setVisible(vis)
        self.exampleToggleBtn.setText("Hide Example" if vis else "Show Example")

    def _example_json_text(self) -> str:
        # Prefer a real local example if available
        try:
            p = os.path.join(TERMS_DIR, "acth.json")
            if os.path.exists(p):
                txt = open(p, "r", encoding="utf-8").read()
                obj = json.loads(txt)
                return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            pass

        example = {
            "id": "sample-term",
            "primary_tag": "general",
            "tags": ["general", "example"],
            "names": ["Sample Term", "Demo Concept"],
            "aliases": ["Mock Term"],
            "abbr": ["ST"],
            "definition": "A concise definition showing how to structure entries.",
            "images": [
                {"src": "https://example.com/image.png", "alt": "diagram", "credit": {"text": "image credit", "href": "https://example.com"}}
            ],
            "why_it_matters": "Helpful to illustrate the schema fields.",
            "how_youll_see_it": ["On cards", "In popovers", "During review"],
            "problem_solving": ["Recognize pattern", "Check clues", "Pick next step"],
            "differentials": [
                {"name": "Related Term A", "hint": "differs by context"},
                {"name": "Related Term B", "hint": "different mechanism"}
            ],
            "tricks": ["Remember with a mnemonic", "Avoid common pitfall"],
            "exam_appearance": ["Classic vignette", "Buzzword"],
            "treatment": ["First line option", "Alternative if contraindication"],
            "red_flags": ["Do not miss sign", "Requires urgent action"],
            "algorithm": ["Step 1", "Step 2", "Step 3"],
            "cases": [
                {"stem": "A short stem.", "clues": ["clue 1", "clue 2"], "answer": "Diagnosis", "teaching": "Teaching point"}
            ],
            "see_also": ["another-term"],
            "prerequisites": ["background-concept"],
            "actions": [
                {"label": "Open Link", "href": "https://entermedschool.com", "variant": "primary"}
            ],
            "sources": [
                {"title": "Good Reference", "url": "https://example.org/ref"}
            ],
            "credits": [
                {"email": "test@example.com", "role": "Author", "display": "Jane Doe"}
            ]
        }
        try:
            return json.dumps(example, ensure_ascii=False, indent=2)
        except Exception:
            return json.dumps(example, indent=2)

    def _on_load_example(self):
        try:
            obj = json.loads(self._example_json_text())
            self._populate_from(obj)
            tooltip("Example loaded — edit and submit")
        except Exception:
            pass

    def _populate_from(self, obj: dict):
        self.namesLE.setText(", ".join(obj.get("names", [])))
        self.definitionTE.setPlainText(obj.get("definition", ""))
        self.aliasesLE.setText(", ".join(obj.get("aliases", [])))
        self.abbrLE.setText(", ".join(obj.get("abbr", [])))
        try:
            primary = (obj.get("primary_tag") or (obj.get("tags") or [None])[0] or "").strip()
            if primary:
                idx = self.primaryTagCB.findText(primary)
                if idx < 0:
                    self.primaryTagCB.addItem(primary)
                    idx = self.primaryTagCB.findText(primary)
                if idx >= 0:
                    self.primaryTagCB.setCurrentIndex(idx)
        except Exception:
            pass
        self.whyTE.setPlainText(obj.get("why_it_matters", ""))
        def set_lines(te: QPlainTextEdit, arr):
            te.setPlainText("\n".join(arr or []))
        set_lines(self.hysiTE, obj.get("how_youll_see_it"))
        set_lines(self.psTE, obj.get("problem_solving"))
        # differentials: allow name|hint format
        diffs = obj.get("differentials") or []
        diff_lines = []
        for d in diffs:
            if isinstance(d, str):
                diff_lines.append(d)
            elif isinstance(d, dict):
                name = d.get("name") or d.get("id") or ""
                hint = d.get("hint") or ""
                diff_lines.append((name + (" | " + hint if hint else "")).strip())
        self.diffTE.setPlainText("\n".join(diff_lines))
        set_lines(self.tricksTE, obj.get("tricks"))
        set_lines(self.examTE, obj.get("exam_appearance"))
        set_lines(self.treatTE, obj.get("treatment"))
        set_lines(self.rfTE, obj.get("red_flags"))
        set_lines(self.algoTE, obj.get("algorithm"))
        set_lines(self.seeAlsoTE, obj.get("see_also"))
        set_lines(self.prereqTE, obj.get("prerequisites"))
        # sources: Title | URL format
        src_lines = []
        for s in obj.get("sources") or []:
            t = s.get("title") or s.get("url") or ""
            u = s.get("url") or ""
            if t and u:
                src_lines.append(f"{t} | {u}")
            elif t:
                src_lines.append(t)
        self.sourcesTE.setPlainText("\n".join(src_lines))
        # images
        try:
            lines = []
            for im in obj.get("images") or []:
                src = (im.get("src") or "").strip()
                alt = (im.get("alt") or "").strip()
                credit = im.get("credit") or {}
                ctext = (credit.get("text") or "").strip()
                chref = (credit.get("href") or "").strip()
                parts = [p for p in [src, alt, ctext, chref] if p]
                if parts:
                    lines.append(" | ".join(parts))
            self.imagesTE.setPlainText("\n".join(lines))
        except Exception:
            pass
        # cases
        try:
            lines = []
            for c in obj.get("cases") or []:
                stem = (c.get("stem") or "").strip()
                clues = "; ".join((c.get("clues") or []))
                ans = (c.get("answer") or "").strip()
                teach = (c.get("teaching") or "").strip()
                parts = [p for p in [stem, clues, ans, teach] if p]
                if parts:
                    lines.append(" | ".join(parts))
            self.casesTE.setPlainText("\n".join(lines))
        except Exception:
            pass
    def _build_payload(self) -> dict:
        names = self._csv_list(self.namesLE.text())
        definition = self.definitionTE.toPlainText().strip()
        obj = {}
        if names:
            obj["id"] = self._slugify(names[0])
            obj["names"] = names
        if definition:
            obj["definition"] = definition
        aliases = self._csv_list(self.aliasesLE.text());
        if aliases: obj["aliases"] = aliases
        abbr = self._csv_list(self.abbrLE.text());
        if abbr: obj["abbr"] = abbr
        # Primary tag from dropdown
        primary = (self.primaryTagCB.currentText() or "").strip()
        if primary:
            obj["primary_tag"] = primary
            obj["tags"] = [primary]
        if self.whyTE.toPlainText().strip(): obj["why_it_matters"] = self.whyTE.toPlainText().strip()
        for key, te in [
            ("how_youll_see_it", self.hysiTE),
            ("problem_solving", self.psTE),
            ("tricks", self.tricksTE),
            ("exam_appearance", self.examTE),
            ("treatment", self.treatTE),
            ("red_flags", self.rfTE),
            ("algorithm", self.algoTE),
        ]:
            vals = self._lines_list(te.toPlainText())
            if vals: obj[key] = vals
        diffs = self._parse_differentials(self.diffTE.toPlainText())
        if diffs: obj["differentials"] = diffs
        sources = self._parse_sources(self.sourcesTE.toPlainText())
        if sources: obj["sources"] = sources
        images = self._parse_images(self.imagesTE.toPlainText())
        if images: obj["images"] = images
        cases = self._parse_cases(self.casesTE.toPlainText())
        if cases: obj["cases"] = cases
        see_also = self._lines_list(self.seeAlsoTE.toPlainText())
        if see_also: obj["see_also"] = see_also
        prereq = self._lines_list(self.prereqTE.toPlainText())
        if prereq: obj["prerequisites"] = prereq
        creds = self._parse_credits(self.creditsTE.toPlainText())
        if creds: obj["credits"] = creds
        return obj

    def _on_preview(self):
        try:
            obj = self._build_payload()
            showText(json.dumps(obj, ensure_ascii=False, indent=2), title="Glossary Term JSON Preview")
        except Exception as e:
            showInfo(f"Preview failed: {e}")

    def _on_submit(self):
        try:
            self._validate_inline()
            obj = self._build_payload()
            names = obj.get("names") or []
            if not names:
                showInfo("Please enter at least one name for the term.")
                return
            # Block if an existing term with the same name exists, and offer to load it
            existing = self._find_existing_by_names(names)
            if existing:
                m = QMessageBox(self)
                m.setIcon(QMessageBox.Warning)
                n0 = names[0]
                m.setWindowTitle("Term Already Exists")
                m.setText(f"A glossary term named ‘{n0}’ already exists.\n\nDo you want to load it here to edit and then suggest an edit?")
                loadBtn = m.addButton("Load Existing", QMessageBox.AcceptRole)
                cancelBtn = m.addButton("Cancel", QMessageBox.RejectRole)
                m.exec()
                if m.clickedButton() == loadBtn:
                    try:
                        self._populate_from(existing)
                        tooltip("Loaded existing term — you can edit and submit as an edit suggestion.")
                    except Exception:
                        pass
                return
            title = f"Glossary term suggestion: {names[0]}"
            body_text = (
                "A user suggested a new glossary term via the Anki add-on.\n\n"
                "```json\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```\n"
            )
            base = "https://github.com/EnterMedSchool/Anki/issues/new"
            url = base + "?" + "title=" + urllib.parse.quote_plus(title) + "&body=" + urllib.parse.quote(body_text)
            openLink(url)
            tooltip("Opening GitHub to create your suggestion…")
            self.accept()
        except Exception as e:
            showInfo(f"Submit failed: {e}")

def on_show_suggest():
    try: SuggestTermDialog(mw).exec()
    except Exception as e: _log(f"SuggestTerm dialog failed: {e}")

# ------------------------------ Menu ------------------------------------------

def _ensure_logo_icon() -> QIcon:
    try: return QIcon(LOGO_PATH) if os.path.exists(LOGO_PATH) else QIcon()
    except Exception: return QIcon()

def _build_menu():
    try:
        bar = mw.menuBar()
        icon = QIcon(LOGO_PATH) if os.path.exists(LOGO_PATH) else QIcon()

        # Find or create a single top-level EMS menu (idempotent)
        menu = None
        try:
            for act in list(bar.actions()):
                try:
                    m = act.menu()
                except Exception:
                    m = None
                if not m:
                    continue
                try:
                    title = m.title()
                except Exception:
                    title = None
                try:
                    oname = m.objectName()
                except Exception:
                    oname = None
                if oname == "ems_menu" or title == "EnterMedSchool":
                    if menu is None:
                        menu = m
                    else:
                        # Remove duplicates
                        try: bar.removeAction(act)
                        except Exception: pass
            if menu is None:
                menu = bar.addMenu("EnterMedSchool")
                try: menu.setObjectName("ems_menu")
                except Exception: pass
        except Exception:
            # Fallback: just add one
            menu = bar.addMenu("EnterMedSchool")
            try: menu.setObjectName("ems_menu")
            except Exception: pass

        # Ensure icon and rebuild content cleanly
        try: menu.setIcon(icon)
        except Exception: pass
        try: menu.clear()
        except Exception: pass

        def run_update(background=True):
            def worker():
                ok, summary, details = update_from_remote(bypass_cache=True)
                def show():
                    if ok:
                        if details: showText(details, title="EnterMedSchool — Update Report"); showInfo(summary)
                    else:
                        showText(summary + "\n\n" + details, title="EnterMedSchool — Update Error")
                try: mw.taskman.run_on_main(show)
                except Exception as e: _log(f"show after update failed: {e}")
            if background: threading.Thread(target=worker, daemon=True).start()
            else: worker()

        a1 = QAction("Check for Updates Now (Bypass Cache)", mw)
        qconnect(a1.triggered, lambda: run_update(background=True)); menu.addAction(a1)
        a2 = QAction("Force Full Resync (Bypass Cache)", mw)
        qconnect(a2.triggered, lambda: run_update(background=True)); menu.addAction(a2)

        menu.addSeparator()
        aDiag = QAction("Diagnostics: Show last fetched index", mw)
        def show_diag():
            raw = "(no file)"; parsed = {}
            try:
                if os.path.exists(FETCHED_INDEX_RAW): raw = open(FETCHED_INDEX_RAW,"r",encoding="utf-8").read()
                if os.path.exists(FETCHED_INDEX_PARSED): parsed = json.load(open(FETCHED_INDEX_PARSED,"r",encoding="utf-8"))
            except Exception as e: raw = f"(error reading diagnostics: {e})"
            showText("Parsed index:\n\n"+json.dumps(parsed, ensure_ascii=False, indent=2)+"\n\nRaw:\n\n"+raw[:4000], title="EMS — Diagnostics")
        qconnect(aDiag.triggered, show_diag); menu.addAction(aDiag)

        # Logs utilities
        aLog = QAction("Open Log Folder", mw)
        qconnect(aLog.triggered, lambda: openFolder(STATE_DIR))
        menu.addAction(aLog)
        aVerbose = QAction("Verbose logging (DEBUG)", mw)
        try: aVerbose.setCheckable(True)
        except Exception: pass
        try: aVerbose.setChecked(str(get_config().get("log_level","INFO")).upper()=="DEBUG")
        except Exception: pass
        def _toggle_verbose():
            try:
                cfg = get_config(); cfg["log_level"] = "DEBUG" if aVerbose.isChecked() else "INFO"; write_config(cfg)
                try: tooltip("Verbose logging enabled" if aVerbose.isChecked() else "Verbose logging disabled")
                except Exception: pass
            except Exception: pass
        qconnect(aVerbose.triggered, _toggle_verbose)
        menu.addAction(aVerbose)

        menu.addSeparator()
        a3 = QAction("Appearance & Settings…", mw); qconnect(a3.triggered, on_show_options); menu.addAction(a3)
        a4 = QAction("Open Data Folder", mw); qconnect(a4.triggered, lambda: openFolder(USER_FILES_DIR)); menu.addAction(a4)
        menu.addSeparator()
        aSuggest = QAction("Suggest a Glossary Term…", mw)
        qconnect(aSuggest.triggered, on_show_suggest); aSuggest.setText("Create a Glossary Term")
        menu.addAction(aSuggest)

        # Live (PocketBase) actions
        menu.addSeparator()
        liveMenu = menu.addMenu("Live (PocketBase)")
        aLogin = QAction("Login...", mw)
        qconnect(aLogin.triggered, lambda: PocketBaseLoginDialog(mw).exec())
        liveMenu.addAction(aLogin)
        aRegister = QAction("Register...", mw)
        def _open_register():
            try:
                base = (get_config().get("pb_base_url") or "https://anki.entermedschool.com").strip()
                PocketBaseRegisterDialog(mw, base).exec()
            except Exception as e:
                _log(f"Register dialog failed: {e}")
        qconnect(aRegister.triggered, _open_register)
        liveMenu.addAction(aRegister)
        aLogout = QAction("Logout", mw)
        def _do_logout():
            try:
                from . import ems_pocketbase as PB
                PB.logout()
                tooltip("Logged out.")
            except Exception:
                pass
        qconnect(aLogout.triggered, _do_logout)
        liveMenu.addAction(aLogout)
        aWho = QAction("Who am I?", mw)
        def _who():
            try:
                from . import ems_pocketbase as PB
                ok, msg = PB.whoami()
                showInfo(msg if ok else ("Not logged in: " + msg))
            except Exception as e:
                showInfo(f"WhoAmI error: {e}")
        qconnect(aWho.triggered, _who)
        liveMenu.addAction(aWho)

        aProfile = QAction("Edit Profile...", mw)
        def _profile():
            try:
                PocketBaseProfileDialog(mw).exec()
            except Exception as e:
                _log(f"Profile dialog failed: {e}")
        qconnect(aProfile.triggered, _profile)
        liveMenu.addAction(aProfile)

        # Dev helper: one-click seed of glossary terms into PocketBase (only if dev flag is enabled)
        def _dev_enabled() -> bool:
            try:
                cfg = get_config() or {}
                if cfg.get("dev_tools_enabled"):
                    return True
            except Exception:
                pass
            try:
                # Enable via flag file: user_files/pocketbase/dev.flag
                flag = os.path.join(USER_FILES_DIR, "pocketbase", "dev.flag")
                return os.path.exists(flag)
            except Exception:
                return False

        if _dev_enabled():
            aSeed = QAction("Seed Terms Now (dev)", mw)
            def _seed():
                try:
                    from . import ems_pocketbase as PB
                    base = get_config().get("pb_base_url", "http://127.0.0.1:8090")
                    # Auto-login as test user if not logged in
                    ok, _ = PB.whoami()
                    if not ok:
                        PB.login(base, "test@test.com", "12345678")
                    ok2, msg2 = PB.seed_terms_all()
                    if ok2:
                        tooltip("Seeding triggered.")
                    else:
                        showInfo("Seed failed: " + (msg2 or "Unknown error"))
                except Exception as e:
                    showInfo(f"Seed error: {e}")
            qconnect(aSeed.triggered, _seed)
            liveMenu.addAction(aSeed)

        # Connectivity helpers and status
        liveMenu.addSeparator()
        aReconnect = QAction("Try Reconnect (Go Online)", mw)
        def _reconn():
            try:
                from . import ems_pocketbase as PB
                PB.try_reconnect(background=True)
                tooltip("Attempting reconnect...")
                # Rebuild the menu shortly after to reflect status
                import threading, time as _t
                def _later():
                    try: _t.sleep(0.8)
                    except Exception: pass
                    try: mw.taskman.run_on_main(_build_menu)
                    except Exception:
                        try: _build_menu()
                        except Exception: pass
                threading.Thread(target=_later, daemon=True).start()
            except Exception:
                pass
        qconnect(aReconnect.triggered, _reconn)
        liveMenu.addAction(aReconnect)

        # Status indicator and disable network-only actions when offline
        try:
            from . import ems_pocketbase as PB
            offline = bool(PB.is_offline())
            auth = PB.load_auth() or {}
            email = ((auth.get('record') or {}).get('email')) or None
            # Read last offline reason for tooltip if present
            try:
                import json
                stp = os.path.join(STATE_DIR, "offline_state.json")
                reason = ""
                if os.path.exists(stp):
                    reason = (json.load(open(stp, "r", encoding="utf-8")) or {}).get("reason") or ""
            except Exception:
                reason = ""
        except Exception:
            offline = False; email = None; reason = ""
        label = "Status: Offline" if offline else ("Status: Online" + (f" ({email})" if email else ""))
        aStatus = QAction(label, mw)
        try:
            if reason:
                aStatus.setToolTip(reason)
        except Exception:
            pass
        aStatus.setEnabled(False)
        liveMenu.addAction(aStatus)

        # Gray out items that require network
        try:
            aWho.setEnabled(not offline)
            aProfile.setEnabled(not offline)
        except Exception:
            pass
    except Exception as e:
        _log(f"build menu failed: {e}")

def _on_profile_open():
    _build_menu(); 
    try: 
        # try to clear offline if PB is reachable
        try:
            from . import ems_pocketbase as PB
            PB.try_reconnect(background=True)
        except Exception:
            pass
        # Show login prompt once per session if not logged in and not suppressed
        try:
            _maybe_prompt_login_once()
        except Exception:
            pass
        # Refresh menu shortly after startup
        try:
            import threading, time as _t
            def _later():
                try: _t.sleep(0.8)
                except Exception: pass
                try: mw.taskman.run_on_main(_build_menu)
                except Exception:
                    try: _build_menu()
                    except Exception: pass
            threading.Thread(target=_later, daemon=True).start()
        except Exception:
            pass
        # auto update (respect last checked)
        last = int(get_config().get("last_update_check", 0))
        if int(time.time()) - last >= AUTO_UPDATE_DAYS*86400:
            threading.Thread(target=lambda: update_from_remote(bypass_cache=True), daemon=True).start()
    except Exception as e:
        _log(f"auto update failed: {e}")
gui_hooks.profile_did_open.append(_on_profile_open)

# --------------------------- Live: PocketBase ---------------------------------

class PocketBaseLoginDialog(QDialog):
    def __init__(self, parent=None, offer_never: bool = False):
        super().__init__(parent or mw)
        self.setWindowTitle("PocketBase Login")
        self.setMinimumWidth(440)
        self.setWindowIcon(_ensure_logo_icon())
        lay = QVBoxLayout(self)
        cfg = get_config()
        row1 = QHBoxLayout(); row1.addWidget(QLabel("Base URL:"))
        self.baseLE = QLineEdit(cfg.get("pb_base_url", "https://anki.entermedschool.com"))
        row1.addWidget(self.baseLE, 1); lay.addLayout(row1)
        row2 = QHBoxLayout(); row2.addWidget(QLabel("Email:"))
        self.emailLE = QLineEdit("")
        row2.addWidget(self.emailLE, 1); lay.addLayout(row2)
        row3 = QHBoxLayout(); row3.addWidget(QLabel("Password:"))
        self.passLE = QLineEdit("")
        try:
            # PyQt6 nests enums under EchoMode
            EchoMode = getattr(QLineEdit, "EchoMode", None)
            if EchoMode is not None:
                self.passLE.setEchoMode(EchoMode.Password)
            else:
                self.passLE.setEchoMode(QLineEdit.Password)
        except Exception:
            # Fallback - show as plain text rather than crash
            pass
        row3.addWidget(self.passLE, 1); lay.addLayout(row3)
        # Optional: never show again
        self.neverCB = None
        if offer_never:
            try:
                self.neverCB = QCheckBox("Never show this again")
                lay.addWidget(self.neverCB)
            except Exception:
                self.neverCB = None
        # Buttons
        btns = QHBoxLayout(); btns.addStretch(1)
        createBtn = QPushButton("Create account")
        loginBtn = QPushButton("Login")
        cancelBtn = QPushButton("Cancel")
        btns.addWidget(createBtn)
        btns.addWidget(loginBtn)
        btns.addWidget(cancelBtn)
        lay.addLayout(btns)
        def do_login():
            try:
                base = (self.baseLE.text() or "https://anki.entermedschool.com").strip()
                email = (self.emailLE.text() or "").strip()
                pwd = self.passLE.text() or ""
                if not email or not pwd:
                    showInfo("Enter email and password."); return
                from . import ems_pocketbase as PB
                ok, msg = PB.login(base, email, pwd)
                if ok:
                    cfg = get_config(); cfg["pb_base_url"] = base; write_config(cfg)
                    tooltip("Logged in.")
                    # Kick off a background Tamagotchi sync right after login
                    try:
                        from .LeoTamagotchi import gui as _leo_tamagotchi
                        _leo_tamagotchi.sync_now()
                    except Exception:
                        pass
                    try:
                        _build_menu()
                    except Exception:
                        pass
                    # Persist suppression if requested
                    try:
                        if self.neverCB is not None and self.neverCB.isChecked():
                            cfg = get_config(); cfg["pb_login_prompt_never"] = True; write_config(cfg)
                    except Exception:
                        pass
                    self.accept()
                else:
                    showInfo("Login failed: " + msg)
            except Exception as e:
                showInfo(f"Login error: {e}")
        def do_create():
            try:
                base = (self.baseLE.text() or "https://anki.entermedschool.com").strip()
                dlg = PocketBaseRegisterDialog(mw, base)
                if dlg.exec():
                    # Auto-fill email; attempt auto-login
                    try:
                        em = dlg.emailLE.text() or ""
                        pw = dlg.passLE.text() or ""
                        if em and pw:
                            from . import ems_pocketbase as PB
                            ok, _ = PB.login(base, em, pw)
                            if ok:
                                tooltip("Logged in.")
                                try:
                                    _build_menu()
                                except Exception:
                                    pass
                                # Persist suppression if requested
                                try:
                                    if self.neverCB is not None and self.neverCB.isChecked():
                                        cfg = get_config(); cfg["pb_login_prompt_never"] = True; write_config(cfg)
                                except Exception:
                                    pass
                                self.accept(); return
                    except Exception:
                        pass
            except Exception as e:
                showInfo(f"Register error: {e}")
        qconnect(loginBtn.clicked, do_login)
        qconnect(createBtn.clicked, do_create)
        def do_cancel():
            try:
                if self.neverCB is not None and self.neverCB.isChecked():
                    cfg = get_config(); cfg["pb_login_prompt_never"] = True; write_config(cfg)
            except Exception:
                pass
            self.reject()
        qconnect(cancelBtn.clicked, do_cancel)

class PocketBaseProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("PocketBase Profile")
        self.setMinimumWidth(480)
        self.setWindowIcon(_ensure_logo_icon())
        lay = QVBoxLayout(self)
        row1 = QHBoxLayout(); row1.addWidget(QLabel("Display name:"))
        self.displayLE = QLineEdit(""); row1.addWidget(self.displayLE, 1); lay.addLayout(row1)
        row2 = QHBoxLayout(); row2.addWidget(QLabel("Avatar URL:"))
        self.avatarLE = QLineEdit(""); row2.addWidget(self.avatarLE, 1); lay.addLayout(row2)
        row3 = QHBoxLayout(); row3.addWidget(QLabel("About:"))
        self.aboutTE = QPlainTextEdit(""); row3.addWidget(self.aboutTE, 1); lay.addLayout(row3)
        btns = QHBoxLayout(); btns.addStretch(1)
        saveBtn = QPushButton("Save"); cancelBtn = QPushButton("Close")
        btns.addWidget(saveBtn); btns.addWidget(cancelBtn); lay.addLayout(btns)

        def load():
            try:
                from . import ems_pocketbase as PB
                ok, obj = PB.profile_get()
                if ok and isinstance(obj, dict):
                    self.displayLE.setText(obj.get("display_name",""))
                    self.avatarLE.setText(obj.get("avatar_url",""))
                    self.aboutTE.setPlainText(obj.get("about",""))
            except Exception as e:
                showInfo(f"Load profile failed: {e}")
        def save():
            try:
                from . import ems_pocketbase as PB
                ok, msg = PB.profile_upsert(self.displayLE.text().strip(), self.avatarLE.text().strip(), self.aboutTE.toPlainText().strip())
                if ok:
                    tooltip("Profile saved.")
                    self.accept()
                else:
                    showInfo("Save failed: " + msg)
            except Exception as e:
                showInfo(f"Save failed: {e}")
        load()
        qconnect(saveBtn.clicked, save)
        qconnect(cancelBtn.clicked, self.reject)


# --------------------------- Register dialog ---------------------------------

class PocketBaseRegisterDialog(QDialog):
    def __init__(self, parent=None, base_url: str = ""):
        super().__init__(parent or mw)
        self.setWindowTitle("Create Account")
        self.setMinimumWidth(480)
        self.setWindowIcon(_ensure_logo_icon())
        lay = QVBoxLayout(self)
        cfg = get_config()
        row1 = QHBoxLayout(); row1.addWidget(QLabel("Base URL:"))
        self.baseLE = QLineEdit(base_url or cfg.get("pb_base_url", "https://anki.entermedschool.com"))
        row1.addWidget(self.baseLE, 1); lay.addLayout(row1)
        row2 = QHBoxLayout(); row2.addWidget(QLabel("Email:"))
        self.emailLE = QLineEdit(""); row2.addWidget(self.emailLE, 1); lay.addLayout(row2)
        row3 = QHBoxLayout(); row3.addWidget(QLabel("Password:"))
        self.passLE = QLineEdit(""); row3.addWidget(self.passLE, 1); lay.addLayout(row3)
        try:
            EchoMode = getattr(QLineEdit, "EchoMode", None)
            if EchoMode is not None:
                self.passLE.setEchoMode(EchoMode.Password)
            else:
                self.passLE.setEchoMode(QLineEdit.Password)
        except Exception:
            pass
        row4 = QHBoxLayout(); row4.addWidget(QLabel("Confirm password:"))
        self.pass2LE = QLineEdit(""); row4.addWidget(self.pass2LE, 1); lay.addLayout(row4)
        try:
            EchoMode = getattr(QLineEdit, "EchoMode", None)
            if EchoMode is not None:
                self.pass2LE.setEchoMode(EchoMode.Password)
            else:
                self.pass2LE.setEchoMode(QLineEdit.Password)
        except Exception:
            pass
        hint = QLabel("Your account is used to sync favorites, ratings, and comments.")
        try:
            hint.setStyleSheet("color: #a4afbf;")
        except Exception:
            pass
        lay.addWidget(hint)
        btns = QHBoxLayout(); btns.addStretch(1)
        okBtn = QPushButton("Create account"); cancelBtn = QPushButton("Cancel")
        btns.addWidget(okBtn); btns.addWidget(cancelBtn); lay.addLayout(btns)
        def do_register():
            try:
                base = (self.baseLE.text() or "https://anki.entermedschool.com").strip()
                email = (self.emailLE.text() or "").strip()
                pw = self.passLE.text() or ""
                pw2 = self.pass2LE.text() or ""
                if not email or not pw:
                    showInfo("Enter email and password."); return
                if pw != pw2:
                    showInfo("Passwords do not match."); return
                from . import ems_pocketbase as PB
                ok, msg = PB.register(base, email, pw)
                if ok:
                    cfg = get_config(); cfg["pb_base_url"] = base; write_config(cfg)
                    tooltip(msg)
                    self.accept()
                else:
                    showInfo("Registration failed: " + (msg or "Unknown error"))
            except Exception as e:
                showInfo(f"Registration error: {e}")
        qconnect(okBtn.clicked, do_register)
        qconnect(cancelBtn.clicked, self.reject)

# ------------------------ Startup login prompt -------------------------------

def _is_logged_in() -> bool:
    try:
        from . import ems_pocketbase as PB
        a = PB.load_auth() or {}
        return bool(a.get("token"))
    except Exception:
        return False

def _maybe_prompt_login_once() -> None:
    global _login_prompt_shown
    if _login_prompt_shown:
        return
    try:
        cfg = get_config() or {}
        if cfg.get("pb_login_prompt_never"):
            return
    except Exception:
        pass
    # Only prompt if not logged in
    if _is_logged_in():
        _login_prompt_shown = True
        return
    _login_prompt_shown = True
    try:
        PocketBaseLoginDialog(mw, offer_never=True).exec()
    except Exception:
        pass
