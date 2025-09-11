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

  function emsLog(level, message, data){
    try{
      const msg = encodeURIComponent(String(message||''));
      const payload = encodeURIComponent(JSON.stringify(data||{}));
      if (window.pycmd) pycmd(`ems_log:${level}:${msg}:${payload}`);
    }catch(_){ /* ignore */ }
  }

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

    try{ emsLog('DEBUG','index.built',{terms:(payload.terms||[]).length, patterns:Object.keys(mapCandidates).length}); }catch(_){ }
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
    let wrapped = 0;

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
      wrapped++;
    }

    for (const [node, frag] of edits) if (node.parentNode) node.parentNode.replaceChild(frag, node);
    try{ emsLog('DEBUG','index.wrap',{wrapped}); }catch(_){ }
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
    // Use safe, ASCII-friendly icons (entities) to avoid mojibake across encodings.
    return `<div class="ems-topbar">
      <a href="#" class="ems-pill" data-ems-learnall="1"><span class="i">&#x21BB;</span><span>Review all</span></a>
      <a href="#" class="ems-pill" data-ems-pin="1"><span class="i">&#x1F4CC;</span><span>Pin</span></a>
      <button type="button" class="ems-iconbtn" data-ems-close="1" aria-label="Close">&times;</button>
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

    // Retry link if prior fetch timed out
    body.querySelectorAll('[data-ems-retry]').forEach(a => {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        const tid = a.getAttribute('data-ems-retry');
        if (!tid) return;
        openTermInPlace(tid);
      });
    });

    // Rating: fetch and wire handlers
    body.querySelectorAll('.ems-ratingbar').forEach(box => {
      const tid = box.getAttribute('data-ems-tid');
      if (!tid) return;
      const avgEl = box.querySelector('.ems-rating-avg');
      const starsEl = box.querySelector('.ems-rating-stars');
      // Credits now live in a dedicated block under the rating bar
      let creditsEl = null;
      try {
        const pop = ensureSingletonPopover();
        creditsEl = (pop && pop.querySelector(".ems-creditsblock[data-ems-tid='"+tid+"']")) || null;
        if (!creditsEl) creditsEl = document.querySelector(".ems-creditsblock[data-ems-tid='"+tid+"']");
        if (!creditsEl && box && box.nextElementSibling && box.nextElementSibling.classList && box.nextElementSibling.classList.contains("ems-creditsblock")) creditsEl = box.nextElementSibling;
      } catch(e){ creditsEl = null }
      function paint(my, avg, count){
        if (avgEl){
          const txt = (count>0? (avg.toFixed(2)+"/"+5+" | "+count): "No ratings");
          avgEl.textContent = txt;
          if (avg < 3.5 && count>0) box.classList.add('is-low'); else box.classList.remove('is-low');
        }
        if (starsEl){
          starsEl.querySelectorAll('[data-star]').forEach(btn => {
            const s = parseInt(btn.getAttribute('data-star')||'0');
            if (my && s <= my) btn.classList.add('is-on'); else btn.classList.remove('is-on');
          });
        }
      }

      function renderCredits(arr, container){
        if (!container) return;
        const chips = (container.querySelector && container.querySelector('.ems-credits')) || container;
        try{
          const html = arr.slice(0,6).map(c => {
            const img = c.avatar ? `<img src="${escHtml(c.avatar)}" alt="">` : '';
            const label = escHtml(c.display||'User');
            const subs = (typeof c.submissions==='number') ? ` #${c.submissions}` : '';
            const avgt = (typeof c.avg==='number') ? ` | ${c.avg.toFixed(2)}` : '';
            const title = `${label}${subs}${avgt}`;
            return `<span class="ems-creditchip" title="${title}">${img}<span>${label}</span></span>`;
          }).join(' ');
          if (arr && arr.length > 0) chips.innerHTML = html; // keep prefill if PB empty
        }catch(e){}
      }

      try{
        const raw = (creditsEl && creditsEl.getAttribute("data-init-credits")) || "";
        if (raw){
          try{ const stub = JSON.parse(raw); if (Array.isArray(stub) && stub.length){
            if (creditsEl) renderCredits(stub, creditsEl);
          } }catch(e){}
        }
      }catch(e){}
      // Remove any stale prefill attempt to topbar (credits moved below)

      // Initial fetch
      if (window.pycmd){
        pycmd(`ems_glossary:rate:get:${tid}`, ret => {
          if (!ret || ret.ok===false) return;
          const avg = typeof ret.avg==='number'? ret.avg : 0;
          const count = ret.count||0; const mine = ret.mine||0;
          paint(mine, avg, count);
        });
        pycmd(`ems_glossary:credits:get:${tid}`, ret => {
          if (!ret || !creditsEl) return;
          try{
            const arr = (ret && Array.isArray(ret.credits)) ? ret.credits : [];
            if (arr.length) renderCredits(arr, creditsEl);
          }catch(e){}
        });
      }

      // Click to rate
      starsEl && starsEl.querySelectorAll('[data-star]').forEach(btn => {
        btn.addEventListener('click', ev => {
          ev.preventDefault();
          const s = parseInt(btn.getAttribute('data-star')||'0');
          if (!window.pycmd) return;
          // Show quick loading toast
          toast("Loading...");
          pycmd(`ems_glossary:rate:set:${tid}:${s}`, ret => {
            if (!ret || ret.ok===false) {
              const msg = (ret && ret.error) ? String(ret.error) : 'Action failed';
              toast(msg.indexOf('Not logged in')>=0 ? 'Login required' : ('Rating failed: ' + msg));
              return;
            }
            const avg = typeof ret.avg==='number'? ret.avg : 0; const count = ret.count||0; const mine = ret.mine||s;
            paint(mine, avg, count);
          });
        });
      });
    });

    /* COMMENTS FEATURE DISABLED: inline comments block */
    // body.querySelectorAll('.ems-comments').forEach(...)

    p.querySelectorAll("img.ems-img").forEach(img=>{
      img.addEventListener("click",(ev)=>{
        const w=window.open(img.getAttribute("src"),"_blank");
        if(w) ev.preventDefault();
      });
    });

    trapScrollInside(body);
  }

  /* ===================== suggest-term helper (selection) ==================== */
  function ensureSuggestBtn(){
    let b = document.querySelector('.ems-suggestbtn');
    if (b && b.isConnected) return b;
    b = document.createElement('button');
    b.className = 'ems-suggestbtn'; b.type = 'button'; b.textContent = 'Suggest term?';
    b.addEventListener('click', ()=>{
      const sel = window.getSelection();
      const txt = (sel && sel.toString()) ? sel.toString().trim() : '';
      if (!txt) { b.style.display='none'; return; }
      if (window.pycmd) pycmd(`ems_glossary:suggest:${encodeURIComponent(txt)}`);
      b.style.display='none';
      try{ sel.removeAllRanges(); }catch(e){}
    });
    document.body.appendChild(b);
    return b;
  }

  function shouldOfferSuggest(){
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return false;
    const txt = sel.toString().trim();
    if (!txt || txt.length < 2 || txt.length > 64) return false;
    const r = sel.getRangeAt(0);
    const anc = r.commonAncestorContainer && (r.commonAncestorContainer.nodeType===1? r.commonAncestorContainer : r.commonAncestorContainer.parentElement);
    if (!anc) return false;
    if (anc.closest('.ems-popover, .ems-pin, .ems-suggestbtn')) return false; // ignore our UI
    if (anc.closest('a, code, pre, .mjx-container, .MathJax')) return false;
    if (anc.closest('.ems-term')) return false; // already a term
    return true;
  }

  function placeSuggestBtn(){
    const btn = ensureSuggestBtn();
    if (!shouldOfferSuggest()){ btn.style.display='none'; return; }
    const sel = window.getSelection(); const r = sel.getRangeAt(0);
    const rect = r.getBoundingClientRect();

    // show invisibly to measure size
    btn.style.visibility='hidden'; btn.style.display='block';
    const bw = btn.offsetWidth || 160; const bh = btn.offsetHeight || 32;
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const vh = document.documentElement.clientHeight || window.innerHeight;
    const sx = window.scrollX, sy = window.scrollY;
    const M = 10;

    // default try above-right
    let x = rect.right + sx + 8;
    let y = rect.top + sy - bh - 8;

    // if overflowing right, place to the left
    if (x + bw > sx + vw - M) x = rect.left + sx - bw - 8;
    // clamp horizontally
    if (x < sx + M) x = sx + M;

    // if above top, place below selection
    if (y < sy + M) y = rect.bottom + sy + 8;
    // clamp bottom
    if (y + bh > sy + vh - M) y = sy + vh - M - bh;

    btn.style.left = Math.round(x) + 'px';
    btn.style.top  = Math.round(y) + 'px';
    btn.style.visibility='visible';
  }

  function hidePopover(){ const p=ensureSingletonPopover(); p.style.display="none"; emsLog('DEBUG','popover.hide',{}); }
  function hidePopoverSoon(){
    clearTimeout(hideTimer);
    hideTimer = setTimeout(()=>{
      const p=ensureSingletonPopover();
      if(!p.matches(":hover")) p.style.display="none";
    }, 160);
  }

  /* =================== unified open path with tokens ==================== */
  function fetchTerm(termId, done){
    // Robust fetch with one retry and a final timeout that paints an error UI
    if (!window.pycmd){ done({html:"<div class='ems-small'>No bridge.</div>"}); return; }
    let answered = false;
    const cb = (ret)=>{ if (answered) return; answered = true; done(ret||{}); };
    try { pycmd(`ems_glossary:get:${termId}`, cb); } catch(e) {}
    // Retry once shortly after
    setTimeout(()=>{ if (!answered) { try { pycmd(`ems_glossary:get:${termId}`, cb); } catch(e) {} } }, 350);
    // Hard timeout → surface a retry affordance
    setTimeout(()=>{ if (!answered) { cb({html: `<div class='ems-small'>Timed out. <a href='#' data-ems-retry='${escHtml(termId)}'>Retry</a></div>`}); } }, 1500);
  }

  function openTermNear(target, termId){
    emsLog('DEBUG','popover.open',{id: termId});
    SHARED.anchorEl = target;
    const token = ++SHARED.openToken;
    const p = ensureSingletonPopover();
    const body = p.querySelector(".ems-body");
    body.innerHTML = `<div class="ems-small" style="opacity:.8;padding:6px 0">Loading...</div>`;
    p.style.display = "block";
    positionPopover(p, target);
    bindInsidePopover();

    const cb = (ret)=>{
      if (token !== SHARED.openToken) return;  // newer request won
      window._EMS_LAST_TID = termId;
      const tbSaved = p.querySelector('.ems-topbar');
      body.innerHTML = ret && ret.html ? ret.html : "<div class='ems-small'>No content.</div>";
      try{ if (ret && ret.live){ body.setAttribute('data-live-loggedin', (ret.live.loggedIn? '1':'0')); body.setAttribute('data-live-offline', (ret.live.offline? '1':'0')); } }catch(e){}
      const curTB = body.querySelector('.ems-topbar'); if (!curTB && tbSaved) { try { body.prepend(tbSaved); } catch(e){} }
      bindInsidePopover();
      positionPopover(p, target);
      /* COMMENTS DISABLED: openCommentsPanel(termId, ret?.title) */
    };
    fetchTerm(termId, cb);
  }

  /* COMMENTS FEATURE DISABLED: comments panel helpers
  function ensureCommentsPanel(){ ... }
  function positionCommentsPanel(pop, panel){ ... }
  function openCommentsPanel(termId, title){ ... }
  */

  // Replace content in the *same* popover (used when clicking links inside it)
  function openTermInPlace(termId){
    const p = ensureSingletonPopover();
    const body = p.querySelector(".ems-body");
    const token = ++SHARED.openToken;
    const tbSaved = p.querySelector(".ems-topbar");
    body.innerHTML = `<div class="ems-small" style="opacity:.8;padding:6px 0">Loading...</div>`;
    p.style.display = "block";
    bindInsidePopover();  // keep handlers fresh
    const cb = (ret)=>{
      if (token !== SHARED.openToken) return;
      window._EMS_LAST_TID = termId;
      body.innerHTML = ret && ret.html ? ret.html : "<div class='ems-small'>No content.</div>";
      try{ if (ret && ret.live){ body.setAttribute('data-live-loggedin', (ret.live.loggedIn? '1':'0')); body.setAttribute('data-live-offline', (ret.live.offline? '1':'0')); } }catch(e){}
      const curTB = body.querySelector('.ems-topbar'); if (!curTB && tbSaved) { try { body.prepend(tbSaved); } catch(e){} }
      bindInsidePopover();
      /* COMMENTS DISABLED: openCommentsPanel(termId, ret?.title) */
    };
    fetchTerm(termId, cb);
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
      `<header><span class="title">${escHtml(obj.title||obj.tid||"Pinned")}</span><span class="spacer"></span><a href="#" class="ems-unpin" title="Close">&times;</a></header>
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
d.innerHTML="<header>Glossary <span class='tag'>G to toggle</span></header><div class='toolbar'><input placeholder='Search terms...' /><button class='ems-tagbtn'>All tags</button><div class='ems-tagmenu'></div></div><div class='ems-list'></div>";
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
          d.querySelector(".ems-tagbtn").textContent = (d.dataset.tag ? d.dataset.tag : "All tags");
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
        const icon=meta.icon||"";
        item.innerHTML=`<span class="ems-chip">${icon}</span> <span>${title}</span> <span class="ems-right">${(meta.tags||[]).join(", ")}</span>`;
        item.addEventListener("click",()=>openTermNear(item, id));
        item.addEventListener("keydown",(e)=>{ if(e.key==="Enter") openTermNear(item, id); });
        list.appendChild(item);
      }
    }
  }

  function toggleDrawer(show){
    const d=ensureDrawer();
    if (show===false){ d.classList.remove("is-open"); emsLog('DEBUG','drawer.hide',{}); return; }
    if (d.classList.contains("is-open")) { d.classList.remove("is-open"); emsLog('DEBUG','drawer.hide',{}); return; }
    populateDrawer(SHARED.index || index);
    d.classList.add("is-open");
    emsLog('DEBUG','drawer.open',{});
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
      emsLog('DEBUG','term.click.ambiguous',{ids});
      showChooserNear(el, ids);
    } else {
      const id = el.dataset.term;
      emsLog('DEBUG','term.click',{id});
      openTermNear(el, id);
    }
    try{ emsLog('DEBUG','index.stitch',{total: terms.length}); }catch(_){ }
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
    document.addEventListener('mouseup', ()=> setTimeout(placeSuggestBtn, 0), true);
    document.addEventListener('keyup',   ()=> setTimeout(placeSuggestBtn, 0), true);
    document.addEventListener('scroll',  ()=> { const b=document.querySelector('.ems-suggestbtn'); if(b) b.style.display='none'; }, true);
  }

  /* ================================= setup ============================== */
  function setup(payload){
    try{
      if (!payload || !payload.terms || !payload.terms.length) return;
      // Capture live flags (offline, loggedIn) for UI decisions
      try { SHARED.live = (payload && payload.live) ? payload.live : {}; } catch(e) { SHARED.live = {}; }
      index = buildIndex(payload);
      SHARED.index = index; // share for hotkey and other copies
      wrapMatches(index);
      stitchMultiWord(index);
      bindOnce();
    } catch(e) { console.error("EMS Glossary setup failed:", e); }
  }

  window.EMSGlossary = { setup, __bound: true };
  // Allow Python to asynchronously push rating updates without blocking UI
  window.EMSGlossary.updateRating = function(tid, avg, count, mine){
    try{
      const esc = (window.CSS && CSS.escape) ? CSS.escape : (s)=>String(s).replace(/"/g,'\\"');
      const sel = ".ems-ratingbar[data-ems-tid=\"" + esc(tid) + "\"]";
      const box = document.querySelector(sel);
      if (!box) return;
      const avgEl = box.querySelector('.ems-rating-avg');
      const starsEl = box.querySelector('.ems-rating-stars');
      const nAvg = (typeof avg === 'number') ? avg : 0;
      const nCount = (typeof count === 'number') ? count : 0;
      const nMine = (typeof mine === 'number') ? mine : 0;
      if (avgEl){
        avgEl.textContent = (nCount>0 ? (nAvg.toFixed(2)+"/"+5+" | "+nCount) : "No ratings");
        if (nAvg < 3.5 && nCount>0) box.classList.add('is-low'); else box.classList.remove('is-low');
      }
      if (starsEl){
        starsEl.querySelectorAll('[data-star]').forEach(btn => {
          const s = parseInt(btn.getAttribute('data-star')||'0');
          if (nMine && s <= nMine) btn.classList.add('is-on'); else btn.classList.remove('is-on');
        });
      }
    }catch(_){ /* ignore */ }
  };
  // COMMENTS FEATURE DISABLED: override as no-op
  window.EMSGlossary.updateComments = function(){ return; };

  // Allow Python to push comments payload lazily
  window.EMSGlossary.updateComments = function(tid, payload){
    try{
      const esc = (window.CSS && CSS.escape) ? CSS.escape : (s)=>String(s).replace(/"/g,'\\"');
      let panel = document.querySelector('.ems-comms[data-ems-tid="'+esc(tid)+'"]');
      let box = panel ? panel.querySelector('.ems-comms-content') : null;
      if (!box){
        const sel = ".ems-comments[data-ems-tid=\"" + esc(tid) + "\"]";
        box = document.querySelector(sel);
      }
      if (!box) return;
      const bodyEl = (panel || box.closest('.ems-body') || document.querySelector('.ems-body'));
      const loggedIn = (bodyEl && bodyEl.getAttribute('data-live-loggedin') === '1');
      const offline  = (bodyEl && bodyEl.getAttribute('data-live-offline')   === '1');
      const data = (payload && typeof payload === 'object') ? payload : (function(){ try{ return JSON.parse(String(payload||'{}')); }catch(_){ return {}; } })();
      const items = Array.isArray(data.items) ? data.items : [];
      const canPost = !!(data.canPost);

      // Build tree
      const byId = new Map(); const roots = [];
      items.forEach(it => { byId.set(it.id, { ...it, children: [] }); });
      byId.forEach((it) => {
        if (it.parentId && byId.has(it.parentId)) byId.get(it.parentId).children.push(it);
        else roots.push(it);
      });

      function escHtml2(s){ return (String(s||'').replace(/[&<>\"']/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]))); }
      function timeAgo(iso){ try{ const d=new Date(iso); const s=((Date.now()-d.getTime())/1000)|0; if(s<60) return `${s}s`; const m=(s/60)|0; if(m<60) return `${m}m`; const h=(m/60)|0; if(h<24) return `${h}h`; const dd=(h/24)|0; return `${dd}d`; }catch(_){ return '';} }
      function renderOne(it, depth){
        const u = it.user||{}; const disp = escHtml2(u.display||'User');
        const when = it.created ? ` · ${timeAgo(it.created)}` : '';
        const replyBtn = (canPost && !offline) ? `<button class="ems-pill" data-ems-c-act="replyui" style="display:none"></button>` : '';
        const replyLink = (canPost && !offline) ? `<a href="#" data-ems-c-act="showreply" data-parent="${escHtml2(it.id)}" class="ems-small" style="opacity:.85">Reply</a>` : '';
        const children = (it.children||[]).map(ch => renderOne(ch, depth+1)).join('');
        const form = (canPost && !offline) ? `<div class="ems-c-form" data-parent="${escHtml2(it.id)}" style="display:none;margin-top:6px"><textarea rows="2" placeholder="Reply…"></textarea><div style="display:flex;gap:6px;justify-content:flex-end;margin-top:6px"><button type="button" class="ems-pill" data-ems-c-act="post" data-parent="${escHtml2(it.id)}">Post</button></div></div>` : '';
        return `<div class="ems-comment" data-id="${escHtml2(it.id)}" style="margin:${depth? '8px 0 0 12px':'6px 0'};padding:${depth? '6px 8px':'6px 0'};border-left:${depth? '1px solid var(--ems-border)':'none'}">
          <div class="ems-comment-meta"><b>${disp}</b>${when}</div>
          <div class="ems-comment-body">${escHtml2(it.body||'')}</div>
          <div class="ems-comment-actions" style="margin-top:4px">${replyLink}</div>
          ${form}
          ${children}
        </div>`;
      }

      // Root composer
      const composer = canPost && !offline ? `<div class="ems-c-form" data-root="1"><textarea rows="3" placeholder="Add a comment…"></textarea><div style="display:flex;gap:6px;justify-content:flex-end;margin-top:6px"><button type="button" class="ems-pill" data-ems-c-act="post">Post</button></div></div>`
                                              : `<div class="ems-small" style="opacity:.85">${loggedIn? 'Comments are unavailable offline.' : 'Log in to comment.'} ${loggedIn? '' : '<a href="#" data-ems-c-act="login">Login</a>'}</div>`;
      const list = roots.map(r => renderOne(r, 0)).join('');
      box.innerHTML = composer + (list ? `<div style="margin-top:8px">${list}</div>` : `<div class='ems-small' style='opacity:.8;margin-top:4px'>No comments yet.</div>`);

      // Delegated handlers exist on the panel or body
    }catch(_){ /* ignore */ }
  };

  // Bootstrap queued payloads if Python pushed them before this script
  if (Array.isArray(window.__EMS_PAYLOAD) && window.__EMS_PAYLOAD.length) {
    const cp = window.__EMS_PAYLOAD.slice();
    window.__EMS_PAYLOAD.length = 0;
    cp.forEach(p => { try { setup(p); } catch(e) { console.error(e); } });
  }
})();

