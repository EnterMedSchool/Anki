/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const name = 'tmp_fields3';
  try { const c = db.findCollectionByNameOrId(name); if (c) { db.delete(c) } } catch (e) {}
  const coll = new Collection({ name, type: 'base', system: false });
  const field = new TextField({ system: false, id: 'abc123', name: 'bar', required: false, unique: false, options: { min: null, max: null, pattern: '' } });
  coll.fields = [ field ]; // try plain array
  db.save(coll);
  const saved = db.findCollectionByNameOrId(name);
  console.log('Saved coll JSON str:', toString(saved.marshalJSON()));
  db.delete(saved);
}, (db) => {});
