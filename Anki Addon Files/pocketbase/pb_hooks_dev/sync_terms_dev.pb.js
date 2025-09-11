/// <reference path="../pb_data/types.d.ts" />
// Periodically sync glossary terms from GitHub into PocketBase.
// Runs every 10 minutes and upserts terms by slug.

// Local seeding: read JSON files from the add-on's user_files/terms folder
// Folder resolution helper comments left for context; we inline joins to avoid scope issues

function readJSONFile(path){
  try {
    const data = $os.readFile(path);
    const txt = toString(data || []);
    return JSON.parse(txt || '{}');
  } catch (e) {
    throw new Error(`read ${path} failed: ${e}`);
  }
}

function listJsonFiles(base){
  const out = [];
  function walk(dir){
    let entries = [];
    try { entries = $os.readDir(dir) || []; } catch(_){ entries = []; }
    for (const it of entries){
      let name = '';
      try { name = String(it.name()); } catch(_){ name = ''; }
      if (!name) continue;
      const p = _pathJoin(dir, name);
      let isD = false; try { isD = !!it.isDir(); } catch(_){ isD=false }
      if (isD){ walk(p); continue; }
      if (/\.json$/i.test(name)) out.push(p);
    }
  }
  walk(base);
  return out;
}

function upsertTerm(slug, title, content) {
  try {
    const coll = $app.findCollectionByNameOrId('terms');
    let rec = null;
    try { rec = $app.findFirstRecordByFilter('terms', 'slug={:slug}', dbx.Params({ slug })); } catch (e) { rec = null }
    if (rec) {
      rec.set('title', title || slug);
      rec.set('content', content || {});
    } else {
      rec = new Record(coll, { slug: slug, title: title || slug, content: content || {} });
    }
    const form = new RecordUpsertForm($app, rec);
    // ensure we can write regardless of collection rules
    try { form.grantSuperuserAccess(); } catch (e) {}
    form.submit();
  } catch (e) {
    console.log('upsertTerm error:', slug, e && e.message ? e.message : String(e));
  }
}

function syncOnce(maxTerms) {
  try {
    let baseDir = 'user_files/terms';
    try {
      const pbDir = String(__hooks || '').replace(/[\\/]+pb_hooks[\\/]*$/,'');
      const addonRoot = pbDir.replace(/[\\/]+pocketbase[\\/]*$/,'');
      baseDir = addonRoot.replace(/[\\/]+$/,'') + '/user_files/terms';
    } catch(_){ }
    const files = listJsonFiles(baseDir) || [];
    if (!files.length){ console.log('EMS sync: no local terms found in', baseDir); return; }
    const limit = Math.min(maxTerms || 50000, files.length);
    for (let i=0;i<limit;i++){
      const fpath = files[i];
      const fname = String(fpath).split(/[\\/]/).pop();
      try {
        const obj = readJSONFile(fpath);
        const baseSlug = (obj && (obj.id || '')).trim() || (fname || '').replace(/\.json$/i,'');
        const slug = baseSlug.replace(/\s+/g,'-').toLowerCase();
        const title = (obj && Array.isArray(obj.names) && obj.names.length ? obj.names[0] : slug);
        upsertTerm(slug, title, obj || {});
      } catch (e) {
        console.log('sync term failed:', fname, e && e.message ? e.message : String(e));
      }
    }
    console.log(`EMS sync: finished ${limit} local terms from ${baseDir}.`);
  } catch (e) {
    console.log('EMS sync error:', e && e.message ? e.message : String(e));
  }
}

// run every 10 minutes (disabled for manual-only seeding)
// try { cronAdd('ems_terms_sync', '*/10 * * * *', () => syncOnce(120)); } catch (e) { console.log('cron add failed', e && e.message ? e.message : String(e)); }

