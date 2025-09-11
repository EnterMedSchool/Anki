/// <reference path="../pb_data/types.d.ts" />
// Ensure terms collection allows create/update for logged-in users (for rating bootstrap)
migrate((db) => {
  try {
    const c = db.findCollectionByNameOrId('terms');
    if (c) {
      c.createRule = "@request.auth.id != ''";
      c.updateRule = "@request.auth.id != ''";
      if (!c.listRule) c.listRule = 'id != null';
      if (!c.viewRule) c.viewRule = 'id != null';
      db.save(c);
    }
  } catch (e) { throw e }
}, (db) => { /* keep */ });

