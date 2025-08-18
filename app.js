/* Minimal client-side renderer for glossary JSON.
 * Expects:
 *   glossary/index.json => { version, files: ["acth.json", ...] }
 *   glossary/terms/<file> => each term object (schema.v1.json)
 */
(function(){
  const $  = (sel, el=document)=> el.querySelector(sel);
  const $$ = (sel, el=document)=> Array.from(el.querySelectorAll(sel));
  const cardsEl = $('#cards');
  const statusEl = $('#status');
  const tagBarEl = $('#tag-bar');
  const activeFiltersEl = $('#active-filters');
  const qEl = $('#q');

  const GLOSSARY_PATH = window.GLOSSARY_PATH || 'glossary';
  const INDEX_URL = `${GLOSSARY_PATH}/index.json`;
  const TERMS_BASE = `${GLOSSARY_PATH}/terms`;

  let terms = [];
  let filtered = [];
  const activeTags = new Set();
  let termMap = new Map();

  function html(strings, ...values){
    const out = strings.reduce((acc, str, i)=>{
      let val = i < values.length ? values[i] : '';
      if(Array.isArray(val)) val = val.join('');
      return acc + str + (val ?? '');
    }, '');
    const t = document.createElement('template');
    t.innerHTML = out.trim();
    return t.content;
  }
  const escape = (s)=> String(s).replace(/[&<>"']/g, (m)=> ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

  function normalizeTerm(t){
    t.names ||= []; t.aliases ||= []; t.abbr ||= []; t.tags ||= []; t.images ||= [];
    t.see_also ||= []; t.prerequisites ||= []; t.actions ||= []; t.sources ||= [];
    t.how_youll_see_it ||= []; t.problem_solving ||= []; t.differentials ||= [];
    t.tricks ||= []; t.exam_appearance ||= []; t.treatment ||= []; t.red_flags ||= [];
    t.cases ||= []; return t;
  }
  function fetchJSON(url){
    return fetch(url, {cache:'no-store'}).then(r=>{
      if(!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
      return r.json();
    });
  }

  async function load(){
    try{
      const index = await fetchJSON(INDEX_URL);
      const files = Array.isArray(index.files) ? index.files : [];
      statusEl.textContent = `Loading ${files.length} terms…`;
      const results = await Promise.all(files.map(f=> 
        fetchJSON(`${TERMS_BASE}/${f}`).then(t=> ({ok:true, t})).catch(err=> ({ok:false, err, f}))
      ));
      const loaded = results.filter(r=> r.ok).map(r=> normalizeTerm(r.t));
      const failed = results.filter(r=> !r.ok);
      if(failed.length){ console.warn('Failed to load some terms', failed); }
      terms = loaded.sort((a,b)=> (a.names?.[0]||a.id).localeCompare(b.names?.[0]||b.id));
      termMap = new Map(terms.map(t=> [t.id, t]));
      buildTagBar();
      applyFiltersFromURL();
      render();
      handleHashLink();
      statusEl.hidden = true;
      cardsEl.hidden = false;
    }catch(err){
      console.error(err);
      statusEl.textContent = 'Failed to load glossary index. Ensure glossary/index.json is present.';
    }
  }

  function buildTagBar(){
    const tagCounts = new Map();
    for(const t of terms){
      const set = new Set([t.primary_tag, ...t.tags].filter(Boolean));
      for(const tag of set){ tagCounts.set(tag, (tagCounts.get(tag)||0) + 1); }
    }
    const tags = Array.from(tagCounts.entries()).sort((a,b)=>{
      if(b[1] !== a[1]) return b[1] - a[1];
      return a[0].localeCompare(b[0]);
    });
    tagBarEl.innerHTML = '';
    for(const [tag,count] of tags){
      const chip = document.createElement('button');
      chip.className = 'chip'; chip.type = 'button';
      chip.textContent = `${tag} · ${count}`;
      chip.dataset.tag = tag;
      chip.setAttribute('data-selected', activeTags.has(tag) ? 'true' : 'false');
      chip.addEventListener('click', ()=>{
        if(activeTags.has(tag)) activeTags.delete(tag); else activeTags.add(tag);
        chip.setAttribute('data-selected', activeTags.has(tag) ? 'true' : 'false');
        render(); syncURL(); renderActiveFilters(); scrollToTop();
      });
      tagBarEl.appendChild(chip);
    }
    renderActiveFilters();
  }

  function renderActiveFilters(){
    activeFiltersEl.innerHTML = '';
    if(activeTags.size === 0) return;
    for(const tag of activeTags){
      const el = html`<span class="chip">${escape(tag)}<span class="x" aria-label="remove filter" title="remove filter">×</span></span>`;
      el.querySelector('.x').addEventListener('click', ()=>{
        activeTags.delete(tag);
        const btn = tagBarEl.querySelector(`[data-tag="${CSS.escape(tag)}"]`);
        if(btn) btn.setAttribute('data-selected','false');
        render(); syncURL(); renderActiveFilters();
      });
      activeFiltersEl.appendChild(el);
    }
  }
  function scrollToTop(){ window.scrollTo({top:0, behavior:'smooth'}); }

  function applyFiltersFromURL(){
    const url = new URL(location.href);
    const q = url.searchParams.get('q') || '';
    const tags = (url.searchParams.get('tags') || '').split(',').filter(Boolean);
    qEl.value = q; activeTags.clear(); for(const t of tags) activeTags.add(t);
  }
  function syncURL(){
    const url = new URL(location.href);
    const q = qEl.value.trim();
    if(q) url.searchParams.set('q', q); else url.searchParams.delete('q');
    if(activeTags.size) url.searchParams.set('tags', Array.from(activeTags).join(','));
    else url.searchParams.delete('tags');
    history.replaceState(null, '', url);
  }
  function termMatches(t, q, tags){
    if(tags.size){
      const set = new Set([t.primary_tag, ...t.tags]);
      for(const tag of tags){ if(!set.has(tag)) return false; }
    }
    if(!q) return true;
    const hay = [
      t.id, ...(t.names||[]), ...(t.aliases||[]), ...(t.abbr||[]),
      t.definition||'', t.why_it_matters||'', ...(t.tags||[])
    ].join(' ').toLowerCase();
    return hay.includes(q.toLowerCase());
  }

  function render(){
    const q = qEl.value.trim();
    filtered = terms.filter(t=> termMatches(t, q, activeTags));
    cardsEl.innerHTML = '';
    if(filtered.length === 0){ cardsEl.appendChild(html`<p>No terms match your filters.</p>`); return; }
    for(const t of filtered){ cardsEl.appendChild(renderCard(t)); }
  }

  function pill(tag){
    const el = document.createElement('span');
    el.className = 'chip'; el.textContent = tag;
    el.addEventListener('click', ()=>{
      if(activeTags.has(tag)) activeTags.delete(tag); else activeTags.add(tag);
      const btn = document.querySelector(`[data-tag="${CSS.escape(tag)}"]`);
      if(btn) btn.setAttribute('data-selected', activeTags.has(tag) ? 'true' : 'false');
      render(); syncURL(); renderActiveFilters();
    });
    return el;
  }

  function renderCard(t){
    const card = document.createElement('article');
    card.className = 'card'; card.id = t.id;

    const title = document.createElement('h2');
    title.textContent = t.names?.[0] || t.id; card.appendChild(title);

    const parts = [];
    if(t.abbr?.length) parts.push(t.abbr.join(', '));
    if(t.aliases?.length) parts.push(t.aliases.join(', '));
    if(parts.length){
      const sub = document.createElement('div');
      sub.className = 'subtitle'; sub.textContent = parts.join(' · ');
      card.appendChild(sub);
    }

    const tags = document.createElement('div'); tags.className = 'tags';
    const ttags = [t.primary_tag, ...(t.tags||[])].filter(Boolean);
    for(const tag of ttags){ tags.appendChild(pill(tag)); }
    card.appendChild(tags);

    if(t.images?.length){
      const img = t.images[0];
      const media = document.createElement('div'); media.className = 'media';
      const imgel = document.createElement('img');
      imgel.alt = img.alt || ''; imgel.loading = 'lazy'; imgel.src = img.src; media.appendChild(imgel);
      if(img.credit && (img.credit.text || img.credit.href)){
        const cred = document.createElement('a');
        cred.className = 'credit'; cred.href = img.credit.href || '#'; cred.target = '_blank'; cred.rel='noopener noreferrer';
        cred.textContent = img.credit.text || 'credit'; media.appendChild(cred);
      }
      card.appendChild(media);
    }

    if(t.definition){
      const def = document.createElement('p'); def.className = 'def'; def.textContent = t.definition; card.appendChild(def);
    }

    const sections = document.createElement('div'); sections.className = 'sections';
    function addSection(title, body){
      if(!body) return;
      const det = document.createElement('details');
      const sum = document.createElement('summary'); sum.textContent = title; det.appendChild(sum);
      const content = document.createElement('div');
      if(Array.isArray(body)){
        const ul = document.createElement('ul');
        for(const item of body){ const li = document.createElement('li'); li.textContent = (typeof item === 'string') ? item : JSON.stringify(item); ul.appendChild(li); }
        content.appendChild(ul);
      }else if(typeof body === 'object' && body !== null){
        const ul = document.createElement('ul');
        for(const [k,v] of Object.entries(body)){ const li = document.createElement('li'); li.textContent = `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`; ul.appendChild(li); }
        content.appendChild(ul);
      }else{
        const p = document.createElement('p'); p.textContent = body; content.appendChild(p);
      }
      det.appendChild(content); sections.appendChild(det);
    }

    addSection('Why it matters', t.why_it_matters);
    addSection('How you’ll see it', t.how_youll_see_it);
    addSection('Problem‑solving', t.problem_solving);
    addSection('Differentials', t.differentials);
    addSection('Tricks', t.tricks);
    addSection('Exam appearance', t.exam_appearance);
    addSection('Treatment', t.treatment);
    addSection('Red flags', t.red_flags);
    if(t.algorithm){ addSection('Algorithm', t.algorithm); }

    if(t.cases?.length){
      const det = document.createElement('details');
      det.appendChild(html`<summary>Mini‑cases (${t.cases.length})</summary>`);
      const wrap = document.createElement('div');
      for(const c of t.cases){
        const div = document.createElement('div'); div.className = 'case';
        if(c.stem){ const p = document.createElement('p'); p.textContent = c.stem; div.appendChild(p); }
        if(c.clues?.length){
          const ul = document.createElement('ul'); for(const clue of c.clues){ const li = document.createElement('li'); li.textContent = clue; ul.appendChild(li); }
          div.appendChild(ul);
        }
        if(c.answer){ const p = document.createElement('p'); p.textContent = `Answer: ${c.answer}`; div.appendChild(p); }
        if(c.teaching){ const p = document.createElement('p'); p.textContent = c.teaching; p.style.color = 'var(--muted)'; div.appendChild(p); }
        wrap.appendChild(div);
      }
      det.appendChild(wrap); sections.appendChild(det);
    }

    if(t.see_also?.length){
      const det = document.createElement('details');
      det.appendChild(html`<summary>See also</summary>`);
      const ul = document.createElement('ul');
      for(const id of t.see_also){
        const li = document.createElement('li');
        const a = document.createElement('a'); a.textContent = termMap.get(id)?.names?.[0] || id; a.href = `#${id}`;
        a.addEventListener('click', ()=> { requestAnimationFrame(()=> handleHashLink()); });
        li.appendChild(a); ul.appendChild(li);
      }
      det.appendChild(ul); sections.appendChild(det);
    }

    if(t.sources?.length){
      const det = document.createElement('details'); det.appendChild(html`<summary>Sources</summary>`);
      const ul = document.createElement('ul');
      for(const src of t.sources){
        const li = document.createElement('li');
        if(src.url){ const a = document.createElement('a'); a.href = src.url; a.target='_blank'; a.rel='noopener noreferrer'; a.textContent = src.title || src.url; li.appendChild(a); }
        else { li.textContent = src.title || JSON.stringify(src); }
        ul.appendChild(li);
      }
      det.appendChild(ul); sections.appendChild(det);
    }

    if(t.actions?.length){
      const row = document.createElement('div'); row.className = 'actions';
      for(const a of t.actions){
        if(!a.href || !a.label) continue;
        const cls = ['button']; if(a.variant) cls.push(a.variant);
        const link = document.createElement('a'); link.className = cls.join(' '); link.href = a.href; link.target='_blank'; link.rel='noopener noreferrer'; link.textContent = a.label;
        row.appendChild(link);
      }
      sections.appendChild(row);
    }
    card.appendChild(sections);
    return card;
  }

  function handleHashLink(){
    if(!location.hash) return;
    const id = location.hash.slice(1);
    const el = document.getElementById(id);
    if(el){
      el.scrollIntoView({behavior:'smooth', block:'start'});
      el.style.outline = '2px solid var(--accent)'; el.style.transition = 'outline 0.6s ease';
      setTimeout(()=> el.style.outline='none', 1200);
    }
  }
  function debounce(fn, ms=120){ let t; return (...args)=> { clearTimeout(t); t = setTimeout(()=> fn(...args), ms); }; }

  qEl.addEventListener('input', debounce(()=>{ render(); syncURL(); }, 120));
  window.addEventListener('hashchange', handleHashLink);
  load();
})();
