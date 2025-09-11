/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  try {
    console.log('dbx keys:', Object.getOwnPropertyNames($dbx || {}).join(','));
    console.log('Collection proto:', Object.getOwnPropertyNames(Collection.prototype).join(','));
    console.log('FieldsList proto:', Object.getOwnPropertyNames(FieldsList.prototype).join(','));
    console.log('RelationField proto:', Object.getOwnPropertyNames(RelationField.prototype).join(','));
  } catch (e) {
    console.log('Probe error:', e && e.message ? e.message : String(e))
  }
}, (db) => { /* down */ });
