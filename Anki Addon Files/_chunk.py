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

# -------------------------- Suggest Term UI -----------------------------------

class SuggestTermDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Suggest a Glossary Term")
        self.setMinimumWidth(620)
        self.resize(760, 760)
        self.setWindowIcon(_ensure_logo_icon())
        # Outer layout
        outer = QVBoxLayout(self)

        # Header row with example toggle
        header = QHBoxLayout()
        logo = QLabel(f"<img width=24 height=24 src='/_addons/{mw.addonManager.addonFromModule(MODULE)}/web/ems_logo.png'>")
        title = QLabel("<b>Suggest a Glossary Term</b>")
        self.exampleToggleBtn = QPushButton("Show Example")
        header.addWidget(logo); header.addWidget(title); header.addStretch(1); header.addWidget(self.exampleToggleBtn)
        outer.addLayout(header)

        # Scroll area with the form
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)
        lay = QVBoxLayout(content)

        # Core fields
        lay.addWidget(QLabel("Core"))
        core1 = QHBoxLayout(); core1.addWidget(QLabel("Name(s) (comma-separated):"))
        self.namesLE = QLineEdit(); core1.addWidget(self.namesLE, 1); lay.addLayout(core1)

        core2 = QHBoxLayout(); core2.addWidget(QLabel("Definition:"))
        self.definitionTE = QPlainTextEdit(); self.definitionTE.setPlaceholderText("A clear, concise definition…"); self.definitionTE.setFixedHeight(90)
        core2.addWidget(self.definitionTE, 1); lay.addLayout(core2)

        # Optional fields
        lay.addWidget(QLabel("Optional"))
        rowA = QHBoxLayout(); rowA.addWidget(QLabel("Aliases (comma-separated):"))
        self.aliasesLE = QLineEdit(); rowA.addWidget(self.aliasesLE, 1); lay.addLayout(rowA)

        rowB = QHBoxLayout(); rowB.addWidget(QLabel("Abbreviations (comma-separated):"))
        self.abbrLE = QLineEdit(); rowB.addWidget(self.abbrLE, 1); lay.addLayout(rowB)

        rowC = QHBoxLayout(); rowC.addWidget(QLabel("Tags (comma-separated):"))
        self.tagsLE = QLineEdit(); rowC.addWidget(self.tagsLE, 1); lay.addLayout(rowC)

        self.whyTE = QPlainTextEdit(); self.whyTE.setPlaceholderText("Why it matters (1-2 sentences)"); self.whyTE.setFixedHeight(70)
        lay.addWidget(QLabel("Why it matters:")); lay.addWidget(self.whyTE)

        self.hysiTE = QPlainTextEdit(); self.hysiTE.setPlaceholderText("One bullet per line"); self.hysiTE.setFixedHeight(90)
        lay.addWidget(QLabel("How you'll see it (bullets):")); lay.addWidget(self.hysiTE)

        self.psTE = QPlainTextEdit(); self.psTE.setPlaceholderText("One bullet per line"); self.psTE.setFixedHeight(90)
        lay.addWidget(QLabel("Problem solving (bullets):")); lay.addWidget(self.psTE)

        self.diffTE = QPlainTextEdit(); self.diffTE.setPlaceholderText("One per line, e.g. Name | hint"); self.diffTE.setFixedHeight(90)
        lay.addWidget(QLabel("Differentials (one per line):")); lay.addWidget(self.diffTE)

        self.tricksTE = QPlainTextEdit(); self.tricksTE.setPlaceholderText("One bullet per line"); self.tricksTE.setFixedHeight(80)
        lay.addWidget(QLabel("Tricks (bullets):")); lay.addWidget(self.tricksTE)

        self.examTE = QPlainTextEdit(); self.examTE.setPlaceholderText("One bullet per line"); self.examTE.setFixedHeight(80)
        lay.addWidget(QLabel("Exam appearance (bullets):")); lay.addWidget(self.examTE)

        self.treatTE = QPlainTextEdit(); self.treatTE.setPlaceholderText("One bullet per line"); self.treatTE.setFixedHeight(80)
        lay.addWidget(QLabel("Treatment (bullets):")); lay.addWidget(self.treatTE)

        self.rfTE = QPlainTextEdit(); self.rfTE.setPlaceholderText("One bullet per line"); self.rfTE.setFixedHeight(70)
        lay.addWidget(QLabel("Red flags (bullets):")); lay.addWidget(self.rfTE)

        self.algoTE = QPlainTextEdit(); self.algoTE.setPlaceholderText("Step per line"); self.algoTE.setFixedHeight(80)
        lay.addWidget(QLabel("Algorithm (steps, one per line):")); lay.addWidget(self.algoTE)

        self.sourcesTE = QPlainTextEdit(); self.sourcesTE.setPlaceholderText("One per line: Title | URL or just URL"); self.sourcesTE.setFixedHeight(80)
        lay.addWidget(QLabel("Sources:")); lay.addWidget(self.sourcesTE)

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
        submitBtn = QPushButton("Submit to GitHub")
        closeBtn = QPushButton("Close")
        btns.addWidget(exampleLoadBtn); btns.addWidget(previewBtn); btns.addWidget(submitBtn); btns.addWidget(closeBtn)
        outer.addLayout(btns)

        # Wire up
        self.exampleToggleBtn.clicked.connect(self._toggle_example)
        exampleLoadBtn.clicked.connect(self._on_load_example)
        previewBtn.clicked.connect(self._on_preview)
        submitBtn.clicked.connect(self._on_submit)
        closeBtn.clicked.connect(self.close)

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
        self.tagsLE.setText(", ".join(obj.get("tags", [])))
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
        tags = self._csv_list(self.tagsLE.text());
        if tags: obj["tags"] = tags
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
        return obj

    def _on_preview(self):
        try:
            obj = self._build_payload()
            showText(json.dumps(obj, ensure_ascii=False, indent=2), title="Glossary Term JSON Preview")
        except Exception as e:
            showInfo(f"Preview failed: {e}")

    def _on_submit(self):
        try:
            obj = self._build_payload()
            names = obj.get("names") or []
            if not names:
                showInfo("Please enter at least one name for the term.")
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
