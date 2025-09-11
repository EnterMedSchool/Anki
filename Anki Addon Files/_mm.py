            raw = "(no file)"; parsed = {}
            try:
                if os.path.exists(FETCHED_INDEX_RAW): raw = open(FETCHED_INDEX_RAW,"r",encoding="utf-8").read()
                if os.path.exists(FETCHED_INDEX_PARSED): parsed = json.load(open(FETCHED_INDEX_PARSED,"r",encoding="utf-8"))
            except Exception as e: raw = f"(error reading diagnostics: {e})"
            showText("Parsed index:\n\n"+json.dumps(parsed, ensure_ascii=False, indent=2)+"\n\nRaw:\n\n"+raw[:4000], title="EMS — Diagnostics")
        qconnect(aDiag.triggered, show_diag); menu.addAction(aDiag)

        menu.addSeparator()
        a3 = QAction("🎨  Appearance & Settings…", mw); qconnect(a3.triggered, on_show_options); menu.addAction(a3)
        a4 = QAction("📂  Open Data Folder", mw); qconnect(a4.triggered, lambda: openFolder(USER_FILES_DIR)); menu.addAction(a4)
        menu.addSeparator()
        aSuggest = QAction("Suggest a Glossary Term…", mw)
        qconnect(aSuggest.triggered, on_show_suggest)
        menu.addAction(aSuggest)
    except Exception as e:
        _log(f"build menu failed: {e}")

def _on_profile_open():
    _build_menu(); 
    try: 
        # auto update (respect last checked)
        last = int(get_config().get("last_update_check", 0))
        if int(time.time()) - last >= AUTO_UPDATE_DAYS*86400:
            threading.Thread(target=lambda: update_from_remote(bypass_cache=True), daemon=True).start()
    except Exception as e:
        _log(f"auto update failed: {e}")
gui_hooks.profile_did_open.append(_on_profile_open)
