/// <reference path="../pb_data/types.d.ts" />
// Collections: terms, term_ratings, user_profiles, term_credits
migrate((db) => {
  // terms
  let termsId = null;
  try {
    let c = null; try { c = db.findCollectionByNameOrId('terms') } catch(e) {}
    if (!c) {
      c = new Collection({ name: 'terms', type: 'base', system: false });
      c.fields = [
        new TextField({ system:false, id:'slug', name:'slug', required:true, unique:true, options:{ min:1, max:128, pattern:'^[a-z0-9\-]+$' } }),
        new TextField({ system:false, id:'title', name:'title', required:false, unique:false, options:{ min:0, max:256, pattern:'' } })
      ];
      c.indexes = [ 'CREATE UNIQUE INDEX idx_terms_slug ON `terms` (`slug`)' ];
      c.listRule = 'id != null'; c.viewRule = 'id != null';
      db.save(c);
      termsId = c.id;
    } else {
      termsId = c.id;
    }
  } catch(e){ throw e }

  const usersId = '_pb_users_auth_';

  // term_ratings
  try {
    let c = null; try { c = db.findCollectionByNameOrId('term_ratings') } catch(e) {}
    if (!c) {
      c = new Collection({ name: 'term_ratings', type: 'base', system: false });
      c.fields = [
        new RelationField({ system:false, id:'term', name:'term', required:true, unique:false, collectionId: termsId, cascadeDelete: true, minSelect: null, maxSelect: 1 }),
        new RelationField({ system:false, id:'user', name:'user', required:true, unique:false, collectionId: usersId, cascadeDelete: true, minSelect: null, maxSelect: 1 }),
        new TextField({ system:false, id:'stars', name:'stars', required:true, unique:false, options:{ min:1, max:1, pattern:'^[1-5]$' } })
      ];
      c.indexes = [ 'CREATE UNIQUE INDEX idx_term_ratings_unique ON `term_ratings` (`term`,`user`)' ];
      c.listRule = 'id != null'; c.viewRule = 'id != null';
      c.createRule = "@request.auth.id != '' && user = @request.auth.id";
      c.updateRule = 'user = @request.auth.id';
      c.deleteRule = 'user = @request.auth.id';
      db.save(c);
    }
  } catch(e){ throw e }

  // user_profiles
  try {
    let c = null; try { c = db.findCollectionByNameOrId('user_profiles') } catch(e) {}
    if (!c) {
      c = new Collection({ name: 'user_profiles', type: 'base', system: false });
      c.fields = [
        new RelationField({ system:false, id:'user', name:'user', required:true, unique:true, collectionId: usersId, cascadeDelete: true, minSelect: null, maxSelect: 1 }),
        new TextField({ system:false, id:'display', name:'display_name', required:false, unique:false, options:{ min:0, max:120, pattern:'' } }),
        new TextField({ system:false, id:'avatar', name:'avatar_url', required:false, unique:false, options:{ min:0, max:400, pattern:'' } }),
        new TextField({ system:false, id:'about', name:'about', required:false, unique:false, options:{ min:0, max:2048, pattern:'' } })
      ];
      c.indexes = [ 'CREATE UNIQUE INDEX idx_user_profiles_user ON `user_profiles` (`user`)' ];
      c.listRule = 'id != null'; c.viewRule = 'id != null';
      c.createRule = "@request.auth.id != '' && user = @request.auth.id";
      c.updateRule = 'user = @request.auth.id';
      c.deleteRule = 'user = @request.auth.id';
      db.save(c);
    }
  } catch(e){ throw e }

  // term_credits
  try {
    let c = null; try { c = db.findCollectionByNameOrId('term_credits') } catch(e) {}
    if (!c) {
      c = new Collection({ name: 'term_credits', type: 'base', system: false });
      c.fields = [
        new RelationField({ system:false, id:'term', name:'term', required:true, unique:false, collectionId: termsId, cascadeDelete: true, minSelect: null, maxSelect: 1 }),
        new RelationField({ system:false, id:'user', name:'user', required:true, unique:false, collectionId: usersId, cascadeDelete: true, minSelect: null, maxSelect: 1 }),
        new TextField({ system:false, id:'role', name:'role', required:false, unique:false, options:{ min:0, max:100, pattern:'' } })
      ];
      c.indexes = [ 'CREATE UNIQUE INDEX idx_term_credits_unique ON `term_credits` (`term`,`user`)' ];
      c.listRule = 'id != null'; c.viewRule = 'id != null';
      c.createRule = "@request.auth.id != '' && user = @request.auth.id";
      c.updateRule = 'user = @request.auth.id';
      c.deleteRule = 'user = @request.auth.id';
      db.save(c);
    }
  } catch(e){ throw e }
}, (db) => { /* keep data */ });

