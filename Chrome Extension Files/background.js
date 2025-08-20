
// background.js — Repo-locked fetcher for EnterMedSchool/Anki, plus tags.json
const REPO = { owner: "EnterMedSchool", repo: "Anki" };
const API_BASE = `https://api.github.com/repos/${REPO.owner}/${REPO.repo}`;
const RAW_BASE = (branch, path) => `https://raw.githubusercontent.com/${REPO.owner}/${REPO.repo}/${branch}/${path}`;

const STORAGE = {
  cache: "ems_glossary_cache_v2",
  index: "ems_glossary_index_v2",
  meta: "ems_glossary_meta_v2",
  tags: "ems_glossary_tags_v1"
};

const DEFAULT_META = {
  lastUpdated: 0,
  scheduleMinutes: 240, // every 4h
  caseSensitive: false,
  highlightUnderline: true,
  useTagColors: true,
  fontScale: 1.0,
  popupMaxHeightVh: 76,   // max height as viewport percent
  popupMaxWidthPx: 560,
  imageThumbMaxW: 200,
  imageThumbMaxH: 160
};

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarm();
  refresh().catch(console.error);
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarm();
  refresh().catch(console.error);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "ems_glossary_refresh") refresh().catch(console.error);
});

function ensureAlarm() {
  const period = DEFAULT_META.scheduleMinutes;
  chrome.alarms.create("ems_glossary_refresh", { periodInMinutes: period });
}

chrome.contextMenus.removeAll(() => {
  chrome.contextMenus.create({ id: "emsRefresh", title: "Refresh EMS glossary now", contexts: ["action"] });
});
chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "emsRefresh") refresh().catch(console.error);
});

chrome.runtime.onMessage.addListener((msg, _, sendResponse) => {
  if (msg?.type === "getGlossaryCache") {
    chrome.storage.local.get([STORAGE.cache, STORAGE.index, STORAGE.meta, STORAGE.tags], (st) => {
      sendResponse({
        cache: st[STORAGE.cache] || [],
        index: st[STORAGE.index] || {},
        meta: Object.assign({}, DEFAULT_META, st[STORAGE.meta] || {}),
        tags: st[STORAGE.tags] || {}
      });
    });
    return true;
  }
  if (msg?.type === "forceRefresh") {
    refresh().then(() => sendResponse({ ok: true })).catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
});

async function refresh() {
  const branch = await getDefaultBranch();
  const idx = await loadIndex(branch);
  const files = Array.isArray(idx?.files) ? idx.files : [];
  if (!files.length) throw new Error("No files listed in glossary/index.json");
  const normalizedPaths = files.map(p => p.includes("/") ? p : `glossary/terms/${p}`);

  const results = await Promise.allSettled(normalizedPaths.map(p => fetchJSON(RAW_BASE(branch, p))));
  const entries = [];
  for (const r of results) if (r.status === "fulfilled" && r.value && typeof r.value === "object") entries.push(r.value);

  // Fetch tags.json (colors/icons)
  let tags = {};
  try { tags = await fetchJSON(RAW_BASE(branch, "glossary/tags.json")); } catch (e) {}

  const { cache, index } = buildIndex(entries, /*caseSensitive*/ false);
  await chrome.storage.local.set({
    [STORAGE.cache]: cache,
    [STORAGE.index]: index,
    [STORAGE.tags]: tags,
    [STORAGE.meta]: Object.assign({}, DEFAULT_META, { lastUpdated: Date.now(), branch })
  });
}

async function getDefaultBranch() {
  const info = await fetchJSON(API_BASE);
  return info?.default_branch || "main";
}
async function loadIndex(branch) {
  const url = RAW_BASE(branch, "glossary/index.json");
  return await fetchJSON(url);
}
async function fetchJSON(url) {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return await res.json();
}
function buildIndex(entries, caseSensitive) {
  const seen = new Set();
  const cache = [];
  const index = {};
  const addToken = (t, i) => {
    const k = caseSensitive ? t : String(t).toLowerCase();
    if (!index[k]) index[k] = i;
  };
  for (const e of entries) {
    if (!e || !e.id || !Array.isArray(e.names)) continue;
    const signature = e.id;
    if (seen.has(signature)) continue;
    seen.add(signature);
    const i = cache.length;
    cache.push(e);
    for (const group of ["names", "aliases", "abbr", "patterns"]) {
      const arr = Array.isArray(e[group]) ? e[group] : [];
      for (const t of arr) if (t && typeof t === "string") addToken(t, i);
    }
  }
  return { cache, index };
}
