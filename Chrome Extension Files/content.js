
// content.js — tag-colored highlights, scroll-inside popup, lightbox, options (font scale, sizes)
let GLOSSARY = [];
let LOOKUP = {};
let META = {
  caseSensitive: false,
  highlightUnderline: true,
  useTagColors: true,
  fontScale: 1.0,
  popupMaxHeightVh: 76,
  popupMaxWidthPx: 560,
  imageThumbMaxW: 200,
  imageThumbMaxH: 160
};
let TAGS = {};

const EXCLUDED_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "CODE", "PRE", "TEXTAREA", "INPUT", "SELECT", "KBD", "SAMP"]);
const HIGHLIGHT_CLASS = "ems-glossary-highlight";
const DATA_MARKED = "data-ems-glossary-marked";

chrome.runtime.sendMessage({ type: "getGlossaryCache" }, (res) => {
  if (!res) return;
  GLOSSARY = res.cache || [];
  LOOKUP = res.index || {};
  META = Object.assign(META, res.meta || {});
  TAGS = res.tags || {};
  injectStyles();
  const compiled = buildCompiledChunks();
  startHighlighting(compiled);
  setupMutationObserver(compiled);
});

function injectStyles() {
  const css = `
  .ems-glossary-highlight {
    background: #fff59d;
    border-bottom: ${META.highlightUnderline ? "1px dotted rgba(0,0,0,0.5)" : "none"};
    border-radius: 6px;
    padding: 0 .2em;
    cursor: help;
    box-decoration-break: clone;
  }
  #ems-pop {
    position: fixed;
    z-index: 2147483647;
    max-width: ${META.popupMaxWidthPx || 560}px;
    min-width: 320px;
    max-height: ${META.popupMaxHeightVh || 76}vh;
    color: #e6e6eb;
    background: linear-gradient(180deg, #171923, #12131b);
    background-color: #12131b;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
    box-shadow: 0 20px 50px rgba(0,0,0,0.55);
    padding: 12px 14px 12px 14px;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    font-size: ${Math.round((META.fontScale || 1) * 14)}px;
    line-height: 1.45;
    display: none;
    isolation: isolate;
    contain: strict;
    overflow: auto;                    /* scroll inside */
    overscroll-behavior: contain;      /* prevent page scroll chaining */
    -webkit-overflow-scrolling: touch;
    backface-visibility: hidden;
  }
  #ems-pop * { mix-blend-mode: normal; }
  #ems-pop .titlebar { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom: 8px; position: sticky; top: -8px; background: linear-gradient(180deg, #171923, #12131b); padding-top: 8px; }
  #ems-pop .term-chip {
    display:inline-block; font-weight: 800; letter-spacing: .2px; padding: 4px 10px; border-radius: 10px;
    color:#1a1b22; background:#fff59d; border-bottom:${META.highlightUnderline ? "1px dotted rgba(0,0,0,0.4)" : "none"}; user-select:none;
  }
  #ems-pop .controls { display:flex; gap:8px; align-items:center; }
  #ems-pop .btn {
    border: 1px solid rgba(255,255,255,0.08); background: #202538; color: #cfd3e6;
    padding: 4px 8px; border-radius: 8px; font-size: 12px; text-decoration: none; cursor: pointer;
  }
  #ems-pop .btn.primary { background:#4f7cff; color:white; border-color: #4f7cff; }
  #ems-pop .btn.icon { width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; padding:0; }
  #ems-pop .hero { background: linear-gradient(180deg, #1f2230, #151826); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 10px 12px; margin-bottom: 8px; color: #e6e6eb; }
  #ems-pop .chips { display:flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 2px 0; }
  #ems-pop .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: #2a2f45; border: 1px solid rgba(255,255,255,0.06); color: #cfd3e6; }
  #ems-pop .images { display:flex; gap:10px; margin: 8px 0; flex-wrap: wrap; }
  #ems-pop .images img { max-width: ${META.imageThumbMaxW || 200}px; max-height: ${META.imageThumbMaxH || 160}px; border-radius: 10px; border:1px solid rgba(255,255,255,0.06); cursor: zoom-in; }
  #ems-pop .section { background: #161928; border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 10px 12px; margin-top: 8px; }
  #ems-pop .section h4 { margin: 0 0 6px 0; font-size: 13px; color: #cfd3e6; letter-spacing: .2px; }
  #ems-pop .section ul { margin: 0 0 0 18px; }
  #ems-pop a { color: #9fc4ff; text-decoration: none; }
  #ems-pop .footer { margin-top: 8px; display:flex; justify-content: space-between; align-items: center; font-size:12px; color:#a8adc6; }
  #ems-pop.dragging { cursor: grabbing; user-select: none; }

  /* Lightbox */
  #ems-lightbox {
    position: fixed; inset: 0; z-index: 2147483647;
    background: rgba(0,0,0,.8);
    display: none; align-items: center; justify-content: center;
  }
  #ems-lightbox img { max-width: calc(100vw - 48px); max-height: calc(100vh - 48px); border-radius: 8px; box-shadow: 0 8px 40px rgba(0,0,0,.6); }
  `;
  const style = document.createElement("style");
  style.id = "ems-inline-style";
  style.textContent = css;
  document.documentElement.appendChild(style);
}

