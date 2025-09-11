/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  try {
    console.log('db type:', typeof db);
    if (db) {
      const keys = [];
      for (const k in db) { keys.push(k) }
      console.log('db enumerable keys:', keys.join(','));
      console.log('db own names:', Object.getOwnPropertyNames(db).join(','));
      const proto = Object.getPrototypeOf(db);
      if (proto) {
        console.log('db proto names:', Object.getOwnPropertyNames(proto).join(','));
      }
    }
  } catch (e) { console.log('Probe error:', String(e)) }
}, (db) => { /* down */ });
