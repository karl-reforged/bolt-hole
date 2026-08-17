import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import worker from '../src/index.js';

const PUBLIC_ORIGIN = 'https://karl-reforged.github.io';
const ADMIN_TOKEN = 'admin-test-token-with-at-least-24-characters';
const GEORGE = { author: 'George', actor_id: 'browser-george' };
const MARY = { author: 'Mary', actor_id: 'browser-mary' };

class TestD1Statement {
  constructor(database, sql, values = []) { this.database = database; this.sql = sql; this.values = values; }
  bind(...values) { return new TestD1Statement(this.database, this.sql, values); }
  all() { return { results: this.database.prepare(this.sql).all(...this.values) }; }
  first() { return this.database.prepare(this.sql).get(...this.values) ?? null; }
  run() {
    const result = this.database.prepare(this.sql).run(...this.values);
    return { success: true, meta: { changes: Number(result.changes) } };
  }
}

class TestD1Database {
  constructor() {
    this.database = new DatabaseSync(':memory:');
    this.database.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'));
  }
  prepare(sql) { return new TestD1Statement(this.database, sql); }
  batch(statements) {
    this.database.exec('BEGIN');
    try {
      const results = statements.map((statement) => statement.run());
      this.database.exec('COMMIT');
      return results;
    } catch (error) {
      this.database.exec('ROLLBACK');
      throw error;
    }
  }
}

function makeEnv() {
  return { DB: new TestD1Database(), PUBLIC_ORIGIN, ADMIN_TOKEN };
}

function request(path, { method = 'GET', token, origin = PUBLIC_ORIGIN, cfIp, body } = {}) {
  const headers = { Origin: origin };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (cfIp) headers['CF-Connecting-IP'] = cfIp;
  return new Request(`https://worker.example${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function saveProperty(env, sourceId = 'property-1') {
  const response = await worker.fetch(request('/', {
    method: 'POST', token: ADMIN_TOKEN,
    body: { action: 'properties_upsert', properties: [{
      source_id: sourceId, address: '1 Test Road', suburb: 'Testville',
      listing_url: `https://example.com/${sourceId}`,
    }] },
  }), env);
  assert.equal(response.status, 200);
}

function identityQuery(identity) {
  return `author=${encodeURIComponent(identity.author)}&actor_id=${encodeURIComponent(identity.actor_id)}`;
}

test('property and note reads are public with exact-origin CORS', async () => {
  const env = makeEnv();
  const properties = await worker.fetch(request('/?action=properties'), env);
  assert.equal(properties.status, 200);
  assert.equal(properties.headers.get('access-control-allow-origin'), PUBLIC_ORIGIN);
  assert.deepEqual(await properties.json(), { properties: [] });
  const notes = await worker.fetch(request('/'), env);
  assert.equal(notes.status, 200);
  assert.deepEqual(await notes.json(), { notes: [] });
  const wrongOrigin = await worker.fetch(request('/', { method: 'OPTIONS', origin: 'https://evil.example' }), env);
  assert.equal(wrongOrigin.status, 403);
});

test('browser writes from an untrusted origin are rejected before storage', async () => {
  const env = makeEnv();
  const response = await worker.fetch(request('/', {
    method: 'POST', origin: 'https://evil.example',
    body: { action: 'note', property_id: 'missing', idempotency_key: crypto.randomUUID(), note: 'Bad origin' },
  }), env);
  assert.equal(response.status, 403);
  assert.deepEqual(await response.json(), { ok: false, error: 'origin_not_allowed' });
});

test('only the admin token can update property records', async () => {
  const env = makeEnv();
  const body = { action: 'properties_upsert', properties: [{ source_id: 'one', listing_url: 'https://example.com/one' }] };
  assert.equal((await worker.fetch(request('/', { method: 'POST', body }), env)).status, 401);
  const saved = await worker.fetch(request('/', { method: 'POST', token: ADMIN_TOKEN, body }), env);
  assert.deepEqual(await saved.json(), { ok: true, upserted: 1 });
});

test('property updates validate the full batch before writing', async () => {
  const env = makeEnv();
  const response = await worker.fetch(request('/', {
    method: 'POST', token: ADMIN_TOKEN,
    body: { action: 'properties_upsert', properties: [
      { source_id: 'valid', listing_url: 'https://example.com/valid' },
      { source_id: 'invalid', listing_url: 'javascript:alert(1)' },
    ] },
  }), env);
  assert.equal(response.status, 422);
  assert.deepEqual(await (await worker.fetch(request('/?action=properties'), env)).json(), { properties: [] });
});

