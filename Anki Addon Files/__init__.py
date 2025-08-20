
from __future__ import annotations
import json, os, re, time, urllib.request, urllib.error, threading, shutil, html, uuid, hashlib
from typing import Any, Dict, List, Tuple
from aqt import mw, gui_hooks
from aqt.qt import QAction, qconnect, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox, QLineEdit, QIcon
from aqt.utils import openFolder, showInfo, showText, tooltip
from anki.notes import Note

MODULE = __name__
ADDON_DIR = os.path.dirname(__file__)
WEB_DIR = os.path.join(ADDON_DIR, "web")
USER_FILES_DIR = os.path.join(ADDON_DIR, "user_files")
TERMS_DIR = os.path.join(USER_FILES_DIR, "terms")
STATE_DIR = os.path.join(USER_FILES_DIR, "_state")
LOG_PATH = os.path.join(USER_FILES_DIR, "log.txt")
LAST_INDEX_SNAPSHOT = os.path.join(STATE_DIR, "last_index.json")
LAST_DIFF = os.path.join(STATE_DIR, "last_diff.json")
LAST_VERSION = os.path.join(STATE_DIR, "version.txt")
SEEN_VERSION = os.path.join(STATE_DIR, "seen_version.txt")
TAGS_JSON_PATH = os.path.join(STATE_DIR, "tags.json")
FETCHED_INDEX_RAW = os.path.join(STATE_DIR, "fetched_index_raw.json")
FETCHED_INDEX_PARSED = os.path.join(STATE_DIR, "fetched_index_parsed.json")
LOGO_PATH = os.path.join(WEB_DIR, "ems_logo.png")

RAW_INDEX = "https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary/index.json"
RAW_TERMS_BASE = "https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary/terms"

AUTO_UPDATE_DAYS = 1

DEFAULT_CONFIG = {
    "tooltip_width_px": 640,
    "popup_font_px": 16,
    "hover_mode": "hover",
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

    # NEW: Learn cards
    "learn_target": "dedicated",           # "dedicated" or "current"
    "learn_deck_name": "EnterMedSchool — Terms"
}

