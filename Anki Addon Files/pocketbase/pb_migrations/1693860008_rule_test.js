/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const name = 'tmp_rule';
  try { const c = db.findCollectionByNameOrId(name); if (c) { db.delete(c) } } catch (e) {}
  const coll = new Collection({ name, type: 'base', system: false });
  coll.fields = new FieldsList([
    new TextField({ system: false, id: 'foo', name: 'foo', required: false, unique: false, options: { min: null, max: null, pattern: '' } })
  ]);
  // try rule referencing the field
  coll.listRule = 'id != null';
  try { db.save(coll); console.log('tmp_rule saved ok'); } catch (e) { console.log('tmp_rule save error:', String(e)); }
  try { db.delete(coll); } catch (e) {}
}, (db) => {});

