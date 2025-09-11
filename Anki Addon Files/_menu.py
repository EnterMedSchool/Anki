    except Exception as e: _log(f"SuggestTerm dialog failed: {e}")

# ------------------------------ Menu ------------------------------------------

def _ensure_logo_icon() -> QIcon:
    try: return QIcon(LOGO_PATH) if os.path.exists(LOGO_PATH) else QIcon()
    except Exception: return QIcon()

def _build_menu():
    try:
        bar = mw.menuBar()
        icon = QIcon(LOGO_PATH) if os.path.exists(LOGO_PATH) else QIcon()
        menu = bar.addMenu("EnterMedSchool")
        try: menu.setIcon(icon)
        except Exception: pass

        def run_update(background=True):
            def worker():
                ok, summary, details = update_from_remote(bypass_cache=True)
                def show():
                    if ok:
                        if details: showText(details, title="EnterMedSchool — Update Report"); showInfo(summary)
                    else:
                        showText(summary + "\n\n" + details, title="EnterMedSchool — Update Error")
                try: mw.taskman.run_on_main(show)
                except Exception as e: _log(f"show after update failed: {e}")
            if background: threading.Thread(target=worker, daemon=True).start()
            else: worker()

        a1 = QAction("🔄  Check for Updates Now (Bypass Cache)", mw)
        qconnect(a1.triggered, lambda: run_update(background=True)); menu.addAction(a1)
        a2 = QAction("🧹  Force Full Resync (Bypass Cache)", mw)
        qconnect(a2.triggered, lambda: run_update(background=True)); menu.addAction(a2)

        menu.addSeparator()
        aDiag = QAction("🧪  Diagnostics: Show last fetched index", mw)
        def show_diag():
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