test('property refreshes warn, archive, reactivate, and preserve manual outcomes', async () => {
  const env = makeEnv();
  const upsert = async (properties, fullSnapshot = true, sourceInventory) => worker.fetch(request('/', {
    method: 'POST', token: ADMIN_TOKEN,
    body: {
      action: 'properties_upsert',
      properties,
      full_snapshot: fullSnapshot,
      source_inventory: sourceInventory || properties.map(({ source_id, source }) => ({ source_id, source })),
    },
  }), env);
  const prop = (source_id, status) => ({
    source_id,
    source: 'domain_web',
    listing_url: `https://example.com/${source_id}`,
    ...(status ? { status } : {}),
  });
  const statuses = async () => {
    const response = await worker.fetch(request('/?action=properties'), env);
    return Object.fromEntries((await response.json()).properties.map((p) => [p.source_id, p.status]));
  };

  assert.equal((await upsert([prop('present'), prop('missing')])).status, 200);
  assert.equal((await upsert([prop('present')], false)).status, 200);
  assert.equal((await statuses()).missing, 'active');
  assert.equal((await upsert([prop('present')])).status, 200);
  assert.equal((await statuses()).missing, 'possibly_unavailable');

  env.DB.database.prepare(
    "UPDATE properties SET last_seen = datetime('now', '-22 days') WHERE source_id = 'missing'"
  ).run();
  await upsert([prop('present')]);
  assert.equal((await statuses()).missing, 'archived');

  await upsert([prop('missing')]);
  assert.equal((await statuses()).missing, 'active');

  env.DB.database.prepare("UPDATE properties SET status = 'sold' WHERE source_id = 'missing'").run();
  await upsert([prop('missing')]);
  assert.equal((await statuses()).missing, 'sold');

  assert.equal((await upsert([prop('bad', 'invented')])).status, 422);

  await upsert([{ ...prop('offer'), display_price: 'UNDER OFFER' }]);
  assert.equal((await statuses()).offer, 'under_offer');
  await upsert([{ ...prop('offer'), display_price: '$1,200,000' }]);
  assert.equal((await statuses()).offer, 'active');

  await upsert([{ ...prop('sold-label'), display_price: 'SOLD' }]);
  assert.equal((await statuses())['sold-label'], 'sold');

  await upsert([{ ...prop('withdrawn-label'), badge: 'Withdrawn' }]);
  assert.equal((await statuses())['withdrawn-label'], 'withdrawn');

  await upsert([{ ...prop('sold-prior'), display_price: 'Auction unless sold prior' }]);
  assert.equal((await statuses())['sold-prior'], 'active');
});

test('full snapshots use complete source inventory rather than the filtered shortlist', async () => {
  const env = makeEnv();
  const send = async (properties, fullSnapshot = false, sourceInventory = []) => worker.fetch(request('/', {
    method: 'POST', token: ADMIN_TOKEN,
    body: {
      action: 'properties_upsert',
      properties,
      full_snapshot: fullSnapshot,
      source_inventory: sourceInventory,
    },
  }), env);
  const prop = (source_id, source = 'domain_web') => ({
    source_id,
    source,
    listing_url: `https://example.com/${source_id}`,
  });
  const inventory = (...items) => items.map(({ source_id, source }) => ({ source_id, source }));

  await send([prop('filtered'), prop('unmonitored-alert', 'cre')]);
  env.DB.database.prepare(
    "UPDATE properties SET last_seen = datetime('now', '-22 days') WHERE source_id = 'filtered'"
  ).run();

  const passing = prop('passing');
  const filtered = prop('filtered');
  const rollingAlert = prop('rolling-alert', 'cre');
  let response = await send([passing, rollingAlert], true, inventory(passing, filtered));
  assert.equal(response.status, 200);

  let rows = (await (await worker.fetch(request('/?action=properties'), env)).json()).properties;
  let statuses = Object.fromEntries(rows.map((row) => [row.source_id, row.status]));
  assert.equal(statuses.filtered, 'active');
  assert.equal(statuses['unmonitored-alert'], 'active');
  assert.equal(statuses['rolling-alert'], 'active');

  env.DB.database.prepare(
    "UPDATE properties SET last_seen = datetime('now', '-22 days') WHERE source_id = 'filtered'"
  ).run();
  response = await send([passing], true, inventory(passing));
  assert.equal(response.status, 200);
  rows = (await (await worker.fetch(request('/?action=properties'), env)).json()).properties;
  statuses = Object.fromEntries(rows.map((row) => [row.source_id, row.status]));
  assert.equal(statuses.filtered, 'archived');
  assert.equal(statuses['unmonitored-alert'], 'active');

  response = await send([passing], true, []);
  assert.equal(response.status, 422);

  response = await send([passing, prop('authoritative-omitted')], true, inventory(passing));
  assert.equal(response.status, 422);
});