function buildCompiledChunks() {
  const tokens = Object.keys(LOOKUP);
  if (!tokens.length) return [];
  const escaped = tokens.map(escapeRegex).sort((a,b) => b.length - a.length);
  const parts = chunkRegex(escaped, 900);
  const flags = META.caseSensitive ? 'g' : 'gi';
  return parts.map(p => new RegExp('\\b(' + p + ')\\b', flags));
}

function startHighlighting(compiledChunks) {
  try {
    if (!compiledChunks || !compiledChunks.length) return;
    const walkers = getTextNodes(document.body);
    for (const node of walkers) highlightNodeWithChunks(node, compiledChunks);
    ensureLightbox();
  } catch (e) { console.warn("EMS Glossary highlight error", e); }
}

function setupMutationObserver(compiledChunks) {
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) for (const node of m.addedNodes) {
      if (node.nodeType === Node.TEXT_NODE) {
        if (shouldSkip(node.parentElement)) continue;
        highlightNodeWithChunks(node, compiledChunks);
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (shouldSkip(node)) continue;
        for (const tn of getTextNodes(node)) highlightNodeWithChunks(tn, compiledChunks);
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

function getTextNodes(root) {
  const out = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      const parent = node.parentElement;
      if (!parent || shouldSkip(parent)) return NodeFilter.FILTER_REJECT;
      if (parent.closest(`[${DATA_MARKED}]`)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  let n; while ((n = walker.nextNode())) out.push(n);
  return out;
}

function shouldSkip(el) {
  if (!el) return true;
  if (el.closest && el.closest("#ems-pop")) return true; // never highlight inside popup
  if (EXCLUDED_TAGS.has(el.tagName)) return true;
  if (el.isContentEditable) return true;
  if (el.closest && el.closest(`.${HIGHLIGHT_CLASS}`)) return true;
  return false;
}

function highlightNodeWithChunks(textNode, compiled) {
  if (!textNode || !textNode.nodeValue) return;
  let remainingNode = textNode;
  for (const re of compiled) {
    remainingNode = highlightNodeWithRegex(remainingNode, re);
    if (!remainingNode) break;
  }
}

function highlightNodeWithRegex(textNode, re) {
  if (!re) return textNode;
  let match; let currentNode = textNode;
  while ((match = re.exec(currentNode.nodeValue)) !== null) {
    const term = match[1];
    const key = META.caseSensitive ? term : term.toLowerCase();
    const idx = LOOKUP[key];
    if (idx == null) continue;
    const entry = GLOSSARY[idx];
    if (!entry) continue;

    const start = match.index;
    const end = start + term.length;
    const before = currentNode.nodeValue.slice(0, start);
    const after = currentNode.nodeValue.slice(end);

    const span = document.createElement("span");
    span.className = HIGHLIGHT_CLASS;
    span.setAttribute(DATA_MARKED, "1");
    span.textContent = currentNode.nodeValue.slice(start, end);
    span.dataset.emsId = entry.id;

    // Tag-colored highlight
    if (META.useTagColors && entry.primary_tag) {
      const tag = TAGS[entry.primary_tag];
      const accent = (tag && (tag.accent || tag.color)) || null;
      if (accent) span.style.background = accent;
    }
    if (META.highlightUnderline) span.style.borderBottom = "1px dotted rgba(0,0,0,0.5)";

    attachPopoverHandlers(span);

    const afterNode = document.createTextNode(after);
    const parent = currentNode.parentNode;
    parent.insertBefore(document.createTextNode(before), currentNode);
    parent.insertBefore(span, currentNode);
    parent.insertBefore(afterNode, currentNode);
    parent.removeChild(currentNode);

    currentNode = afterNode;
    re.lastIndex = 0;
  }
  return currentNode;
}

let HIDE_TIMER = null;
let CURRENT_ANCHOR = null;
let PINNED = false;
let DRAG = null;

function attachPopoverHandlers(el) {
  const pop = ensurePopover();
  function show() {
    clearTimeout(HIDE_TIMER);
    CURRENT_ANCHOR = el;
    const id = el.dataset.emsId;
    const entry = GLOSSARY.find(x => x.id === id);
    renderPopover(pop, entry);
    pop.style.display = "block";
    if (!PINNED) {
      positionPopoverAbsolute(pop, el);
      pop.style.position = "absolute";
    } else {
      pop.style.position = "fixed";
    }
  }
  function scheduleHide() {
    if (PINNED) return;
    clearTimeout(HIDE_TIMER);
    HIDE_TIMER = setTimeout(() => { pop.style.display = "none"; CURRENT_ANCHOR = null; }, 180);
  }
  el.addEventListener("mouseenter", show);
  el.addEventListener("mouseleave", scheduleHide);
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    const visible = pop.style.display !== "none";
    if (visible && CURRENT_ANCHOR === el && !PINNED) {
      pop.style.display = "none"; CURRENT_ANCHOR = null;
    } else { show(); }
  });
}

function ensurePopover() {
  let pop = document.getElementById("ems-pop");
  if (!pop) {
    pop = document.createElement("div");
    pop.id = "ems-pop";
    pop.innerHTML = `
      <div class="titlebar">
        <span class="term-chip"></span>
        <div class="controls">
          <a class="btn action-watch" target="_blank" rel="noopener" style="display:none;">Watch</a>
          <a class="btn action-notes" target="_blank" rel="noopener" style="display:none;">Notes</a>
          <button class="btn icon pin" title="Pin">📌</button>
          <button class="btn icon close" title="Close">✕</button>
        </div>
      </div>
      <div class="hero def"></div>
      <div class="chips aliases"></div>
      <div class="chips tags"></div>
      <div class="images"></div>
      <div class="sections"></div>
      <div class="footer"><span>EMS Glossary</span><a class="more" target="_blank" rel="noopener">More</a></div>
    `;
    document.body.appendChild(pop);

    // Intercept wheel to scroll inside
    pop.addEventListener("wheel", (e) => {
      const canScroll = pop.scrollHeight > pop.clientHeight;
      if (!canScroll) return;
      e.preventDefault();
      pop.scrollTop += e.deltaY;
    }, { passive: false });

    // Also intercept touchmove for mobile
    let touchStartY = 0;
    pop.addEventListener("touchstart", (e) => { if (e.touches[0]) touchStartY = e.touches[0].clientY; }, { passive: true });
    pop.addEventListener("touchmove", (e) => {
      const canScroll = pop.scrollHeight > pop.clientHeight;
      if (!canScroll) return;
      const y = e.touches[0]?.clientY || 0;
      pop.scrollTop += (touchStartY - y);
      touchStartY = y;
      e.preventDefault();
    }, { passive: false });

    // Hover hand-off
    pop.addEventListener("mouseenter", () => { clearTimeout(HIDE_TIMER); });
    pop.addEventListener("mouseleave", () => {
      if (PINNED) return;
      clearTimeout(HIDE_TIMER);
      HIDE_TIMER = setTimeout(() => { pop.style.display = "none"; CURRENT_ANCHOR = null; }, 180);
    });

    // Titlebar buttons
    const pinBtn = pop.querySelector(".pin");
    const closeBtn = pop.querySelector(".close");
    pinBtn.addEventListener("click", () => {
      PINNED = !PINNED;
      if (PINNED) {
        pop.style.position = "fixed";
        pinBtn.textContent = "📍";
      } else {
        pinBtn.textContent = "📌";
      }
    });
    closeBtn.addEventListener("click", () => {
      pop.style.display = "none"; CURRENT_ANCHOR = null; PINNED = false; pop.querySelector(".pin").textContent = "📌";
    });

    // Dragging when pinned: drag by the titlebar
    const titlebar = pop.querySelector(".titlebar");
    titlebar.style.cursor = "grab";
    titlebar.addEventListener("mousedown", (e) => {
      if (!PINNED) return;
      e.preventDefault();
      const rect = pop.getBoundingClientRect();
      DRAG = { offsetX: e.clientX - rect.left, offsetY: e.clientY - rect.top };
      pop.classList.add("dragging");
      const move = (ev) => {
        if (!DRAG) return;
        let x = ev.clientX - DRAG.offsetX;
        let y = ev.clientY - DRAG.offsetY;
        x = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, x));
        y = Math.max(8, Math.min(window.innerHeight - pop.offsetHeight - 8, y));
        pop.style.left = x + "px";
        pop.style.top = y + "px";
      };
      const up = () => {
        DRAG = null;
        pop.classList.remove("dragging");
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });

    // Reposition while visible
    document.addEventListener("scroll", () => {
      if (pop.style.display !== "none" && CURRENT_ANCHOR && !PINNED) positionPopoverAbsolute(pop, CURRENT_ANCHOR);
    }, { passive: true });
    window.addEventListener("resize", () => {
      if (pop.style.display !== "none") {
        if (PINNED) {
          const rect = pop.getBoundingClientRect();
          let x = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, rect.left));
          let y = Math.max(8, Math.min(window.innerHeight - pop.offsetHeight - 8, rect.top));
          pop.style.left = x + "px";
          pop.style.top = y + "px";
        } else if (CURRENT_ANCHOR) {
          positionPopoverAbsolute(pop, CURRENT_ANCHOR);
        }
      }
    });
  }
  return pop;
}

