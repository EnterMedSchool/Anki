/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const name = 'tmp_inspect';
  try { const c = db.findCollectionByNameOrId(name); if (c) { db.delete(c) } } catch (e) {}
  const coll = new Collection({ name, type: 'base', system: false });
  const field = new TextField({ system: false, id: 'abc123', name: 'bar', required: false, unique: false, options: { min: null, max: null, pattern: '' } });
  coll.fields = new FieldsList([ field ]);
  db.save(coll);
  const saved = db.findCollectionByNameOrId(name);
  const fs = saved.fields; // FieldsList
  try {
    const arr = [];
    for (const k of Object.getOwnPropertyNames(fs)) { /* noop */ }
    // FieldsList likely has method to iterate; try toString or marshal
    console.log('Saved coll name:', saved.name);
    console.log('Saved fields list type:', typeof fs);
    // try to inspect via marshalJSON
    console.log('Saved coll JSON:', saved.marshalJSON ? saved.marshalJSON() : '(no marshal)');
  } catch (e) { console.log('inspect error:', String(e)) }
  db.delete(saved);
}, (db) => {});
