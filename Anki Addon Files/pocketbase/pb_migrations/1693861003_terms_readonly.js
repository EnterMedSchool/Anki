/// <reference path="../pb_data/types.d.ts" />
// Make `terms` collection read-only for clients (list/view only).
// This overrides any prior rules that allowed create/update.
migrate((db) => {
  try {
    const c = db.findCollectionByNameOrId('terms');
    if (c) {
      // allow reads
      if (!c.listRule) c.listRule = 'id != null';
      if (!c.viewRule) c.viewRule = 'id != null';

      // disable writes for non-admins
      c.createRule = null;
      c.updateRule = null;
      c.deleteRule = null;

      db.save(c);
    }
  } catch (e) { throw e }
}, (db) => { /* keep as read-only */ });