function renderPopover(pop, entry) {
  const termChip = pop.querySelector(".term-chip");
  const defEl = pop.querySelector(".def");
  const aliasesWrap = pop.querySelector(".aliases");
  const tagsWrap = pop.querySelector(".tags");
  const imagesWrap = pop.querySelector(".images");
  const sectionsWrap = pop.querySelector(".sections");
  const moreLink = pop.querySelector(".more");

  termChip.textContent = entry?.names?.[0] || entry?.id || "";
  // Use tag accent on chip background if available
  if (META.useTagColors && entry?.primary_tag && TAGS[entry.primary_tag]?.accent) {
    termChip.style.background = TAGS[entry.primary_tag].accent;
  } else {
    termChip.style.background = "#fff59d";
  }

  defEl.textContent = entry?.definition || "";

  // Actions (Watch / Notes) in titlebar
  const watchBtn = pop.querySelector(".action-watch");
  const notesBtn = pop.querySelector(".action-notes");
  watchBtn.style.display = "none"; notesBtn.style.display = "none";
  if (Array.isArray(entry?.actions)) {
    for (const a of entry.actions) {
      const label = (a.label || "").toLowerCase();
      if (label.includes("watch")) {
        watchBtn.href = a.href; watchBtn.style.display = "inline-flex";
        if (a.variant === "primary") watchBtn.classList.add("primary"); else watchBtn.classList.remove("primary");
      } else if (label.includes("note")) {
        notesBtn.href = a.href; notesBtn.style.display = "inline-flex";
        if (a.variant === "primary") notesBtn.classList.add("primary"); else notesBtn.classList.remove("primary");
      }
    }
  }

  // Aliases/abbr chips
  aliasesWrap.innerHTML = "";
  const aliasList = [];
  if (Array.isArray(entry?.aliases)) aliasList.push(...entry.aliases);
  if (Array.isArray(entry?.abbr)) aliasList.push(...entry.abbr);
  for (const a of aliasList) {
    const el = document.createElement("span");
    el.className = "chip";
    el.textContent = a;
    aliasesWrap.appendChild(el);
  }

  // Tags chips
  tagsWrap.innerHTML = "";
  const tagList = [];
  if (entry?.primary_tag) tagList.push(entry.primary_tag);
  if (Array.isArray(entry?.tags)) tagList.push(...entry.tags);
  for (const t of tagList) {
    const el = document.createElement("span");
    el.className = "chip";
    el.textContent = t;
    tagsWrap.appendChild(el);
  }

  // Images with lightbox
  imagesWrap.innerHTML = "";
  if (Array.isArray(entry?.images)) {
    for (const im of entry.images) {
      if (!im?.src) continue;
      const img = document.createElement("img");
      img.src = im.src; img.alt = im.alt || "";
      img.addEventListener("click", () => openLightbox(im.src));
      imagesWrap.appendChild(img);
    }
  }

  // Sections (same as before)
  sectionsWrap.innerHTML = "";
  const sectionOrder = [
    "why_it_matters",
    "how_youll_see_it",
    "problem_solving",
    "pathophysiology",
    "diagnosis",
    "imaging",
    "treatment",
    "mnemonics",
    "pearls",
    "pitfalls",
    "red_flags",
    "algorithm",
    "exam_appearance",
    "see_also",
    "prerequisites",
    "differentials",
    "actions",
    "cases"
  ];
  const pretty = (k) => k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()).replace("Dont", "Don't");

  const addSection = (key, value) => {
    if (value == null) return;
    const sec = document.createElement("div");
    sec.className = "section";
    const h = document.createElement("h4");
    h.textContent = pretty(key);
    sec.appendChild(h);

    if (key === "differentials" && Array.isArray(value)) {
      const ul = document.createElement("ul");
      for (const item of value) {
        const li = document.createElement("li");
        if (item && typeof item === "object") {
          const name = item.name || item.id || "";
          const hint = item.hint ? ` — ${item.hint}` : "";
          if (item.id) {
            const a = document.createElement("a"); a.href = "#"; a.textContent = name;
            a.onclick = (e) => { e.preventDefault(); openById(item.id); };
            li.appendChild(a); li.appendChild(document.createTextNode(hint));
          } else { li.textContent = name + hint; }
        } else { li.textContent = String(item); }
        ul.appendChild(li);
      }
      sec.appendChild(ul);
    } else if (key === "actions" && Array.isArray(value)) {
      const wrap = document.createElement("div"); wrap.style.display = "flex"; wrap.style.gap = "8px"; wrap.style.flexWrap = "wrap";
      for (const a of value) {
        const btn = document.createElement("a");
        btn.className = "btn" + (a.variant === "primary" ? " primary" : "");
        btn.href = a.href || "#"; btn.target = "_blank"; btn.rel = "noopener";
        btn.textContent = a.label || "Open";
        wrap.appendChild(btn);
      }
      sec.appendChild(wrap);
    } else if (key === "cases" && Array.isArray(value)) {
      for (const c of value) {
        const card = document.createElement("div");
        card.style.background = "#141828";
        card.style.border = "1px solid rgba(255,255,255,.06)";
        card.style.borderRadius = "10px";
        card.style.padding = "8px 10px";
        card.style.marginTop = "6px";
        if (c.stem) { const p = document.createElement("div"); p.textContent = c.stem; p.style.fontWeight = "600"; card.appendChild(p); }
        if (Array.isArray(c.clues) && c.clues.length) {
          const ul = document.createElement("ul"); ul.style.margin = "4px 0 0 18px";
          for (const cl of c.clues) { const li = document.createElement("li"); li.textContent = cl; ul.appendChild(li); }
          card.appendChild(ul);
        }
        if (c.answer) { const p = document.createElement("div"); p.textContent = "Answer: " + c.answer; p.style.marginTop = "6px"; card.appendChild(p); }
        if (c.teaching) { const p = document.createElement("div"); p.textContent = c.teaching; p.style.opacity = ".9"; p.style.marginTop = "4px"; card.appendChild(p); }
        sec.appendChild(card);
      }
    } else if (key === "see_also" && Array.isArray(value)) {
      const ul = document.createElement("ul");
      for (const id of value) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "#"; a.textContent = String(id).replace(/-/g, " ");
        a.onclick = (e) => { e.preventDefault(); openById(String(id)); };
        li.appendChild(a);
        ul.appendChild(li);
      }
      sec.appendChild(ul);
    } else if (key === "prerequisites" && Array.isArray(value)) {
      const ul = document.createElement("ul");
      for (const item of value) {
        const li = document.createElement("li");
        const id = (typeof item === "string") ? item : item?.id;
        if (id) {
          const a = document.createElement("a"); a.href = "#"; a.textContent = id.replace(/-/g, " ");
          a.onclick = (e) => { e.preventDefault(); openById(id); };
          li.appendChild(a);
        } else {
          li.textContent = typeof item === "string" ? item : JSON.stringify(item);
        }
        ul.appendChild(li);
      }
      sec.appendChild(ul);
    } else {
      if (Array.isArray(value)) {
        const ul = document.createElement("ul");
        for (const item of value) { const li = document.createElement("li"); li.textContent = String(item); ul.appendChild(li); }
        sec.appendChild(ul);
      } else {
        const div = document.createElement("div"); div.textContent = String(value); sec.appendChild(div);
      }
    }
    sectionsWrap.appendChild(sec);
  };

  for (const k of sectionOrder) if (entry[k] != null) addSection(k, entry[k]);

  const skip = new Set(["id","names","aliases","abbr","patterns","primary_tag","tags","definition","sources","images","html"].concat(sectionOrder));
  for (const [k, v] of Object.entries(entry || {})) {
    if (skip.has(k) || v == null) continue;
    addSection(k, v);
  }

  const url = Array.isArray(entry?.sources) && entry.sources[0]?.url ? entry.sources[0].url : "";
  const moreLink = pop.querySelector(".more");
  if (url) { moreLink.href = url; moreLink.style.display = "inline"; }
  else { moreLink.removeAttribute("href"); moreLink.style.display = "none"; }
}