// Simple debug endpoints to verify hooks are loaded
try { routerAdd('GET', '/ems/ping', (e) => { try { return e.json(200, { ok: true }); } catch(err){ return e.json(500, { ok:false, error: String(err) }); } }); } catch (_) {}
try { routerAdd('GET', '/ems/whoami', (e) => { const i=e.requestInfo(); const a=i&&i.auth; return e.json(200, { email: a ? (a.get('email')||'') : '' }); }); } catch(_){}
try { routerAdd('GET', '/ems/list-terms', (e) => {
  try {
    let dir = 'user_files/terms';
    try {
      const pbDir = String(__hooks || '').replace(/[\\/]+pb_hooks[\\/]*$/,'');
      const addonRoot = pbDir.replace(/[\\/]+pocketbase[\\/]*$/,'');
      dir = addonRoot.replace(/[\\/]+$/,'') + '/user_files/terms';
    } catch(_){ }
    function scan(d){
      let out = [];
      let entries = [];
      try { entries = $os.readDir(d) || []; } catch(_){ entries = []; }
      for (const it of entries){
        let name=''; try { name = String(it.name()); } catch(_){ name=''; }
        if (!name) continue;
        const p = d.replace(/[\\/]+$/,'') + '/' + name.replace(/^[\\/]+/,'');
        let isD=false; try { isD = !!it.isDir(); } catch(_){ isD=false }
        if (isD) { out = out.concat(scan(p)); continue; }
        if (/\.json$/i.test(name)) out.push(p);
      }
      return out;
    }
    const files = scan(dir);
    return e.json(200, { count: files.length, dir });
  } catch(err){ return e.json(500, { error:String(err) }); }
}); } catch(_){ }

// Allow manual trigger (allowed user(s) only)
try {
  routerAdd('POST', '/ems/sync-terms', (e) => {
    const info = e.requestInfo();
    const auth = info && info.auth;
    const email = auth ? String(auth.get('email') || '') : '';
    const allowed = ['test@test.com'];
    if (!email || allowed.indexOf(email) === -1) {
      return e.json(403, { ok:false, error: 'forbidden' });
    }
    // Full reseed: authoritative replace (delete all, then import all)
    try {
      // 1) Delete all existing terms
      try {
        while (true) {
          const batch = $app.findRecordsByFilter('terms', '', '', 200, 0, null) || [];
          if (!batch.length) break;
          for (const r of batch) { try { $app.delete(r) } catch(_){} }
          try { sleep(25) } catch(_){}
        }
      } catch(delErr){ console.log('delete all terms failed:', delErr && delErr.message ? delErr.message : String(delErr)); }

      let baseDir = 'user_files/terms';
      try {
        const pbDir = String(__hooks || '').replace(/[\\/]+pb_hooks[\\/]*$/,'');
        const addonRoot = pbDir.replace(/[\\/]+pocketbase[\\/]*$/,'');
        baseDir = addonRoot.replace(/[\\/]+$/,'') + '/user_files/terms';
      } catch(_){ }
      function scan(d){
        let out = [];
        let entries = [];
        try { entries = $os.readDir(d) || []; } catch(_){ entries = []; }
        for (const it of entries){
          let name=''; try { name = String(it.name()); } catch(_){ name=''; }
          if (!name) continue;
          const p = d.replace(/[\\/]+$/,'') + '/' + name.replace(/^[\\/]+/,'');
          let isD=false; try { isD = !!it.isDir(); } catch(_){ isD=false }
          if (isD) { out = out.concat(scan(p)); continue; }
          if (/\.json$/i.test(name)) out.push(p);
        }
        return out;
      }
      const files = scan(baseDir);
      for (let i=0;i<files.length;i++){
        const fpath = files[i];
        const fname = String(fpath).split(/[\\/]/).pop();
        try {
          let obj = {};
          try {
            const data = $os.readFile(fpath);
            const txt = toString(data || []);
            obj = JSON.parse(txt || '{}');
          } catch (pe) {
            console.log('parse failed:', fname, pe && pe.message ? pe.message : String(pe));
            obj = {};
          }
          const baseSlug = (obj && (obj.id || '')).trim() || (fname || '').replace(/\.json$/i,'');
          const slug = baseSlug.replace(/\s+/g,'-').toLowerCase();
          const title = (obj && Array.isArray(obj.names) && obj.names.length ? obj.names[0] : slug);
          try {
            const coll = $app.findCollectionByNameOrId('terms');
            let rec = null;
            try { rec = $app.findFirstRecordByFilter('terms', 'slug={:s}', dbx.Params({ s: slug })); } catch(_) { rec = null }
            if (!rec) { try { rec = $app.findFirstRecordByFilter('terms', 'slug = {:s}', dbx.Params({ s: slug })); } catch(_) { rec = null } }
            if (!rec) { try { rec = $app.findFirstRecordByFilter('terms', 'slug={:slug}', dbx.Params({ slug })); } catch(_) { rec = null } }
            if (rec) {
              rec.set('title', title || slug);
              try { rec.set('content', obj || {}); } catch(_){ }
            } else {
              rec = new Record(coll, { slug: slug, title: title || slug });
              try { rec.set('content', obj || {}); } catch(_){ }
            }
            const form = new RecordUpsertForm($app, rec);
            try { form.grantSuperuserAccess(); } catch(_){ }
            form.submit();
          } catch (werr) {
            console.log('write failed:', slug, werr && werr.message ? werr.message : String(werr));
          }
        } catch (err) {
          console.log('seed term failed:', fname, err && err.message ? err.message : String(err));
        }
      }
    } catch (se) { console.log('seed error:', se && se.message ? se.message : String(se)); }
    return e.json(200, { ok: true });
  });
} catch (e) {}

