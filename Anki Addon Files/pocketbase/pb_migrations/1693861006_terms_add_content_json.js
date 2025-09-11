/// <reference path="../pb_data/types.d.ts" />
// Add a JSON `content` field to the `terms` collection if missing.
migrate((db) => {
  try {
    const c = db.findCollectionByNameOrId('terms');
    if (!c) return;
    // Add JSON field only if not present
    try { const ex = c.fields.getByName('content'); if (ex) return; } catch(_){ }
    const f = new JSONField({
      system: false,
      id: 'content',
      name: 'content',
      required: false,
      hidden: false,
      presentable: false,
      maxSize: 0,
    });
    try { c.fields.add(f); } catch(_) { c.fields = new FieldsList([ f ]); }
    db.save(c);
  } catch (e) { throw e }
}, (db) => { /* keep */ });