function openById(id) {
  const entry = GLOSSARY.find(x => x.id === id);
  if (!entry) return;
  const pop = ensurePopover();
  renderPopover(pop, entry);
  pop.style.display = "block";
  if (PINNED) pop.style.position = "fixed"; else if (CURRENT_ANCHOR) positionPopoverAbsolute(pop, CURRENT_ANCHOR);
}

function ensureLightbox() {
  if (document.getElementById("ems-lightbox")) return;
  const lb = document.createElement("div");
  lb.id = "ems-lightbox";
  lb.innerHTML = `<img alt="">`;
  document.body.appendChild(lb);
  lb.addEventListener("click", () => lb.style.display = "none");
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") lb.style.display = "none"; });
}
function openLightbox(src) {
  ensureLightbox();
  const lb = document.getElementById("ems-lightbox");
  const img = lb.querySelector("img");
  img.src = src; lb.style.display = "flex";
}

function positionPopoverAbsolute(pop, target) {
  const rect = target.getBoundingClientRect();
  const margin = 6;
  let top = rect.bottom + margin + window.scrollY;
  let left = rect.left + window.scrollX;
  const width = pop.offsetWidth || (META.popupMaxWidthPx || 560);
  const height = pop.offsetHeight || 320;
  if (left + width > window.scrollX + window.innerWidth - 8) left = window.scrollX + window.innerWidth - width - 8;
  if (top + height > window.scrollY + window.innerHeight - 8) top = rect.top - height - margin + window.scrollY;
  pop.style.top = `${Math.max(8, top)}px`;
  pop.style.left = `${Math.max(8, left)}px`;
}

function chunkRegex(escapedTerms, chunkSize) {
  const chunks = []; let buf = []; let len = 0;
  for (const t of escapedTerms) {
    if ((len + t.length + 1) > chunkSize && buf.length) { chunks.push(buf.join("|")); buf = [t]; len = t.length; }
    else { buf.push(t); len += t.length + 1; }
  }
  if (buf.length) chunks.push(buf.join("|")); return chunks;
}
function escapeRegex(s) { return s.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&"); }
