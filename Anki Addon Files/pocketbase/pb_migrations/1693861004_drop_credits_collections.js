/// <reference path="../pb_data/types.d.ts" />
// Remove credits-related collections: term_credits and user_profiles
migrate((db) => {
  try {
    try { const c = db.findCollectionByNameOrId('term_credits'); if (c) db.delete(c); } catch (_) {}
    try { const c = db.findCollectionByNameOrId('user_profiles'); if (c) db.delete(c); } catch (_) {}
  } catch (e) { throw e }
}, (db) => { /* no-op downgrade */ });

