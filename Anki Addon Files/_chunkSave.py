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

