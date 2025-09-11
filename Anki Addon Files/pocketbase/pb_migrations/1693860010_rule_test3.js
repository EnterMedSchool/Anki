/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const name = 'tmp_rule3';
  try { const c = db.findCollectionByNameOrId(name); if (c) { db.delete(c) } } catch (e) {}
  const coll = new Collection({ name, type: 'base', system: false });
  coll.fields = new FieldsList([
    new TextField({ system: false, id: 'foo', name: 'foo', required: false, unique: false, options: { min: null, max: null, pattern: '' } })
  ]);
  coll.listRule = 'data.foo != null';
  try { db.save(coll); console.log('tmp_rule3 saved ok'); } catch (e) { console.log('tmp_rule3 save error:', String(e)); }
  try { db.delete(coll); } catch (e) {}
}, (db) => {});
