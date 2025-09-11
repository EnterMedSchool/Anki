(function () {
  /* ========================== shared, de-duped ========================== */
  const SHARED = window._EMS_SHARED || (window._EMS_SHARED = {
    bound: false,
    index: null,
    openToken: 0,           // cancels stale loads
    pendingHoverEl: null,   // hover intent target
    anchorEl: null
  });

  const HANDLERS = window._EMS_HANDLERS || (window._EMS_HANDLERS = {});
  const cfg = (window.EMS_CFG || { hoverMode: "hover", hoverDelay: 140 });

  let index = null;
  let hoverTimer = 0;
  let hideTimer = 0;
  let zCounter = 2147483647;

  /* ================================ utils =============================== */
  const escHtml = s => (s || "").replace(/[&<>\"']/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
  const toast = (txt) => { const f=document.createElement("div"); f.className="ems-float is-open"; f.textContent=txt||"Done"; document.body.appendChild(f); setTimeout(()=>f.remove(), 1400); };

  /* ======================= index + inline highlights ===================== */
  function buildIndex(payload){
    const meta = payload.meta || {};
    const claims = payload.claims || {};
    const mapCandidates = Object.create(null);

    for (const k in claims) mapCandidates[k] = (claims[k]||[]).slice();
    for (const t of (payload.terms||[])) {
      for (const p of (t.patterns||[])) {
        const k = p.toLowerCase();
        if (!mapCandidates[k]) mapCandidates[k] = [t.id];
        else if (!mapCandidates[k].includes(t.id)) mapCandidates[k].push(t.id);
      }
    }

    const titleLookup = Object.create(null);
    for (const id in meta){
      const title=(meta[id] && (meta[id].title||"")).toLowerCase().replace(/\s+/g," ").trim();
      if (title){
        if (!titleLookup[title]) titleLookup[title] = [id];
        else if (!titleLookup[title].includes(id)) titleLookup[title].push(id);
      }
    }

    const alts = Object.keys(mapCandidates).sort((a,b)=>b.length-a.length);
    const esc  = s => s.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")
                       .replace(/\\ /g," ").replace(/\\'/g,"'")
                       .replace(/\\-/g,"-").replace(/\\\//g,"/");
    let rx;
    try {
      rx = new RegExp("(?<![A-Za-z0-9])(?:"+alts.map(esc).join("|")+")(?![A-Za-z0-9])","gi");
    } catch (e) {
      rx = new RegExp("\\b(?:"+alts.map(esc).join("|")+")\\b","gi");
    }

    return { mapCandidates, mapClaims: claims, rx, meta, titleLookup };
  }

  function wrapMatches(idx){
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node){
        if (!node || !node.nodeValue) return NodeFilter.FILTER_REJECT;
        const p = node.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        if (p.closest("a, .ems-term, .ems-popover, .ems-pin, .mjx-container, .MathJax, code, pre")) return NodeFilter.FILTER_REJECT;
        if (!/[A-Za-z]/.test(node.nodeValue)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    const edits = [];

    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!idx.rx.test(node.nodeValue)) continue;
      idx.rx.lastIndex = 0;

      const text = node.nodeValue;
      let last = 0;
      const frag = document.createDocumentFragment();
      let changed = false;

      for (let m; (m = idx.rx.exec(text)); ) {
        const word = m[0];
        const key = word.toLowerCase();
        const ids = idx.mapCandidates[key] || [];
        if (!ids.length) continue;

        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));

        const span = document.createElement("span");
        span.className = "ems-term";
        if (ids.length === 1) span.dataset.term = ids[0];
        else { span.dataset.choices = ids.join(","); span.classList.add("ems-term--ambiguous"); }
        span.textContent = word;
        span.setAttribute("tabindex","0");

        const meta0 = idx.meta[ids[0]] || {};
        if (meta0.accent) span.style.setProperty("--ems-accent", meta0.accent);

        frag.appendChild(span);
        last = idx.rx.lastIndex;
        changed = true;
      }

      if (!changed) continue;
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      edits.push([node, frag]);
    }

    for (const [node, frag] of edits) if (node.parentNode) node.parentNode.replaceChild(frag, node);
  }

  function stitchMultiWord(idx){
    const isSpaceText = n => n && n.nodeType === 3 && /^\s+$/.test(n.nodeValue);
    const terms = Array.from(document.querySelectorAll(".ems-term"));

    for (let i=0;i<terms.length;i++){
      const first = terms[i]; if (!first || !first.isConnected) continue;

      const run = [first];
      let tail = first;
      let cur  = tail.nextSibling;

      while (isSpaceText(cur) &&
             cur.nextSibling &&
             cur.nextSibling.nodeType===1 &&
             cur.nextSibling.classList.contains("ems-term")){
        run.push(cur.nextSibling);
        tail = cur.nextSibling;
        cur  = tail.nextSibling;
      }
      if (run.length === 1) continue;

      const combined = run.map(el=>el.textContent).join(" ").replace(/\s+/g," ").toLowerCase();
      let ids = idx.mapCandidates[combined] || [];
      if (!ids.length && idx.titleLookup) ids = idx.titleLookup[combined] || [];
      if (!ids.length) continue;

      const span = document.createElement("span");
      span.className = "ems-term";
      span.textContent = run.map(el => el.textContent).join(" ");
      if (ids.length === 1) span.dataset.term = ids[0];
      else { span.dataset.choices = ids.join(","); span.classList.add("ems-term--ambiguous"); }

      const meta0 = idx.meta[ids[0]] || {};
      if (meta0.accent) span.style.setProperty("--ems-accent", meta0.accent);

      const parent = first.parentNode;
      let n = first;
      while (n && n !== tail) { const next = n.nextSibling; parent.removeChild(n); n = next; }
      parent.replaceChild(span, tail);
      i += run.length - 1;
    }
  }

  /* ================================ popover ============================== */
  function topbarHTML(){
    return `<div class="ems-topbar">
      <a href="#" class="ems-pill" data-ems-learnall="1"><span class="i">🧠</span><span>Review all</span></a>
      <a href="#" class="ems-pill" data-ems-pin="1"><span class="i">📌</span><span>Pin</span></a>
      <button type="button" class="ems-iconbtn" data-ems-close="1" aria-label="Close">×</button>
    </div>`;
  }

  function ensureSingletonPopover(){
    // remove accidental duplicates (caused by the 2nd popup.js in older bundles)
    const all = Array.from(document.querySelectorAll(".ems-popover"));
    for (let i=1;i<all.length;i++) all[i].remove();

    let p = all[0];
    if (!p){
      p = document.createElement("div");
      p.className = "ems-popover";
      p.style.display = "none";
      p.setAttribute("role","dialog");
      p.setAttribute("aria-modal","true");
      document.body.appendChild(p);
    }

    // ensure exactly one scrollable .ems-body and the toolbar inside it
    let body = p.querySelector(".ems-body");
    if (!body){
      body = document.createElement("div");
      body.className = "ems-body";
      while (p.firstChild) body.appendChild(p.firstChild);
      p.appendChild(body);
    } else {
      const extras = p.querySelectorAll(".ems-body");
      if (extras.length > 1){
        const primary = extras[0];
        for (let i=1;i<extras.length;i++){
          while (extras[i].firstChild) primary.appendChild(extras[i].firstChild);
          extras[i].remove();
        }
        body = primary;
      }
    }

    let tb = p.querySelector(".ems-topbar");
    if (!tb) body.insertAdjacentHTML("afterbegin", topbarHTML());
    else if (tb.parentElement !== body) body.prepend(tb);

    return p;
  }

  function positionPopover(p, target){
    const rect=target.getBoundingClientRect();
    const vw=document.documentElement.clientWidth||window.innerWidth;
    const vh=document.documentElement.clientHeight||window.innerHeight;
    const width=p.offsetWidth||360, height=p.offsetHeight||200;

    let x=rect.left+window.scrollX;
    let y=rect.bottom+window.scrollY+10;
    if (y+height>window.scrollY+vh-12){ y=rect.top+window.scrollY-height-10; }

    x = clamp(x, 10+window.scrollX, window.scrollX+vw-width-10);
    y = clamp(y, 10+window.scrollY, window.scrollY+vh-height-10);

    p.style.left = x+"px";
    p.style.top  = y+"px";
  }

  function trapScrollInside(el){
    ["wheel","touchmove"].forEach(evt => el.addEventListener(evt, e => { e.stopPropagation(); }, {passive:false}));
  }

  function bindInsidePopover(){
    const p = ensureSingletonPopover();
    const body = p.querySelector(".ems-body");

    p.addEventListener("mouseenter", ()=>{ clearTimeout(hideTimer); }, {once:false});
    p.addEventListener("mouseleave", ()=>{ hidePopoverSoon(); }, {once:false});

    const close=p.querySelector("[data-ems-close]");
    if (close) close.onclick=(e)=>{ e.preventDefault(); hidePopover(); };

    const pinBtn=p.querySelector("[data-ems-pin]");
    if (pinBtn) pinBtn.onclick=(e)=>{
      e.preventDefault();
      const tid=window._EMS_LAST_TID; if (!tid) return;
      if (window.pycmd) pycmd(`ems_glossary:pin:${tid}`,(ret)=>{ if(ret&&ret.id) createOrUpdatePin(ret); });
    };

    const learnAll=p.querySelector("[data-ems-learnall]");
    if (learnAll) learnAll.onclick=(e)=>{
      e.preventDefault();
      const tid=window._EMS_LAST_TID; if (!tid) return;
      if (window.pycmd) pycmd(`ems_glossary:learnall:${tid}`,(ret)=>{ if(ret&&ret.message) toast(ret.message); });
    };

    // Open linked terms *in-place*; hold Shift/Ctrl/Cmd to pin instead
    p.querySelectorAll("[data-ems-link]").forEach(a=>{
      a.addEventListener("click",(ev)=>{
        ev.preventDefault();
        const tid=a.getAttribute("data-ems-link") || a.dataset.emsLink;
        if (!tid) return;
        if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
          if (window.pycmd) pycmd(`ems_glossary:pin:${tid}`,(ret)=>{ if(ret&&ret.id) createOrUpdatePin(ret); });
          return;
        }
        openTermInPlace(tid);   // replace content in the same popover
      });
    });

    p.querySelectorAll(".ems-learn").forEach(btn=>{
      btn.addEventListener("click",(ev)=>{
        ev.preventDefault(); if (btn.disabled) return;
        const sec = btn.closest(".ems-section")?.getAttribute("data-sec");
        const tid = window._EMS_LAST_TID;
        if (!sec || !tid) return;
        if (window.pycmd) pycmd(`ems_glossary:learn:${tid}:${sec}`,(ret)=>{ if(ret&&ret.message) toast(ret.message); });
      });
    });

    p.querySelectorAll("img.ems-img").forEach(img=>{
      img.addEventListener("click",(ev)=>{
        const w=window.open(img.getAttribute("src"),"_blank");
        if(w) ev.preventDefault();
      });
    });

    trapScrollInside(body);
  }

  function hidePopover(){ const p=ensureSingletonPopover(); p.style.display="none"; }
  function hidePopoverSoon(){
    clearTimeout(hideTimer);
    hideTimer = setTimeout(()=>{
      const p=ensureSingletonPopover();
      if(!p.matches(":hover")) p.style.display="none";
    }, 160);
  }

  /* =================== unified open path with tokens ==================== */
  function openTermNear(target, termId){
    SHARED.anchorEl = target;
    const token = ++SHARED.openToken;
    const p = ensureSingletonPopover();
    const body = p.querySelector(".ems-body");
    body.innerHTML = `<div class="ems-small" style="opacity:.8;padding:6px 0">Loading…</div>`;
    p.style.display = "block";
    positionPopover(p, target);
    bindInsidePopover();

    if (!window.pycmd) return;

    pycmd(`ems_glossary:get:${termId}`, (ret)=>{
      if (token !== SHARED.openToken) return;  // newer request won
      window._EMS_LAST_TID = termId;
      body.innerHTML = ret && ret.html ? ret.html : "<div class='ems-small'>No content.</div>";
      const tb = p.querySelector(".ems-topbar");
      if (tb && tb.parentElement !== body) body.prepend(tb);
      bindInsidePopover();
      positionPopover(p, target);
    });
  }

  // Replace content in the *same* popover (used when clicking links inside it)
  function openTermInPlace(termId){
    const p = ensureSingletonPopover();
    const body = p.querySelector(".ems-body");
    const token = ++SHARED.openToken;
    body.innerHTML = `<div class="ems-small" style="opacity:.8;padding:6px 0">Loading…</div>`;
    p.style.display = "block";
    bindInsidePopover();  // keep handlers fresh
    if (!window.pycmd) return;

    pycmd(`ems_glossary:get:${termId}`, (ret)=>{
      if (token !== SHARED.openToken) return;
      window._EMS_LAST_TID = termId;
      body.innerHTML = ret && ret.html ? ret.html : "<div class='ems-small'>No content.</div>";
      bindInsidePopover();
      // keep previous position (no reposition)
    });
  }

  function showChooserNear(target, ids){
    const p = ensureSingletonPopover();
    const body = p.querySelector(".ems-body");
    const items = ids.map(id=>{
      const label=(SHARED.index?.meta?.[id]?.title||id);
      return `<li data-id="${id}">
        <button data-open="${id}" class="ems-pill" style="height:26px;padding:0 10px">Open</button>
        <span style="opacity:.85;margin-left:8px">${escHtml(label)}</span>
      </li>`;
    }).join("");

    body.innerHTML = `<h3 style="margin:0 0 6px 0;text-align:center">Choose term</h3>
                      <ul style="margin:0;padding-left:18px;display:grid;gap:6px">${items}</ul>`;
    p.style.display = "block";
    positionPopover(p, target);
    bindInsidePopover();

    p.querySelectorAll("[data-open]").forEach(btn=>{
      btn.addEventListener("click",(e)=>{
        e.preventDefault();
        const tid=btn.getAttribute("data-open");
        openTermNear(target, tid);
      });
    });
  }

  /* ================================ pins ================================ */
  function ensurePinBindings(pin){
    const header=pin.querySelector("header");
    let dragging=false,sx=0,sy=0,ox=0,oy=0;
    function mdown(e){ dragging=true; pin.style.zIndex=++zCounter; sx=e.clientX; sy=e.clientY; const r=pin.getBoundingClientRect(); ox=r.left; oy=r.top; e.preventDefault(); }
    function mmove(e){ if(!dragging) return; const nx=ox+(e.clientX-sx)+window.scrollX; const ny=oy+(e.clientY-sy)+window.scrollY; pin.style.left=Math.max(8,nx)+"px"; pin.style.top=Math.max(8,ny)+"px"; }
    function mup(){ dragging=false; }
    header.onmousedown=mdown; document.addEventListener("mousemove",mmove,true); document.addEventListener("mouseup",mup,true);
    pin.addEventListener("mousedown",()=>{ pin.style.zIndex=++zCounter; },true);

    const bodyEl = pin.querySelector('.body');
    if (bodyEl) ['wheel','touchmove'].forEach(evt=> bodyEl.addEventListener(evt,(e)=>{ e.stopPropagation(); }, {passive:false}));

    pin.querySelector(".ems-unpin").onclick=(e)=>{ e.preventDefault(); pin.remove(); };
    pin.querySelectorAll("[data-ems-link]").forEach(a=>{
      a.addEventListener("click",(ev)=>{
        ev.preventDefault();
        const sid=a.getAttribute("data-ems-link");
        if (sid && window.pycmd) pycmd(`ems_glossary:pin:${sid}`,(ret)=>{ if(ret&&ret.id) createOrUpdatePin(ret); });
      });
    });
  }

  function createOrUpdatePin(obj){
    const pin=document.createElement("div");
    pin.className="ems-pin";
    pin.dataset.pid=obj.id;
    document.body.appendChild(pin);

    pin.style.left=(obj.x||60)+"px";
    pin.style.top =(obj.y||60)+"px";
    pin.style.zIndex=++zCounter;

    pin.innerHTML=
      `<header><span class="title">${escHtml(obj.title||obj.tid||"Pinned")}</span><span class="spacer"></span><a href="#" class="ems-unpin" title="Close">×</a></header>
       <div class="body">${obj.html||""}</div>`;

    ensurePinBindings(pin);
    return pin;
  }

  /* ================================ drawer =============================== */
  function ensureDrawer(){
    let d=document.querySelector(".ems-drawer");
    if (d && d.isConnected) return d;
    d=document.createElement("div");
    d.className="ems-drawer";
    d.innerHTML="<header>Glossary <span class='tag'>G to toggle</span></header><div class='toolbar'><input placeholder='Search terms…' /><button class='ems-tagbtn'>All tags ▾</button><div class='ems-tagmenu'></div></div><div class='ems-list'></div>";
    document.body.appendChild(d);
    const tagMenu=d.querySelector(".ems-tagmenu");
    d.querySelector(".ems-tagbtn").onclick=()=>tagMenu.classList.toggle("is-open");
    document.addEventListener("click",(e)=>{ if(!d.contains(e.target)) tagMenu.classList.remove("is-open"); }, true);
    return d;
  }

  function populateDrawer(idx){
    const d=ensureDrawer();
    const list=d.querySelector(".ems-list");
    list.innerHTML="";

    idx = idx || SHARED.index;
    if (!idx){
      list.innerHTML = "<div style='padding:12px;opacity:.8'>No terms loaded yet.</div>";
      return;
    }

    const q=(d.querySelector(".toolbar input").value||"").toLowerCase();
    const tagMenu=d.querySelector(".ems-tagmenu");
    const tag=d.dataset.tag||"";

    const allTags=new Set();
    for (const id in idx.meta) for (const t of (idx.meta[id].tags||[])) allTags.add(t);

    if (!tagMenu.dataset.built) {
      tagMenu.innerHTML=`<div class="opt" data-tag="">All tags</div>` +
        Array.from(allTags).sort().map(t=>`<div class="opt" data-tag="${t}">${t}</div>`).join("");
      tagMenu.dataset.built="1";
      tagMenu.querySelectorAll(".opt").forEach(el=>{
        el.onclick=()=>{
          d.dataset.tag=el.getAttribute("data-tag")||"";
          d.querySelector(".ems-tagbtn").textContent = (d.dataset.tag ? d.dataset.tag+" ▾" : "All tags ▾");
          populateDrawer(idx);
          tagMenu.classList.remove("is-open");
        };
      });
    }

    const seen=new Set();
    for (const k in idx.mapCandidates) {
      for (const id of (idx.mapCandidates[k]||[])) {
        if (seen.has(id)) continue; seen.add(id);
        const meta=idx.meta[id]||{}; const title=meta.title||id;
        if (q && !title.toLowerCase().includes(q) && !id.toLowerCase().includes(q)) continue;
        if (tag && !(meta.tags||[]).includes(tag)) continue;

        const item=document.createElement("div");
        item.className="ems-item"; item.tabIndex=0;
        if (meta.accent) item.style.setProperty("--ems-accent", meta.accent);
        const icon=meta.icon||"🔎";
        item.innerHTML=`<span class="ems-chip">${icon}</span> <span>${title}</span> <span class="ems-right">${(meta.tags||[]).join(", ")}</span>`;
        item.addEventListener("click",()=>openTermNear(item, id));
        item.addEventListener("keydown",(e)=>{ if(e.key==="Enter") openTermNear(item, id); });
        list.appendChild(item);
      }
    }
  }

  function toggleDrawer(show){
    const d=ensureDrawer();
    if (show===false){ d.classList.remove("is-open"); return; }
    if (d.classList.contains("is-open")) { d.classList.remove("is-open"); return; }
    populateDrawer(SHARED.index || index);
    d.classList.add("is-open");
    const inp = d.querySelector(".toolbar input");
    if (inp) inp.oninput = () => populateDrawer(SHARED.index || index);
  }

  /* ============================ global binds ============================ */
  function onEnter(ev){
    const el = ev.target;
    if (!el || !el.classList || !el.classList.contains("ems-term")) return;
    if (cfg.hoverMode !== "hover") return;

    SHARED.pendingHoverEl = el;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(()=>{
      // if we already left this element, cancel
      if (SHARED.pendingHoverEl !== el) return;
      if (el.dataset.choices) return;              // ambiguous → click to choose
      openTermNear(el, el.dataset.term);
    }, Math.max(60,(cfg.hoverDelay|0)||0));
  }

  function onLeave(ev){
    const el = ev.target;
    if (el && el === SHARED.pendingHoverEl) SHARED.pendingHoverEl = null;
    if (el && el.classList && el.classList.contains("ems-term")) hidePopoverSoon();
  }

  function onClick(ev){
    const el = ev.target && ev.target.closest && ev.target.closest(".ems-term");
    if (!el) return;
    ev.preventDefault();
    SHARED.pendingHoverEl = null;

    if (el.dataset.choices) {
      const ids = el.dataset.choices.split(",").filter(Boolean);
      showChooserNear(el, ids);
    } else {
      openTermNear(el, el.dataset.term);
    }
  }

  function onKeydown(ev){
    if (ev.key === "Escape"){ hidePopover(); return; }

    // Cmd/Ctrl+K — universal drawer shortcut
    const isMac = navigator.platform.toUpperCase().includes("MAC");
    if ((isMac && ev.metaKey && ev.key.toLowerCase()==="k") ||
        (!isMac && ev.ctrlKey && ev.key.toLowerCase()==="k")) {
      ev.preventDefault(); ev.stopPropagation();
      toggleDrawer(true);
      const d=ensureDrawer(); const q=d.querySelector(".toolbar input"); if(q){ q.focus(); q.select(); }
      return;
    }

    // G — only consume if an index exists (prevents a 2nd copy from eating the key)
    if ((ev.key==="g"||ev.key==="G") && !ev.metaKey && !ev.ctrlKey && !ev.altKey) {
      const haveIndex = !!(SHARED.index || index);
      if (!haveIndex) return;
      ev.preventDefault(); ev.stopPropagation();
      toggleDrawer(true);
    }
  }

  function bindOnce(){
    if (SHARED.bound) return;
    SHARED.bound = true;
    HANDLERS.bound = true; // keep legacy flag in sync

    document.body.addEventListener("mouseenter", onEnter, true);
    document.body.addEventListener("mouseleave", onLeave, true);
    document.body.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeydown, true);
  }

  /* ================================= setup ============================== */
  function setup(payload){
    try{
      if (!payload || !payload.terms || !payload.terms.length) return;
      index = buildIndex(payload);
      SHARED.index = index; // share for hotkey and other copies
      wrapMatches(index);
      stitchMultiWord(index);
      bindOnce();
    } catch(e) { console.error("EMS Glossary setup failed:", e); }
  }

  window.EMSGlossary = { setup, __bound: true };

  // Bootstrap queued payloads if Python pushed them before this script
  if (Array.isArray(window.__EMS_PAYLOAD) && window.__EMS_PAYLOAD.length) {
    const cp = window.__EMS_PAYLOAD.slice();
    window.__EMS_PAYLOAD.length = 0;
    cp.forEach(p => { try { setup(p); } catch(e) { console.error(e); } });
  }
})();

