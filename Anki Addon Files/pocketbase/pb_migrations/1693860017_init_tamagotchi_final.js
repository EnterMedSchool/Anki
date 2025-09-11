/// <reference path="../pb_data/types.d.ts" />
// Create Tamagotchi collection with user + data fields
migrate((db) => {
  let coll = null;
  try { coll = db.findCollectionByNameOrId('tamagotchi'); } catch (e) {}
  if (!coll) {
    coll = new Collection({ name: 'tamagotchi', type: 'base', system: false });
    const userField = new RelationField({
      system: false,
      id: 'userref',
      name: 'user',
      required: true,
      unique: true,
      collectionId: '_pb_users_auth_',
      cascadeDelete: true,
      minSelect: null,
      maxSelect: 1
    });
    const dataField = new JSONField({ system: false, id: 'datajson', name: 'data', required: true, unique: false, options: {} });
    coll.fields = [ userField, dataField ];
    db.save(coll);
  }
  coll = db.findCollectionByNameOrId('tamagotchi');
  coll.indexes = [ 'CREATE UNIQUE INDEX idx_tamagotchi_user ON `tamagotchi` (`user`)' ];
  // Try rules referencing the relation field
  coll.listRule = 'user = @request.auth.id';
  coll.viewRule = 'user = @request.auth.id';
  coll.createRule = "@request.auth.id != '' && user = @request.auth.id";
  coll.updateRule = 'user = @request.auth.id';
  coll.deleteRule = 'user = @request.auth.id';
  try { db.save(coll); } catch (e) {
    // Fallback to using user.id in rules if needed
    coll.listRule = 'user.id = @request.auth.id';
    coll.viewRule = 'user.id = @request.auth.id';
    coll.createRule = "@request.auth.id != '' && user.id = @request.auth.id";
    coll.updateRule = 'user.id = @request.auth.id';
    coll.deleteRule = 'user.id = @request.auth.id';
    db.save(coll);
  }
}, (db) => {
  try { const c = db.findCollectionByNameOrId('tamagotchi'); if (c) { db.delete(c) } } catch (e) {}
});
