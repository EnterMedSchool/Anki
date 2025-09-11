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
