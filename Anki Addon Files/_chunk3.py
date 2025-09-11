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
