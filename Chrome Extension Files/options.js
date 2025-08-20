
const STORAGE_META = "ems_glossary_meta_v2";
const DEFAULT_META = {
  caseSensitive: false,
  highlightUnderline: true,
  useTagColors: true,
  fontScale: 1.0,
  popupMaxHeightVh: 76,
  popupMaxWidthPx: 560,
  imageThumbMaxW: 200,
  imageThumbMaxH: 160
};
document.addEventListener("DOMContentLoaded", async () => {
  const st = await chrome.storage.local.get([STORAGE_META]);
  const meta = Object.assign({}, DEFAULT_META, st[STORAGE_META] || {});
  const ids = ["fontScale","popupMaxHeightVh","popupMaxWidthPx","imageThumbMaxW","imageThumbMaxH","useTagColors","highlightUnderline"];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el.type === "checkbox") el.checked = !!meta[id];
    else el.value = meta[id];
  }
  document.getElementById("save").onclick = async () => {
    const out = {};
    for (const id of ids) {
      const el = document.getElementById(id);
      out[id] = (el.type === "checkbox") ? el.checked : Number(el.value);
    }
    const next = Object.assign({}, meta, out);
    await chrome.storage.local.set({ [STORAGE_META]: next });
    document.getElementById("msg").textContent = "Saved. Reload pages to apply.";
    setTimeout(() => document.getElementById("msg").textContent = "", 2000);
  };
});