def _log(msg: str):
    try:
        os.makedirs(USER_FILES_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")
    except Exception:
        pass

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
        greek = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ"}
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
        return {"terms": terms, "meta": meta, "claims": claims_on_card}

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
        return {"terms": terms, "meta": meta, "claims": {}}

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
        details = ""
        if errors:
            details = "Some files were skipped:\n\n" + "\n".join(f"• {fn}: {msg}" for fn, msg in errors.items())
            details += "\n\nValid files were applied successfully."
        return True, summary, details
    except Exception as e:
        details = f"Update failed.\n\n{index_url} → {e}\n\nTip: open the URL above in a browser and verify it's valid JSON."
        return False, "Update failed — see details.", details
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
    if not want: return

    cfg = get_config()
    pkg = mw.addonManager.addonFromModule(MODULE)
    web_content.css.append(f"/_addons/{pkg}/web/popup.css")
    web_content.js.append(f"/_addons/{pkg}/web/popup.js")

    width = int(cfg.get("tooltip_width_px", 640))
    font_px = int(cfg.get("popup_font_px", 16))
    hover_mode = cfg.get("hover_mode", "hover")
    hover_delay_ms = int(cfg.get("hover_delay_ms", 120))
    click_anywhere = bool(cfg.get("open_with_click_anywhere", True))

    theme = f"""
    <style> .ems-popover {{ max-width: {width}px; font-size: {font_px}px; }} </style>
    <script>window.EMS_CFG = {{
        hoverMode: {json.dumps(hover_mode)},
        hoverDelay: {hover_delay_ms},
        clickAnywhere: {str(click_anywhere).lower()}
    }};</script>
    """
    web_content.head += theme

gui_hooks.webview_will_set_content.append(on_webview_will_set_content)

# ---------------------------- Popup Rendering ---------------------------------

def _brand_block_html(tid: str) -> str:
    pkg = mw.addonManager.addonFromModule(MODULE)
    return ("<div class='ems-brand'><div class='ems-brand-inner'>"
            f"<img class='ems-logo' src='/_addons/{pkg}/web/ems_logo.png' alt='EMS'/> "
            "<a class='ems-site' href='https://entermedschool.com' target='_blank' rel='noopener'><span class='ems-brand-name'>EnterMedSchool</span></a> "
            "<span class='ems-by'>&nbsp;by <a class='ems-contact' href='mailto:contact@arihoresh.com'>Ari Horesh</a></span>"
            "</div><div class='ems-small'><a class='ems-suggest' href='https://github.com/EnterMedSchool/Anki/issues/new?title=Glossary%20edit%20suggestion%20for%20"
            + html.escape(tid) + "' target='_blank' rel='noopener'>Suggest edit ✍️</a></div></div>")

def _sanitize_html(value: str) -> str:
    return GLOSSARY._sanitize_html(value)

def _bullets(items):
    items = [x for x in (items or []) if x]
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>"

def _section_html(name: str, icon: str, content_html: str, sec_id: str, extra_class: str = "") -> str:
    if not content_html:
        return f"<details class='ems-section is-disabled {extra_class}' data-sec='{sec_id}'><summary>{icon} {name}<button class='ems-learn' disabled title='No content'>＋ Learn</button></summary></details>"
    return f"<details open class='ems-section {extra_class}' data-sec='{sec_id}'><summary>{icon} {name}<button class='ems-learn' title='Add this as a card'>＋ Learn</button></summary>{content_html}</details>"

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
    title = (t.get("names") or [t.get("id")])[0]
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
    parts.append(f"<h3>{html.escape(title)} <span class='ems-emoji'>🧠</span></h3>")
    if definition: parts.append(f"<p class='ems-lead'>{html.escape(definition)}</p>")

    parts.append(_section_html("Why it matters", "🎯", f"<p>{html.escape(t.get('why_it_matters',''))}</p>" if t.get("why_it_matters") else "", "why_it_matters"))
    parts.append(_section_html("How you'll see it", "🩺", _bullets(t.get("how_youll_see_it")), "how_youll_see_it"))
    parts.append(_section_html("Problem solving — quick approach", "🧩", _bullets(t.get("problem_solving")), "problem_solving"))
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
        parts.append(_section_html("Differentials & Look‑alikes", "🔀", "<ul>" + "".join(items) + "</ul>", "differentials"))
    else:
        parts.append(_section_html("Differentials & Look‑alikes", "🔀", "", "differentials"))
    parts.append(_section_html("Tricks to avoid traps", "🧠", _bullets(t.get("tricks")), "tricks"))
    parts.append(_section_html("How exams like to ask it", "📝", _bullets(t.get("exam_appearance")), "exam_appearance"))
    parts.append(_section_html("Treatment — exam/wards version", "💊", _bullets(t.get("treatment")), "treatment", "is-success"))
    parts.append(_section_html("Red flags — do not miss", "🚨", _bullets(t.get("red_flags")), "red_flags", "is-danger"))
    parts.append(_section_html("1‑minute algorithm", "🛣️", _algo_html(t.get("algorithm") or []), "algorithm", "is-algo"))
    parts.append(_section_html("Mini‑cases", "🧪", _cases_html(t.get("cases") or []), "cases"))

    related = []
    for sid in (t.get("see_also") or []): related.append(f"<a href='#' data-ems-link='{sid}'>[{sid}]</a>")
    for sid in (t.get("prerequisites") or []): related.append(f"<a href='#' data-ems-link='{sid}'>[{sid}]</a>")
    if related: parts.append("<div class='ems-related ems-section'>🔗 " + " · ".join(related) + "</div>")
    if t.get("sources"):
        srcs = " · ".join(f"<a href='{html.escape(s.get('url',''))}' target='_blank' rel='noopener'>{html.escape(s.get('title','Source'))}</a>" for s in (t.get('sources') or []) if s.get('url'))
        parts.append(f"<div class='ems-sources ems-section'>📎 {srcs}</div>")
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
        return {"id": t.get("id"), "html": "<div class='ems-body'>" + core + "</div>", "title": (t.get("names") or [t.get("id")])[0]}
    html_out = _term_html_from_schema(t); title = (t.get("names") or [t.get("id")])[0]
    return {"id": t.get("id"), "html": html_out, "title": title}
GlossaryStore.popup_payload = GlossaryStore_popup_payload

# ---------------------------- Learning cards ----------------------------------

LEARN_SECTIONS = [
    ("why_it_matters", "Why it matters"),
    ("how_youll_see_it", "How you'll see it"),
    ("problem_solving", "Problem solving — quick approach"),
    ("differentials", "Differentials & Look‑alikes"),
    ("tricks", "Tricks to avoid traps"),
    ("exam_appearance", "How exams like to ask it"),
    ("treatment", "Treatment — exam/wards version"),
    ("red_flags", "Red flags — do not miss"),
    ("algorithm", "1‑minute algorithm"),
    ("cases", "Mini‑cases"),
]

def _section_content_html(t: Dict[str, Any], sec_id: str) -> str:
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
    try:
        from aqt.reviewer import Reviewer
        if not isinstance(context, Reviewer): return handled
    except Exception:
        return handled
    if not isinstance(message, str) or not message.startswith("ems_glossary:"): return handled
    parts = message.split(":", 3)
    cmd = parts[1]

    if cmd == "get":
        term_id = parts[2].strip()
        return (True, GLOSSARY.popup_payload(term_id))

    if cmd == "pin":
        tid = parts[2].strip()
        payload = GLOSSARY.popup_payload(tid)
        pid = f"pin{int(time.time()*1000)%100000}"
        obj = {"id": pid, "tid": tid, "title": payload.get("title") or tid, "html": payload.get("html",""), "x": 60, "y": 60}
        return (True, obj)

    if cmd == "learn":
        tid = parts[2].strip()
        sec = parts[3].strip() if len(parts) > 3 else ""
        t = GLOSSARY.terms_by_id.get(tid)
        if not t or not sec: return (True, {"ok": False, "message": "Missing content."})
        ok, uid = _add_learn_card(t, sec, context)
        if ok: 
            mw.reset()
            return (True, {"ok": True, "message": "Added ✓"})
        else:
            if uid == "empty": return (True, {"ok": False, "message": "Nothing to add."})
            return (True, {"ok": False, "message": "Already added."})

    if cmd == "learnall":
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
        self.setWindowTitle("EnterMedSchool — Glossary Settings ✨")
        self.setMinimumWidth(540)
        self.setWindowIcon(_ensure_logo_icon())
        self._cfg = get_config()

        lay = QVBoxLayout(self)
        header = QHBoxLayout()
        logo = QLabel(f"<img width=24 height=24 src='/_addons/{mw.addonManager.addonFromModule(MODULE)}/web/ems_logo.png'>")
        title = QLabel("<b>EnterMedSchool — Glossary Settings</b>  🚀")
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
        save = QPushButton("Save ✅"); reset = QPushButton("Reset ↩️"); close = QPushButton("Close")
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
        write_config(cfg); showInfo("Saved. ✨")

    def _on_reset(self):
        cfg = get_config()
        for k, v in DEFAULT_CONFIG.items():
            if k == "last_update_check": continue
            cfg[k] = v
        write_config(cfg); showInfo("Reset to defaults.")

def on_show_options():
    try: SettingsDialog(mw).exec()
    except Exception as e: _log(f"Settings dialog failed: {e}")

# ------------------------------ Menu ------------------------------------------

def _ensure_logo_icon() -> QIcon:
    try: return QIcon(LOGO_PATH) if os.path.exists(LOGO_PATH) else QIcon()
    except Exception: return QIcon()

def _build_menu():
    try:
        bar = mw.menuBar()
        icon = QIcon(LOGO_PATH) if os.path.exists(LOGO_PATH) else QIcon()
        menu = bar.addMenu("EnterMedSchool")
        try: menu.setIcon(icon)
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

        a1 = QAction("🔄  Check for Updates Now (Bypass Cache)", mw)
        qconnect(a1.triggered, lambda: run_update(background=True)); menu.addAction(a1)
        a2 = QAction("🧹  Force Full Resync (Bypass Cache)", mw)
        qconnect(a2.triggered, lambda: run_update(background=True)); menu.addAction(a2)

        menu.addSeparator()
        aDiag = QAction("🧪  Diagnostics: Show last fetched index", mw)
        def show_diag():
            raw = "(no file)"; parsed = {}
            try:
                if os.path.exists(FETCHED_INDEX_RAW): raw = open(FETCHED_INDEX_RAW,"r",encoding="utf-8").read()
                if os.path.exists(FETCHED_INDEX_PARSED): parsed = json.load(open(FETCHED_INDEX_PARSED,"r",encoding="utf-8"))
            except Exception as e: raw = f"(error reading diagnostics: {e})"
            showText("Parsed index:\n\n"+json.dumps(parsed, ensure_ascii=False, indent=2)+"\n\nRaw:\n\n"+raw[:4000], title="EMS — Diagnostics")
        qconnect(aDiag.triggered, show_diag); menu.addAction(aDiag)

        menu.addSeparator()
        a3 = QAction("🎨  Appearance & Settings…", mw); qconnect(a3.triggered, on_show_options); menu.addAction(a3)
        a4 = QAction("📂  Open Data Folder", mw); qconnect(a4.triggered, lambda: openFolder(USER_FILES_DIR)); menu.addAction(a4)
    except Exception as e:
        _log(f"build menu failed: {e}")

def _on_profile_open():
    _build_menu(); 
    try: 
        # auto update (respect last checked)
        last = int(get_config().get("last_update_check", 0))
        if int(time.time()) - last >= AUTO_UPDATE_DAYS*86400:
            threading.Thread(target=lambda: update_from_remote(bypass_cache=True), daemon=True).start()
    except Exception as e:
        _log(f"auto update failed: {e}")
gui_hooks.profile_did_open.append(_on_profile_open)
