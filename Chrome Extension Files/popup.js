
document.getElementById("refresh").onclick = async () => {
  const res = await chrome.runtime.sendMessage({ type: "forceRefresh" });
  window.close();
};
document.getElementById("options").onclick = () => chrome.runtime.openOptionsPage();
chrome.runtime.sendMessage({ type: "getGlossaryCache" }, (res) => {
  if (!res) return;
  const n = (res.cache || []).length;
  const t = res.meta?.lastUpdated ? new Date(res.meta.lastUpdated).toLocaleString() : "never";
  const b = res.meta?.branch || "main";
  document.getElementById("meta").textContent = `${n} terms • branch ${b} • updated ${t}`;
});
