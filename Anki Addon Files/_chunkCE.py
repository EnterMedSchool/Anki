
        # Ensure "my terms" folder exists
        try:
            os.makedirs(MY_TERMS_DIR, exist_ok=True)
        except Exception:
            pass

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
