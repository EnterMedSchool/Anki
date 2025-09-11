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
