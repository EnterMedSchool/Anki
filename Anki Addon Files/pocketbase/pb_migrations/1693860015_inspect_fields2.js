/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const name = 'tmp_inspect2';
  try { const c = db.findCollectionByNameOrId(name); if (c) { db.delete(c) } } catch (e) {}
  const coll = new Collection({ name, type: 'base', system: false });
  const field = new TextField({ system: false, id: 'abc123', name: 'bar', required: false, unique: false, options: { min: null, max: null, pattern: '' } });
  coll.fields = new FieldsList([ field ]);
  db.save(coll);
  const saved = db.findCollectionByNameOrId(name);
  const jsonStr = toString(saved.marshalJSON());
  console.log('Saved coll JSON str:', jsonStr);
  db.delete(saved);
}, (db) => {});