test('notes accept an encouraged name, default to Anonymous, and retry safely', async () => {
  const env = makeEnv();
  await saveProperty(env);
  const namedBody = {
    action: 'note', property_id: 'property-1', idempotency_key: crypto.randomUUID(),
    author: '  George  ', note: 'Creek frontage is the strongest feature.',
  };
  const first = await worker.fetch(request('/', { method: 'POST', body: namedBody }), env);
  assert.equal(first.status, 201);
  assert.equal((await first.clone().json()).note.author, 'George');
  assert.equal((await worker.fetch(request('/', { method: 'POST', body: namedBody }), env)).status, 200);
  const anonymous = await worker.fetch(request('/', { method: 'POST', body: {
    action: 'note', property_id: 'property-1', idempotency_key: crypto.randomUUID(), note: 'Anonymous thought.',
  } }), env);
  assert.equal((await anonymous.json()).note.author, 'Anonymous');
  assert.equal((await (await worker.fetch(request('/'), env)).json()).notes.length, 2);
});

test('concurrent delivery of one note id remains idempotent', async () => {
  const env = makeEnv();
  await saveProperty(env);
  const body = {
    action: 'note', property_id: 'property-1', idempotency_key: crypto.randomUUID(),
    author: 'George', note: 'Only one copy, even when delivered together.',
  };
  const [first, second] = await Promise.all([
    worker.fetch(request('/', { method: 'POST', body }), env),
    worker.fetch(request('/', { method: 'POST', body }), env),
  ]);
  assert.deepEqual([first.status, second.status].sort(), [200, 201]);
  assert.equal((await (await worker.fetch(request('/'), env)).json()).notes.length, 1);
});

test('invalid notes and malformed JSON return client errors', async () => {
  const env = makeEnv();
  await saveProperty(env);
  const invalid = await worker.fetch(request('/', { method: 'POST', body: {
    action: 'note', property_id: 'property-1', idempotency_key: crypto.randomUUID(), note: ' '.repeat(4),
  } }), env);
  assert.equal(invalid.status, 422);
  const unknownName = await worker.fetch(request('/', { method: 'POST', body: {
    action: 'note', property_id: 'property-1', idempotency_key: crypto.randomUUID(),
    author: 'Mallory', note: 'Unknown selector value.',
  } }), env);
  assert.equal(unknownName.status, 422);
  assert.deepEqual(await unknownName.json(), { ok: false, error: 'invalid_author' });
  const malformed = new Request('https://worker.example/', { method: 'POST', body: '{bad' });
  assert.equal((await worker.fetch(malformed, env)).status, 400);
  assert.equal((await worker.fetch(request('/', { method: 'POST', body: { action: 'surprise' } }), env)).status, 404);
});

test('a shared name carries reactions across devices while anonymous feedback stays per browser', async () => {
  const env = makeEnv();
  await saveProperty(env);
  for (const body of [
    { action: 'reaction', property_id: 'property-1', reaction: 'love', ...GEORGE },
    { action: 'reaction', property_id: 'property-1', reaction: 'pass', ...MARY },
  ]) assert.equal((await worker.fetch(request('/', { method: 'POST', body }), env)).status, 200);

  const georgeOtherDevice = await worker.fetch(request('/?action=reactions&author=George&actor_id=other-browser'), env);
  assert.deepEqual(await georgeOtherDevice.json(), { reactions: [{ property_id: 'property-1', reaction: 'love', author: 'George' }] });
  const mary = await worker.fetch(request(`/?action=reactions&${identityQuery(MARY)}`), env);
  assert.deepEqual(await mary.json(), { reactions: [{ property_id: 'property-1', reaction: 'pass', author: 'Mary' }] });

  await worker.fetch(request('/', { method: 'POST', body: {
    action: 'reaction', property_id: 'property-1', reaction: 'interesting', actor_id: 'anonymous-device-one', author: '',
  } }), env);
  const otherAnonymous = await worker.fetch(request('/?action=reactions&actor_id=anonymous-device-two'), env);
  assert.deepEqual(await otherAnonymous.json(), { reactions: [] });
});