// Ensure a single term exists (idempotent upsert) – used by clients before rating
try {
  routerAdd('POST', '/ems/ensure-term', (e) => {
    try {
      const info = e.requestInfo();
      const a = info && info.auth;
      const email = a ? String(a.get('email')||'') : '';
      const allowed = ['test@test.com'];
      if (!email || allowed.indexOf(email) === -1) return e.json(403, { ok:false, error:'forbidden' });
      const b = (info && info.body) || {};
      const slug = String(b.slug||'').trim();
      const title = String(b.title||'').trim();
      const content = b.content || {};
      if (!slug) return e.json(400, { ok:false, error:'missing slug' });
      try {
        const coll = $app.findCollectionByNameOrId('terms');
        let rec = null;
        try { rec = $app.findFirstRecordByFilter('terms', 'slug={:s}', dbx.Params({ s: slug })); } catch(_) { rec = null }
        if (!rec) { try { rec = $app.findFirstRecordByFilter('terms', 'slug = {:s}', dbx.Params({ s: slug })); } catch(_) { rec = null } }
        if (!rec) { try { rec = $app.findFirstRecordByFilter('terms', 'slug={:slug}', dbx.Params({ slug })); } catch(_) { rec = null } }
        if (rec) {
          rec.set('title', title || slug);
          try { rec.set('content', content || {}); } catch(_){ }
        } else {
          rec = new Record(coll, { slug: slug, title: title || slug });
          try { rec.set('content', content || {}); } catch(_){ }
        }
        const form = new RecordUpsertForm($app, rec);
        try { form.grantSuperuserAccess(); } catch(_){ }
        form.submit();
      } catch (werr) {
        return e.json(500, { ok:false, error: (werr && werr.message) ? werr.message : String(werr) });
      }
      return e.json(200, { ok:true });
    } catch (err) {
      return e.json(500, { ok:false, error: (err && err.message) ? err.message : String(err) });
    }
  });
} catch (e) { console.log('ensure-term route failed', e && e.message ? e.message : String(e)); }

// Credits-related PocketBase features removed; credits now come only from term JSON
