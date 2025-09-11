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