test('favourites persist by shared name and can be cleared', async () => {
  const env = makeEnv();
  await saveProperty(env);
  await worker.fetch(request('/', { method: 'POST', body: {
    action: 'favourite', property_id: 'property-1', favourite: true, ...GEORGE,
  } }), env);
  const otherDevice = await worker.fetch(request('/?action=favourites&author=George&actor_id=other'), env);
  assert.deepEqual(await otherDevice.json(), { favourites: [{ property_id: 'property-1', author: 'George' }] });
  await worker.fetch(request('/', { method: 'POST', body: {
    action: 'favourite', property_id: 'property-1', favourite: false, ...GEORGE,
  } }), env);
  assert.deepEqual(await (await worker.fetch(request(`/?action=favourites&${identityQuery(GEORGE)}`), env)).json(), { favourites: [] });
});

test('only the admin can export attributed feedback', async () => {
  const env = makeEnv();
  await saveProperty(env);
  await worker.fetch(request('/', { method: 'POST', body: {
    action: 'note', property_id: 'property-1', idempotency_key: crypto.randomUUID(), author: 'George', note: 'More creek.',
  } }), env);
  assert.equal((await worker.fetch(request('/?action=feedback_export'), env)).status, 401);
  const response = await worker.fetch(request('/?action=feedback_export', { token: ADMIN_TOKEN }), env);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).notes[0].author, 'George');
});

test('writes stop when rate limited', async () => {
  const env = makeEnv();
  await saveProperty(env);
  env.WRITE_RATE_LIMITER = { limit: async () => ({ success: false }) };
  const response = await worker.fetch(request('/', { method: 'POST', body: {
    action: 'note', property_id: 'property-1', idempotency_key: crypto.randomUUID(), note: 'Limited.',
  } }), env);
  assert.equal(response.status, 429);
});

test('public rate-limit keys cannot be rotated with arbitrary bearer tokens', async () => {
  const env = makeEnv();
  const keys = [];
  env.WRITE_RATE_LIMITER = { limit: async ({ key }) => { keys.push(key); return { success: true }; } };
  for (const token of ['rotating-one', 'rotating-two']) {
    await worker.fetch(request('/', {
      method: 'POST', token, cfIp: '203.0.113.7',
      body: { action: 'note', property_id: 'missing', idempotency_key: crypto.randomUUID(), note: 'Probe' },
    }), env);
  }
  assert.equal(keys.length, 2);
  assert.equal(keys[0], keys[1]);
});

test('production migration preserves legacy notes and reactions', () => {
  const database = new DatabaseSync(':memory:');
  database.exec(readFileSync(new URL('../migrations/0001_initial.sql', import.meta.url), 'utf8'));
  database.exec(`
    INSERT INTO properties (source_id) VALUES ('property-1');
    INSERT INTO notes (id, property_id, author, timestamp, note)
      VALUES ('note-1', 'property-1', '', '2026-08-17T00:00:00Z', 'Old note');
    INSERT INTO reactions (property_id, reaction, timestamp)
      VALUES ('property-1', 'love', '2026-08-17T00:00:00Z');
  `);
  database.exec(readFileSync(new URL('../migrations/0002_attributed_feedback.sql', import.meta.url), 'utf8'));
  database.exec(readFileSync(new URL('../migrations/0003_constrain_notes.sql', import.meta.url), 'utf8'));

  assert.equal(database.prepare('SELECT author FROM notes').get().author, 'Legacy import');
  assert.deepEqual({ ...database.prepare('SELECT actor_id, author, reaction FROM reactions').get() }, {
    actor_id: 'legacy-import', author: 'Legacy import', reaction: 'love',
  });
  assert.ok(database.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='favourites'").get());
  const columns = database.prepare('PRAGMA table_info(notes)').all();
  assert.equal(columns.find((column) => column.name === 'author').notnull, 1);
  assert.equal(columns.find((column) => column.name === 'note').notnull, 1);
});
