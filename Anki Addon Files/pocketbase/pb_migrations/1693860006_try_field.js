/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  // create temp collection with a relation field
  const coll = new Collection({ name: 'tmp_try', type: 'base', system: false });
  const f = new RelationField({
    system: false,
    id: 'userref',
    name: 'user',
    required: true,
    unique: true,
    options: {
      collectionId: '_pb_users_auth_', cascadeDelete: true, minSelect: null, maxSelect: 1, displayFields: []
    }
  });
  console.log('RelationField keys:', Object.getOwnPropertyNames(f).join(','));
  coll.fields = new FieldsList([ f ]);
  try { db.save(coll); console.log('Saved tmp_try with id:', coll.id); } catch (e) { console.log('Save error:', String(e)); }
  try { db.delete(coll); } catch (e) { /* ignore */ }
}, (db) => {});
