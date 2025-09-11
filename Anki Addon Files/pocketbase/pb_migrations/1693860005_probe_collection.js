/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const c = new Collection({ name: 'x', type: 'base', system: false });
  console.log('Collection keys (before):', Object.getOwnPropertyNames(c).join(','));
  try { c.fields = new FieldsList([]); } catch (e) { console.log('set fields error', String(e)) }
  try { c.schema = new FieldsList([]); } catch (e) { console.log('set schema error', String(e)) }
  console.log('Collection keys (after):', Object.getOwnPropertyNames(c).join(','));
  // Try saving empty collection then deleting
  try { db.save(c); console.log('Saved empty test collection with id:', c.id || '(none)'); db.delete(c); console.log('Deleted empty test collection'); } catch (e) { console.log('save/delete error:', String(e)) }
}, (db) => {});
