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
