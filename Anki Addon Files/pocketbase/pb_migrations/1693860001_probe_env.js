/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  try {
    const names = Object.getOwnPropertyNames(globalThis);
    console.log('Probe: globals count:', names.length);
    console.log('Probe: first 120 globals:', names.slice(0,120).join(','));
    console.log('Probe types:', ['Collection','Dao','SchemaField','$app','$db','$dao','fs','$os','$apis','$security','$migrations']
      .map(n => (n+':' + (typeof globalThis[n]))).join(','));
  } catch (e) {
    console.log('Probe error:', e && e.message ? e.message : String(e))
  }
}, (db) => { /* down */ });
