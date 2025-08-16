
# EMS Glossary Hover — MVP37d
# - Fix: string literal that broke on Windows/py3.9 (no backslash-escaped f-strings).
# - Keep: robust Learn notetype creation/repair, scroll-trap, drawer CSS.
# - Drawer ('G') fully styled. Tag-colored highlights. Empty sections disabled.
from __future__ import annotations

import os, json, re, time, traceback, html, urllib.request
from typing import Dict, List, Tuple, Any

from aqt import mw, gui_hooks
from aqt.qt import QAction, QIcon, QFileDialog, QDialog, QVBoxLayout, QFormLayout, QSpinBox, QComboBox, QCheckBox, QLineEdit, QPushButton, QLabel, QWidget, QHBoxLayout
from aqt.utils import showInfo, tooltip

ADDON_DIR = os.path.dirname(__file__)
WEB_DIR = os.path.join(ADDON_DIR, "web")
USER_DIR = os.path.join(ADDON_DIR, "user_files")
TERMS_DIR = os.path.join(USER_DIR, "terms")
for d in (USER_DIR, TERMS_DIR):
    os.makedirs(d, exist_ok=True)

# Remote data locations (your GitHub)
INDEX_URL = "https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary/index.json"
TAGS_URL  = "https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary/tags.json"
TERMS_BASE = "https://raw.githubusercontent.com/EnterMedSchool/Anki/main/glossary"

# Config
CFG_PATH = os.path.join(USER_DIR, "config.json")
DEFAULT_CFG = {
    "popup_width": 640,
    "font_px": 16,
    "open_mode": "hover",         # "hover" or "click"
    "hover_delay": 120,
    "max_per_card": 80,
    "click_anywhere": True,
    "learn_target": "dedicated",  # "dedicated" or "current"
    "learn_deck": "EnterMedSchool — Terms",
    "scan_fields": "Front,Back,Extra",
}

def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        c = DEFAULT_CFG.copy(); c.update(user); return c
    except Exception:
        return DEFAULT_CFG.copy()

def save_cfg(c):
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)

CFG = load_cfg()

# In-memory data
TAGS_PATH = os.path.join(USER_DIR, "tags.json")
TAGS: Dict[str, Dict[str, str]] = {}
GLOSSARY: Dict[str, Dict[str, Any]] = {}

