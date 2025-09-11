
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
