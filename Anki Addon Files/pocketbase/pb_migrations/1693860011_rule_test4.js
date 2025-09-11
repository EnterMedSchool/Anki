/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const name = 'tmp_rule4';
  try { const c = db.findCollectionByNameOrId(name); if (c) { db.delete(c) } } catch (e) {}
  const coll = new Collection({ name, type: 'base', system: false });
  coll.fields = new FieldsList([
    new RelationField({ system: false, id: 'userref', name: 'user', required: true, unique: false, options: { collectionId: '_pb_users_auth_', cascadeDelete: true, minSelect: null, maxSelect: 1, displayFields: [] } })
  ]);
  coll.listRule = 'user.id = @request.auth.id';
  try { db.save(coll); console.log('tmp_rule4 saved ok'); } catch (e) { console.log('tmp_rule4 save error:', String(e)); }
  try { db.delete(coll); } catch (e) {}
}, (db) => {});