# --- Utilities ---------------------------------------------------------------
def _http_text(url: str, timeout=20) -> str:
    req = urllib.request.Request(url + ("?t=%d" % int(time.time())), headers={"User-Agent": "ems-anki/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def _http_json(url: str, timeout=20) -> Any:
    return json.loads(_http_text(url, timeout=timeout))

def _sanitize_html(s: str) -> str:
    s = s or ""
    # [[term-id]] -> clickable link inside popup/pins
    s = re.sub(r"\[\[([a-z0-9\-]+)\]\]", r"<a href='#' data-ems-link='\1'>\1</a>", s, flags=re.I)
    return s

def _load_local_tags():
    global TAGS
    try:
        with open(TAGS_PATH, "r", encoding="utf-8") as f:
            TAGS = json.load(f)
    except Exception:
        TAGS = {}

def _load_local_terms():
    global GLOSSARY
    GLOSSARY = {}
    if not os.path.isdir(TERMS_DIR): return
    for fn in os.listdir(TERMS_DIR):
        if not fn.lower().endswith(".json"): continue
        p = os.path.join(TERMS_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            tid = d.get("id") or os.path.splitext(fn)[0]
            d["id"] = tid
            d["title"] = d.get("title") or tid
            d["synonyms"] = d.get("synonyms") or []
            secs = d.get("sections") or {}
            for k,v in list(secs.items()):
                if isinstance(v, list):
                    secs[k] = "<ul>" + "".join("<li>%s</li>" % _sanitize_html(x) for x in v) + "</ul>"
                else:
                    secs[k] = _sanitize_html(v or "")
            d["sections"] = secs
            d["lead"] = _sanitize_html(d.get("lead") or "")
            d["images"] = d.get("images") or []
            d["credit"] = d.get("credit") or ""
            d["credit_url"] = d.get("credit_url") or ""
            d["tags"] = d.get("tags") or []
            d["primary_tag"] = d.get("primary_tag") or (d["tags"][0] if d["tags"] else "")
            GLOSSARY[tid] = d
        except Exception as e:
            print("EMS: failed to load", fn, e)

def _accent_for_term(d: Dict[str, Any]) -> str:
    tag = d.get("primary_tag") or ""
    if tag and tag in TAGS:
        return TAGS[tag].get("accent", "#8b5cf6")
    return "#8b5cf6"

# --- Payloads to JS ----------------------------------------------------------
def _bootstrap_payload() -> str:
    _load_local_tags(); _load_local_terms()
    terms = []
    for tid, d in GLOSSARY.items():
        terms.append({
            "id": tid,
            "title": d.get("title", tid),
            "synonyms": [d.get("title", tid)] + d.get("synonyms", []),
            "tags": d.get("tags", []),
            "primary": d.get("primary_tag") or "",
            "accent": _accent_for_term(d),
        })
    out = {"cfg": CFG, "tags": TAGS, "terms": terms}
    return json.dumps(out)

def _popup_payload(term_id: str) -> str:
    d = GLOSSARY.get(term_id)
    if not d:
        return json.dumps({"ok": False, "html": "<div style='padding:10px'>Missing term.</div>", "id": term_id})
    title = html.escape(d.get("title", term_id))
    lead = d.get("lead", "")
    accent = _accent_for_term(d)
    # media
    media_html = ""; credit_html = ""
    imgs = d.get("images") or []
    if imgs:
        if len(imgs)==1:
            u = imgs[0].get("url") if isinstance(imgs[0], dict) else str(imgs[0])
            cap = imgs[0].get("alt","") if isinstance(imgs[0], dict) else ""
            media_html += f"<div class='ems-media'><img class='ems-img' src='{html.escape(u)}' alt='{html.escape(cap)}'/></div>"
        else:
            media_html += "<div class='ems-gallery'>" + "".join(
                f"<figure><img class='ems-img' src='{html.escape(x.get('url') if isinstance(x,dict) else str(x))}'/></figure>"
                for x in imgs
            ) + "</div>"
    if d.get("credit") or d.get("credit_url"):
        href = html.escape(d.get("credit_url") or d.get("credit") or "#")
        credit_html = f"<div class='ems-credit'><a target='_blank' href='{href}'>image credit</a></div>"
    # sections
    order = d.get("order") or ["why","how","problem","diff","tricks","exam","treatment","red_flags","algorithm","mini_cases"]
    labels = {
        "why":"🎯 Why it matters",
        "how":"🔗 How you'll see it",
        "problem":"🧩 Problem solving — quick approach",
        "diff":"🧪 Differentials & Look-alikes",
        "tricks":"🧠 Tricks to avoid traps",
        "exam":"📝 How exams like to ask it",
        "treatment":"💊 Treatment — exam/wards version",
        "red_flags":"🚨 Red flags — do not miss",
        "algorithm":"🧭 1-minute algorithm",
        "mini_cases":"🌿 Mini-cases",
    }
    sec_html = []
    for key in order:
        html_block = d["sections"].get(key, "")
        has = bool(html_block.strip())
        disabled = "" if has else " is-disabled"
        learn_disabled = "" if has else " is-disabled"
        title_label = html.escape(labels.get(key, key.replace("_"," ").title()))
        sec_html.append(f"""
        <details class="ems-section{disabled}" open>
          <summary>
            <span class="ems-sec-left">{title_label}</span>
            <span class="ems-sec-right"><a href="#" class="ems-learn{learn_disabled}" data-ems-learn="{key}">＋ Learn</a></span>
          </summary>
          <div class="ems-section-body">{html_block}</div>
        </details>
        """)
    links_html = ""
    rel = d.get("related") or []
    if rel:
        links_html = "<div class='ems-related'>" + " · ".join(f"<a href='#' data-ems-link='{html.escape(x)}'>[{html.escape(x)}]</a>" for x in rel) + "</div>"
    footer = (
        "<div class='ems-brand'><div class='ems-brand-inner'>"
        "<img class='ems-logo' src='/_addons/ems_glossary/web/ems_logo.png' alt='EMS'/>"
        "<span class='ems-brand-name'>EnterMedSchool</span> · "
        "<a class='ems-site' href='https://entermedschool.com' target='_blank'>entermedschool.com</a>"
        "</div></div>"
    )
    html_out = f"""
    <div class="ems-topbar">
        <a href="#" class="ems-reviewall" data-ems-reviewall="{term_id}">🧠 Review all</a>
        <a href="#" class="ems-pin" data-ems-pin="{term_id}">📌 Pin</a>
        <a href="#" class="ems-close">✕</a>
    </div>
    <div class="ems-body" style="--ems-accent:{accent}">
        {media_html}{credit_html}
        <div class="ems-content">
            <h3>{title} <span style="font-size:18px">🧠</span></h3>
            <div class="ems-lead">{lead}</div>
        </div>
        {''.join(sec_html)}
        {links_html}
        <div class="ems-actions">
            <a class="ems-btn ems-btn--primary" href="{html.escape(d.get('watch_url','https://entermedschool.com'))}" target="_blank">Watch Lecture</a>
            <a class="ems-btn ems-btn--secondary" href="{html.escape(d.get('notes_url','https://entermedschool.com'))}" target="_blank">Read Notes</a>
        </div>
        {footer}
    </div>
    """
    return json.dumps({"ok": True, "html": html_out, "id": term_id})

# --- Learn cards -------------------------------------------------------------
def _ensure_learn_model_and_deck():
    col = mw.col
    mm = col.models
    m = None
    for x in mm.all():
        if x.get("name") == "EMS — Learn":
            m = x; break
    if not m:
        m = mm.new("EMS — Learn")
        f1 = mm.newField("Question")
        f2 = mm.newField("Answer")
        mm.addField(m, f1); mm.addField(m, f2)
        t = mm.newTemplate("Card 1")
        t["qfmt"] = "<div class='ems-card'><div class='q'>{{Question}}</div></div>"
        t["afmt"] = "<div class='ems-card'><div class='q'>{{Question}}</div><hr id=answer><div class='a'>{{Answer}}</div></div>"
        m["css"] = """.card { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; color: #eaeef3; background: #12141a; }
.ems-card{max-width:800px;margin:0 auto;background:#12141a;padding:18px;border-radius:14px;border:1px solid rgba(255,255,255,.08);}
.ems-card .q{font-size:20px;font-weight:700;padding:6px 8px;margin-bottom:8px;background:rgba(255,255,255,.04);border-radius:10px;border:1px solid rgba(255,255,255,.08);}
.ems-card .a{font-size:16px;line-height:1.5;}
ul{margin:6px 0 6px 18px} li{margin:4px 0}"""
        mm.addTemplate(m, t)
        mm.add(m)
    else:
        names = [f["name"] for f in m.get("flds",[])]
        changed = False
        if "Question" not in names:
            mm.addField(m, mm.newField("Question")); changed=True
        if "Answer" not in names:
            mm.addField(m, mm.newField("Answer")); changed=True
        if not m.get("tmpls"):
            t = mm.newTemplate("Card 1")
            t["qfmt"] = "<div class='ems-card'><div class='q'>{{Question}}</div></div>"
            t["afmt"] = "<div class='ems-card'><div class='q'>{{Question}}</div><hr id=answer><div class='a'>{{Answer}}</div></div>"
            mm.addTemplate(m, t); changed=True
        if changed:
            mm.save(m)

    # Decide deck
    if CFG["learn_target"] == "current":
        did = mw.col.decks.get_current_id()
    else:
        did = mw.col.decks.id(CFG["learn_deck"])
    return m, did

def _add_learn_card(term_id: str, section_key: str) -> Tuple[bool,str]:
    d = GLOSSARY.get(term_id)
    if not d:
        return False, "Missing term."
    html_block = d.get("sections",{}).get(section_key,"").strip()
    if not html_block:
        return False, "Empty section."
    m, did = _ensure_learn_model_and_deck()
    col = mw.col
    # duplicate protection
    dup = col.find_notes(f'tag:"ems_id::{term_id}" tag:"ems_sec::{section_key}"')
    if dup:
        return False, "Already added."
    n = col.new_note(m)
    sec_title = section_key.replace("_"," ").title()
    n["Question"] = f"{d.get('title',term_id)} — {sec_title}"
    n["Answer"]   = d.get("sections",{}).get(section_key,"")
    n.tags.extend(["ems","ems_learn",f"ems_id::{term_id}",f"ems_sec::{section_key}"])
    col.add_note(n, did)
    return True, "Added"

def _add_all_sections(term_id: str) -> Tuple[int,int,List[str]]:
    d = GLOSSARY.get(term_id)
    if not d: return 0,0,["Missing term"]
    add=0; skip=0; msgs=[]
    for k,v in (d.get("sections") or {}).items():
        if not (v and v.strip()): continue
        ok, msg = _add_learn_card(term_id, k)
        if ok: add+=1
        else: skip+=1
    return add, skip, msgs

# --- Updates -----------------------------------------------------------------
def _download_index_and_terms(index_url: str, dest_terms_dir: str):
    errs = []; downloaded = []
    try:
        idx = _http_json(index_url)
    except Exception as e:
        return [], [f"Could not parse JSON from {index_url}\\n{e}"]
    files = idx.get("files") or []
    for fn in files:
        url = f"{TERMS_BASE}/{fn}"
        try:
            txt = _http_text(url)
            json.loads(txt)  # validate
            with open(os.path.join(dest_terms_dir, fn), "w", encoding="utf-8") as f:
                f.write(txt)
            downloaded.append(fn)
        except Exception as e:
            errs.append(f"{fn}: {e}")
    # tags.json
    try:
        ttxt = _http_text(TAGS_URL)
        json.loads(ttxt)
        with open(TAGS_PATH, "w", encoding="utf-8") as f:
            f.write(ttxt)
    except Exception as e:
        errs.append(f"tags.json: {e}")
    return downloaded, errs

def update_from_remote(force=False):
    os.makedirs(TERMS_DIR, exist_ok=True)
    dl, errs = _download_index_and_terms(INDEX_URL, TERMS_DIR)
    _load_local_tags(); _load_local_terms()
    if errs:
        showInfo("Some files were skipped:\\n\\n" + "\\n".join("• "+x for x in errs) + "\\n\\nValid files were applied successfully.")
    else:
        showInfo("EMS Glossary updated.")

# --- Menu --------------------------------------------------------------------
def _ensure_menu():
    m = mw.form.menubar
    if hasattr(mw, "_ems_menu"):  # already
        return
    menu = m.addMenu(QIcon(os.path.join(WEB_DIR,"ems_logo.png")), " EnterMedSchool")
    mw._ems_menu = menu

    act1 = QAction("Check for Updates Now", mw)
    act1.triggered.connect(lambda: update_from_remote(force=True))
    menu.addAction(act1)

    act2 = QAction("Force Full Resync", mw)
    def fullres():
        for fn in os.listdir(TERMS_DIR):
            if fn.lower().endswith(".json"):
                try: os.remove(os.path.join(TERMS_DIR, fn))
                except: pass
        update_from_remote(force=True)
    act2.triggered.connect(fullres)
    menu.addAction(act2)

    menu.addSeparator()

    act3 = QAction("Appearance & Settings…", mw)
    act3.triggered.connect(open_settings)
    menu.addAction(act3)

    act4 = QAction("Open Data Folder", mw)
    act4.triggered.connect(lambda: QFileDialog.getOpenFileName(mw, "User data", USER_DIR, "All (*.*)"))
    menu.addAction(act4)

# --- Settings dialog ---------------------------------------------------------
def open_settings():
    global CFG
    dlg = QDialog(mw); dlg.setWindowTitle("EnterMedSchool — Glossary Settings 🚀")
    lay = QVBoxLayout(dlg)
    form = QFormLayout(); lay.addLayout(form)

    sp_w = QSpinBox(); sp_w.setRange(420, 1200); sp_w.setValue(CFG["popup_width"])
    sp_f = QSpinBox(); sp_f.setRange(12, 24); sp_f.setValue(CFG["font_px"])
    form.addRow("Popup width (px)", sp_w)
    form.addRow("Popup font size (px)", sp_f)

    cb_m = QComboBox(); cb_m.addItems(["hover","click"]); cb_m.setCurrentText(CFG["open_mode"])
    sp_d = QSpinBox(); sp_d.setRange(0, 1500); sp_d.setValue(CFG["hover_delay"])
    form.addRow("Open mode", cb_m)
    form.addRow("Hover delay (ms)", sp_d)

    sp_max = QSpinBox(); sp_max.setRange(10, 200); sp_max.setValue(CFG["max_per_card"])
    form.addRow("Max highlights per card", sp_max)

    chk = QCheckBox("Clicking a term opens immediately"); chk.setChecked(CFG["click_anywhere"]); lay.addWidget(chk)

    form2 = QFormLayout(); lay.addLayout(form2)
    cb_t = QComboBox(); cb_t.addItems(["dedicated","current"]); cb_t.setCurrentText(CFG["learn_target"])
    ed_deck = QLineEdit(CFG["learn_deck"])
    form2.addRow("Save to", cb_t); form2.addRow("Dedicated deck name", ed_deck)

    row = QHBoxLayout(); lay.addLayout(row)
    b_reset = QPushButton("Reset ↩️"); b_save = QPushButton("Save ✅"); b_close = QPushButton("Close")
    row.addWidget(b_reset); row.addWidget(b_save); row.addStretch(1); row.addWidget(b_close)

    def do_reset():
        for k,v in DEFAULT_CFG.items(): CFG[k]=v
        sp_w.setValue(CFG["popup_width"]); sp_f.setValue(CFG["font_px"])
        cb_m.setCurrentText(CFG["open_mode"]); sp_d.setValue(CFG["hover_delay"])
        sp_max.setValue(CFG["max_per_card"]); chk.setChecked(CFG["click_anywhere"])
        cb_t.setCurrentText(CFG["learn_target"]); ed_deck.setText(CFG["learn_deck"])

    def do_save():
        CFG["popup_width"] = sp_w.value()
        CFG["font_px"] = sp_f.value()
        CFG["open_mode"] = cb_m.currentText()
        CFG["hover_delay"] = sp_d.value()
        CFG["max_per_card"] = sp_max.value()
        CFG["click_anywhere"] = chk.isChecked()
        CFG["learn_target"] = cb_t.currentText()
        CFG["learn_deck"] = ed_deck.text().strip() or DEFAULT_CFG["learn_deck"]
        save_cfg(CFG); dlg.accept(); tooltip("Saved.")

    b_reset.clicked.connect(do_reset); b_save.clicked.connect(do_save); b_close.clicked.connect(dlg.reject)
    dlg.exec()

# --- Web injection -----------------------------------------------------------
def on_webview_will_set_content(web_content, context):
    try:
        name = type(context).__name__.lower()
    except Exception:
        name = ""
    if "review" in name or "preview" in name or "browser" in name or "editor" in name:
        web_content.css.append("/_addons/ems_glossary/web/popup.css")
        web_content.js.append("/_addons/ems_glossary/web/popup.js")
        theme = f"""
        <style> .ems-popover {{ max-width: {CFG['popup_width']}px; font-size: {CFG['font_px']}px; }} </style>
        <script>window.EMS_BOOT = {{
            hoverMode: {json.dumps(CFG['open_mode'])},
            hoverDelay: {int(CFG['hover_delay'])},
            clickAnywhere: {str(CFG['click_anywhere']).lower()},
            maxPerCard: {int(CFG['max_per_card'])}
        }};</script>
        """
        web_content.head += theme

gui_hooks.webview_will_set_content.append(on_webview_will_set_content)

# --- Bridge ------------------------------------------------------------------
def on_js_message(handled, msg, context, view):
    if not isinstance(msg, str) or not msg.startswith("ems:"):
        return handled
    try:
        payload = json.loads(msg[4:])
        op = payload.get("op")
        if op == "bootstrap":
            return (True, _bootstrap_payload())
        elif op == "popup":
            return (True, _popup_payload(payload.get("id","")))
        elif op == "learn":
            ok, m = _add_learn_card(payload["id"], payload["section"])
            return (True, json.dumps({"ok": ok, "msg": m}))
        elif op == "learn_all":
            a,b,_ = _add_all_sections(payload["id"])
            return (True, json.dumps({"ok": True, "added": a, "skipped": b}))
        elif op == "update":
            update_from_remote(force=True); return (True, "ok")
        else:
            return (True, json.dumps({"ok": False, "msg": "unknown op"}))
    except Exception as e:
        tb = traceback.format_exc()
        print("EMS error:\n", tb)
        return (True, json.dumps({"ok": False, "msg": str(e)}))

gui_hooks.webview_did_receive_js_message.append(on_js_message)

# --- Startup -----------------------------------------------------------------
_load_local_tags(); _load_local_terms()
_ensure_menu()
