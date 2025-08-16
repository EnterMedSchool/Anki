
(function(){
  const W = window;
  function py(payload){ try { return pycmd("ems:" + JSON.stringify(payload)); } catch(e){ return ""; } }
  // Bootstrap
  let BOOT = {}; try { BOOT = JSON.parse(py({op:"bootstrap"}) || "{}"); } catch(e){ BOOT={}; }
  const CFG = (W.EMS_BOOT || {});
  const TAGS = BOOT.tags || {};
  const TERMS = BOOT.terms || [];
  const ACCENTS = {}; TERMS.forEach(t=>ACCENTS[t.id]=t.accent||"#8b5cf6");

  // Build synonym map
  const syn2id = {};
  TERMS.forEach(t => {
    const arr = (t.synonyms||[]).concat([t.title||t.id]).filter(Boolean);
    arr.forEach(s => syn2id[s.toLowerCase()] = t.id);
  });
  const alt = Object.keys(syn2id).sort((a,b)=>b.length-a.length).map(x=>x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const rx = alt.length ? new RegExp("\\\\b(" + alt.join("|") + ")\\\\b","gi") : null;

  function isInside(el, sel){ while(el){ if(el.matches && el.matches(sel)) return true; el=el.parentNode; } return false; }

  function wrapTextNode(node){
    if(!rx) return;
    const txt = node.nodeValue; let m, last=0, fr=null;
    rx.lastIndex=0;
    while((m=rx.exec(txt))){
      const before = txt.slice(last, m.index);
      const matched = m[0];
      const id = syn2id[matched.toLowerCase()];
      if(!id){ continue; }
      if(!fr) fr = document.createDocumentFragment();
      if(before) fr.appendChild(document.createTextNode(before));
      const span = document.createElement("span");
      span.className="ems-term"; span.dataset.emsId=id;
      span.style.setProperty("--ems-accent", ACCENTS[id] || "#8b5cf6");
      span.textContent = matched;
      fr.appendChild(span);
      last = m.index + matched.length;
    }
    if(!fr) return;
    const after = txt.slice(last); if(after) fr.appendChild(document.createTextNode(after));
    node.parentNode.replaceChild(fr, node);
  }

  function scan(root){
    if(!root) root = document.body;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n){
        if(!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if(isInside(n.parentNode, ".ems-popover, .ems-drawer, .ems-pin")) return NodeFilter.FILTER_REJECT;
        if(isInside(n.parentNode, "script, style, textarea")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const max = (CFG.maxPerCard || 80);
    const nodes=[];
    while(nodes.length<max && walker.nextNode()){ nodes.push(walker.currentNode); }
    nodes.forEach(wrapTextNode);
  }

  function closeAllPopovers(){ document.querySelectorAll(".ems-popover").forEach(x=>x.remove()); }
  function trapScroll(el){ el.addEventListener("wheel",(ev)=>{ev.stopPropagation();},{passive:false}); el.addEventListener("touchmove",(ev)=>{ev.stopPropagation();},{passive:false}); }

  function popupHtml(termId){
    const res = py({op:"popup", id:termId});
    try { const o = JSON.parse(res||"{}"); return o.html || "<div class='ems-body'>Error</div>"; }
    catch(e){ return "<div class='ems-body'>Error</div>"; }
  }

  function showPopover(target, termId){
    closeAllPopovers();
    const html = popupHtml(termId);
    const div = document.createElement("div"); div.className="ems-popover"; div.innerHTML=html;
    document.body.appendChild(div);
    const r = target.getBoundingClientRect();
    const vw = Math.max(document.documentElement.clientWidth, window.innerWidth||0);
    let left = Math.min(Math.max(12, r.left), vw - div.offsetWidth - 12);
    let top  = Math.max(12, r.bottom + 8);
    div.style.left = left+"px"; div.style.top = top+"px";
    const body = div.querySelector(".ems-body"); if(body) trapScroll(body);
    const close = div.querySelector(".ems-close"); if(close) close.addEventListener("click",(e)=>{e.preventDefault();div.remove();});
    const btnPin = div.querySelector(".ems-pin"); if(btnPin) btnPin.addEventListener("click",(e)=>{ e.preventDefault(); pinTerm(termId, html); });
    const reviewAll = div.querySelector(".ems-reviewall"); if(reviewAll) reviewAll.addEventListener("click",(e)=>{ e.preventDefault(); toast(py({op:"learn_all", id:termId})); });
    div.addEventListener("click", (e)=>{
      const a = e.target.closest("[data-ems-learn]");
      if(a){ e.preventDefault(); const key = a.getAttribute("data-ems-learn"); toast(py({op:"learn", id:termId, section:key})); }
      const rl = e.target.closest("[data-ems-link]");
      if(rl){ e.preventDefault(); const id = rl.getAttribute("data-ems-link"); showPopover(target, id); }
    });
  }

  function pinTerm(termId, html){
    const pin = document.createElement("div"); pin.className="ems-pin";
    pin.innerHTML = "<header><span class='title'>"+termId+"</span><span class='spacer'></span><a href='#' class='ems-unpin'>✕</a></header><div class='body'>"+html+"</div>";
    document.body.appendChild(pin);
    const header = pin.querySelector("header"); let sx=0, sy=0, ox=0, oy=0, drag=false;
    header.addEventListener("mousedown",(e)=>{ drag=true; sx=e.clientX; sy=e.clientY; const rr=pin.getBoundingClientRect(); ox=rr.left; oy=rr.top; e.preventDefault(); });
    window.addEventListener("mousemove",(e)=>{ if(!drag) return; pin.style.left=(ox+(e.clientX-sx))+"px"; pin.style.top=(oy+(e.clientY-sy))+"px";});
    window.addEventListener("mouseup",()=> drag=false);
    const b = pin.querySelector(".body"); if(b) trapScroll(b);
    pin.querySelector(".ems-unpin").addEventListener("click",(e)=>{e.preventDefault(); pin.remove();});
  }

  function toast(msg){
    let text="";
    try{ const o=JSON.parse(msg||"{}"); if(o.ok && (o.added!=null)) text="Added "+o.added+" · skipped "+o.skipped; else if(o.ok!=null) text=o.ok?"Added":(o.msg||""); else text=msg; }
    catch(e){ text=msg; }
    let t = document.querySelector(".ems-float"); if(!t){ t=document.createElement("div"); t.className="ems-float"; document.body.appendChild(t); }
    t.textContent = text; t.classList.add("is-open"); setTimeout(()=> t.classList.remove("is-open"), 2000);
  }

  // Drawer
  function ensureDrawer(){
    let d = document.querySelector(".ems-drawer");
    if(d) return d;
    d = document.createElement("div");
    d.className="ems-drawer";
    d.innerHTML = "<header>Glossary <span class='tag'>G to toggle</span></header><div class='toolbar'><input type='text' placeholder='Search terms…'><button class='ems-tagbtn'>All tags ▾</button><div class='ems-tagmenu'></div></div><div class='ems-list'></div>";
    document.body.appendChild(d);
    const menu = d.querySelector(".ems-tagmenu");
    const tags = ["All tags"].concat(Object.keys(TAGS));
    tags.forEach(t=>{ const opt=document.createElement("div"); opt.className="opt"; opt.textContent=t; opt.dataset.val=t==="All tags"?"":t; menu.appendChild(opt); });
    const btn = d.querySelector(".ems-tagbtn");
    btn.addEventListener("click", ()=>{ menu.classList.toggle("is-open"); });
    menu.addEventListener("click",(e)=>{ const o=e.target.closest(".opt"); if(!o) return; menu.classList.remove("is-open"); btn.textContent=(o.textContent||"All tags")+" ▾"; d.dataset.tag = o.dataset.val || ""; renderList();});
    const inp = d.querySelector("input"); inp.addEventListener("input", renderList);
    d.addEventListener("keydown",(e)=>{ if(e.key==="Escape") d.classList.remove("is-open"); });
    return d;
  }
  function renderList(){
    const d = document.querySelector(".ems-drawer"); const list = d.querySelector(".ems-list"); list.innerHTML="";
    const q = d.querySelector("input").value.trim().toLowerCase();
    const tag = d.dataset.tag || "";
    TERMS.forEach(t=>{
      if(q){ const hay=(t.title+" "+(t.synonyms||[]).join(" ")).toLowerCase(); if(hay.indexOf(q)===-1) return; }
      if(tag && (!t.tags || t.tags.indexOf(tag)===-1)) return;
      const it = document.createElement("div"); it.className="ems-item"; it.tabIndex=0; it.dataset.open=t.id;
      const chip=document.createElement("div"); chip.className="ems-chip"; chip.style.setProperty("--ems-accent", t.accent||"#8b5cf6");
      const title=document.createElement("div"); title.className="title"; title.textContent=t.title;
      const right=document.createElement("div"); right.className="ems-right"; right.textContent=(t.tags||[]).slice(0,3).join(", ");
      it.appendChild(chip); it.appendChild(title); it.appendChild(right);
      it.addEventListener("click", ()=>{ showPopover(it, t.id); });
      list.appendChild(it);
    });
  }

  function bindTerms(){
    document.querySelectorAll(".ems-term").forEach(el=>{
      const tid = el.dataset.emsId;
      if(CFG.hoverMode==="hover"){
        let to=null;
        el.addEventListener("mouseenter", ()=>{ to=setTimeout(()=> showPopover(el, tid), CFG.hoverDelay||120); });
        el.addEventListener("mouseleave", ()=>{ if(to){ clearTimeout(to); to=null; }});
        if(CFG.clickAnywhere){
          el.addEventListener("click", (e)=>{ e.preventDefault(); showPopover(el, tid); });
        }
      }else{
        el.addEventListener("click", (e)=>{ e.preventDefault(); showPopover(el, tid); });
      }
    });
  }

  function bootstrap(){
    const root = document.getElementById("qa") || document.body;
    scan(root); bindTerms();
  }

  document.addEventListener("keydown",(e)=>{
    if(e.key.toLowerCase()==="g"){
      const d=ensureDrawer(); d.classList.toggle("is-open"); if(d.classList.contains("is-open")) renderList();
    }
  }, {capture:true});

  setTimeout(bootstrap, 80);
})();
