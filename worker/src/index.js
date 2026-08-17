/**
 * Bolt Hole backend — Cloudflare Worker + D1.
 *
 * Drop-in replacement for the Google Apps Script backend (apps_script/Code.gs).
 * The API contract is identical, so the shortlist page and Python scraper only
 * change their endpoint URL:
 *
 *   GET  ?action=properties  → { properties: [{source_id, ..., payload: {...}}] }
 *   GET  ?action=reactions&author=...&actor_id=... → participant reactions
 *   GET  (bare)              → { notes: [{id, property_id, author, timestamp, note}] }
 *   POST {action:"note", property_id, author?, note}           → { ok: true, note }
 *   POST {action:"properties_upsert", properties:[{...}]}      → { ok: true, upserted: n }
 *   POST {action:"reaction", property_id, reaction}            → { ok: true }  (clear/'' deletes)
 *
 * Upsert semantics preserved from Code.gs:
 *   - existing first_seen is kept on update
 *   - a manually-set non-'active' status survives unless the incoming property
 *     carries an explicit status (the scraper never sends one)
 *
 * Feedback names are optional labels, not authenticated identities. Named
 * reactions/favourites follow that label across devices; anonymous feedback
 * uses a browser-generated actor_id and therefore remains device-specific.
 */

function corsHeaders(request, env) {
  const allowedOrigin = String(env.PUBLIC_ORIGIN || '').replace(/\/$/, '');
  const requestOrigin = String(request.headers.get('Origin') || '').replace(/\/$/, '');
  const headers = {
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Vary': 'Origin',
  };
  if (allowedOrigin && requestOrigin === allowedOrigin) {
    headers['Access-Control-Allow-Origin'] = requestOrigin;
  }
  return headers;
}

function json(request, env, obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(request, env) },
  });
}

function bearerToken(request) {
  const header = request.headers.get('Authorization') || '';
  return header.startsWith('Bearer ') ? header.slice(7).trim() : '';
}

function isAdminRequest(request, env) {
  const token = bearerToken(request);
  return Boolean(token && env.ADMIN_TOKEN && token === env.ADMIN_TOKEN);
}

class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

const ALLOWED_AUTHORS = new Map(
  ['George', 'Mary', 'Alex', 'Greg', 'Justin', 'Anonymous']
    .map((name) => [name.toLocaleLowerCase('en-AU'), name])
);

function cleanAuthor(value) {
  const author = String(value || '').trim().replace(/\s+/g, ' ');
  if (author.length > 80 || /[\u0000-\u001f\u007f]/.test(author)) {
    throw new ApiError(422, 'invalid_author');
  }
  if (!author) return 'Anonymous';
  const canonical = ALLOWED_AUTHORS.get(author.toLocaleLowerCase('en-AU'));
  if (!canonical) throw new ApiError(422, 'invalid_author');
  return canonical;
}

function feedbackIdentity(authorValue, actorValue) {
  const author = cleanAuthor(authorValue);
  if (author !== 'Anonymous') {
    return { actorId: `name:${author.normalize('NFKC').toLocaleLowerCase('en-AU')}`, author };
  }
  const actorId = String(actorValue || '').trim();
  if (!/^[A-Za-z0-9_-]{8,100}$/.test(actorId)) {
    throw new ApiError(422, 'invalid_actor_id');
  }
  return { actorId: `device:${actorId}`, author };
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      const headers = corsHeaders(request, env);
      if (!headers['Access-Control-Allow-Origin']) {
        return json(request, env, { ok: false, error: 'origin_not_allowed' }, 403);
      }
      return new Response(null, { status: 204, headers });
    }

    if (request.method !== 'GET' && request.headers.get('Origin')) {
      const headers = corsHeaders(request, env);
      if (!headers['Access-Control-Allow-Origin']) {
        return json(request, env, { ok: false, error: 'origin_not_allowed' }, 403);
      }
    }

    try {
      if (request.method === 'GET') {
        const action = new URL(request.url).searchParams.get('action') || '';
        if (action === 'properties') return json(request, env, { properties: await readProperties(env) });
        if (action === 'feedback_export') {
          if (!isAdminRequest(request, env)) {
            return json(request, env, { ok: false, error: 'authentication_required' }, 401);
          }
          return json(request, env, await readFeedbackExport(env));
        }
        if (!action) return json(request, env, { notes: await readNotes(env) });
        if (action === 'reactions' || action === 'favourites') {
          const url = new URL(request.url);
          const identity = feedbackIdentity(
            url.searchParams.get('author'),
            url.searchParams.get('actor_id'),
          );
          if (action === 'reactions') {
            return json(request, env, { reactions: await readReactions(env, identity.actorId) });
          }
          return json(request, env, { favourites: await readFavourites(env, identity.actorId) });
        }
        return json(request, env, { ok: false, error: 'unknown_action:' + action }, 404);
      }

      if (request.method === 'POST') {
        let body = {};
        try {
          body = JSON.parse(await request.text() || '{}');
        } catch {
          return json(request, env, { ok: false, error: 'invalid_json' }, 400);
        }
        const action = body.action || '';

        if (env.WRITE_RATE_LIMITER && ['note', 'reaction', 'favourite', 'properties_upsert'].includes(action)) {
          const clientKey = request.headers.get('CF-Connecting-IP')
            || bearerToken(request)
            || String(body.actor_id || body.author || 'anonymous').slice(0, 100);
          const { success } = await env.WRITE_RATE_LIMITER.limit({ key: `${action}:${clientKey}` });
          if (!success) {
            return json(request, env, { ok: false, error: 'rate_limited' }, 429);
          }
        }

        if (action === 'note') {
          const author = cleanAuthor(body.author);
          const result = await addNote(env, body, author);
          return json(request, env, { ok: true, note: result.note }, result.created ? 201 : 200);
        }
        if (action === 'properties_upsert') {
          if (!isAdminRequest(request, env)) {
            return json(request, env, { ok: false, error: 'authentication_required' }, 401);
          }
          const n = await upsertProperties(env, body.properties || []);
          return json(request, env, { ok: true, upserted: n });
        }
        if (action === 'reaction') {
          const identity = feedbackIdentity(body.author, body.actor_id);
          await upsertReaction(env, body, identity);
          return json(request, env, { ok: true });
        }
        if (action === 'favourite') {
          const identity = feedbackIdentity(body.author, body.actor_id);
          await upsertFavourite(env, body, identity);
          return json(request, env, { ok: true });
        }
        return json(request, env, { ok: false, error: 'unknown_action:' + action }, 404);
      }

      return json(request, env, { ok: false, error: 'method_not_allowed' }, 405);
    } catch (err) {
      if (err instanceof ApiError) {
        return json(request, env, { ok: false, error: err.code }, err.status);
      }
      console.error('Unhandled Bolt Hole API error', err);
      return json(request, env, { ok: false, error: 'internal_error' }, 500);
    }
  },
};

// ── Notes ────────────────────────────────────────────────────────────────

async function readNotes(env) {
  const { results } = await env.DB.prepare(
    'SELECT id, property_id, author, timestamp, note FROM notes ORDER BY timestamp'
  ).all();
  return results;
}

async function addNote(env, body, author) {
  const id = String(body.idempotency_key || '');
  const propertyId = String(body.property_id || '').trim();
  const note = String(body.note || '').trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)) {
    throw new ApiError(422, 'invalid_idempotency_key');
  }
  if (!propertyId || propertyId.length > 200) {
    throw new ApiError(422, 'invalid_property_id');
  }
  if (!note || note.length > 500) {
    throw new ApiError(422, 'invalid_note');
  }
  const property = await env.DB.prepare(
    'SELECT source_id FROM properties WHERE source_id = ?'
  ).bind(propertyId).first();
  if (!property) throw new ApiError(422, 'unknown_property');

  const timestamp = new Date().toISOString();
  const insert = await env.DB.prepare(
    'INSERT OR IGNORE INTO notes (id, property_id, author, timestamp, note) VALUES (?, ?, ?, ?, ?)'
  ).bind(
    id,
    propertyId,
    author,
    timestamp,
    note
  ).run();
  const saved = await env.DB.prepare(
    'SELECT id, property_id, author, timestamp, note FROM notes WHERE id = ?'
  ).bind(id).first();
  if (!saved) throw new Error('note_insert_missing');
  if (saved.property_id !== propertyId || saved.author !== author || saved.note !== note) {
    throw new ApiError(409, 'idempotency_key_conflict');
  }
  return { note: saved, created: Number(insert?.meta?.changes || 0) > 0 };
}

// ── Properties ───────────────────────────────────────────────────────────

async function readProperties(env) {
  const { results } = await env.DB.prepare(
    'SELECT source_id, suburb, address, first_seen, last_seen, status, listing_url, payload FROM properties'
  ).all();
  // Inline the payload dict so callers get a flat record (matches _readProperties)
  for (const row of results) {
    if (row.payload) {
      try { row.payload = JSON.parse(row.payload); } catch (e) { row.payload = null; }
    }
  }
  return results;
}

async function upsertProperties(env, properties) {
  if (!Array.isArray(properties)) throw new ApiError(422, 'invalid_properties');
  if (properties.length > 500) throw new ApiError(413, 'too_many_properties');
  if (!properties.length) return 0;
  const nowIso = new Date().toISOString();

  const stmt = env.DB.prepare(`
    INSERT INTO properties (source_id, suburb, address, first_seen, last_seen, status, listing_url, payload)
    VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
    ON CONFLICT(source_id) DO UPDATE SET
      suburb      = excluded.suburb,
      address     = excluded.address,
      -- first_seen: keep the existing value on update
      last_seen   = excluded.last_seen,
      -- status: preserve a manually-set non-'active' status unless the incoming
      -- property carried an explicit status (?9 = 1 when explicit)
      status      = CASE
                      WHEN ?9 = 1 THEN excluded.status
                      WHEN properties.status IS NOT NULL AND properties.status != 'active' THEN properties.status
                      ELSE excluded.status
                    END,
      listing_url = excluded.listing_url,
      payload     = excluded.payload
  `);

  // Validate the entire upload before constructing any writes. This prevents a
  // malformed record near the end from leaving a partially refreshed database.
  const validated = properties.map((p) => {
    if (!p || typeof p !== 'object' || Array.isArray(p)) {
      throw new ApiError(422, 'invalid_property');
    }
    const sid = String(p.source_id || '').trim();
    if (!sid || sid.length > 200) throw new ApiError(422, 'invalid_source_id');
    const listingUrl = String(p.listing_url || '').trim();
    if (listingUrl) {
      let parsed;
      try { parsed = new URL(listingUrl); } catch { throw new ApiError(422, 'invalid_listing_url'); }
      if (parsed.protocol !== 'https:' || listingUrl.length > 2048) {
        throw new ApiError(422, 'invalid_listing_url');
      }
    }
    let payload;
    try { payload = JSON.stringify(p); } catch { throw new ApiError(422, 'invalid_property'); }
    if (payload.length > 100_000) throw new ApiError(413, 'property_too_large');
    return { p, sid, listingUrl, payload };
  });

  const batch = [];
  for (const { p, sid, listingUrl, payload } of validated) {
    batch.push(stmt.bind(
      sid,
      String(p.suburb || ''),
      String(p.address || ''),
      String(p.first_seen || nowIso),
      nowIso,
      String(p.status || 'active'),
      listingUrl,
      payload,
      p.status ? 1 : 0
    ));
  }
  // A D1 batch is transactional: either the full refresh lands or none does.
  await env.DB.batch(batch);
  return validated.length;
}

// ── Reactions ────────────────────────────────────────────────────────────

async function readReactions(env, actorId) {
  const { results } = await env.DB.prepare(
    'SELECT property_id, reaction, author FROM reactions WHERE actor_id = ?'
  ).bind(actorId).all();
  return results.filter(r => r.property_id && r.reaction)
    .map(r => ({
      property_id: String(r.property_id),
      reaction: String(r.reaction),
      author: String(r.author),
    }));
}

async function upsertReaction(env, body, identity) {
  const pid = String(body.property_id || '');
  if (!pid) throw new ApiError(422, 'invalid_property_id');
  const reaction = String(body.reaction || '');

  const property = await env.DB.prepare(
    'SELECT source_id FROM properties WHERE source_id = ?'
  ).bind(pid).first();
  if (!property) throw new ApiError(422, 'unknown_property');

  // Neutral/clear removes the row (matches Apps Script semantics)
  if (reaction === 'clear' || reaction === '') {
    await env.DB.prepare(
      'DELETE FROM reactions WHERE property_id = ? AND actor_id = ?'
    ).bind(pid, identity.actorId).run();
    return;
  }
  if (!['love', 'interesting', 'pass'].includes(reaction)) {
    throw new ApiError(422, 'invalid_reaction');
  }

  await env.DB.prepare(`
    INSERT INTO reactions (property_id, actor_id, author, reaction, timestamp) VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(property_id, actor_id) DO UPDATE SET
      author = excluded.author,
      reaction = excluded.reaction,
      timestamp = excluded.timestamp
  `).bind(pid, identity.actorId, identity.author, reaction, new Date().toISOString()).run();
}

// ── Favourites ───────────────────────────────────────────────────────────

async function readFavourites(env, actorId) {
  const { results } = await env.DB.prepare(
    'SELECT property_id, author FROM favourites WHERE actor_id = ?'
  ).bind(actorId).all();
  return results.map(row => ({
    property_id: String(row.property_id),
    author: String(row.author),
  }));
}

async function upsertFavourite(env, body, identity) {
  const pid = String(body.property_id || '').trim();
  if (!pid) throw new ApiError(422, 'invalid_property_id');
  if (typeof body.favourite !== 'boolean') {
    throw new ApiError(422, 'invalid_favourite');
  }
  const property = await env.DB.prepare(
    'SELECT source_id FROM properties WHERE source_id = ?'
  ).bind(pid).first();
  if (!property) throw new ApiError(422, 'unknown_property');

  if (!body.favourite) {
    await env.DB.prepare(
      'DELETE FROM favourites WHERE property_id = ? AND actor_id = ?'
    ).bind(pid, identity.actorId).run();
    return;
  }
  await env.DB.prepare(`
    INSERT INTO favourites (property_id, actor_id, author, timestamp) VALUES (?, ?, ?, ?)
    ON CONFLICT(property_id, actor_id) DO UPDATE SET
      author = excluded.author,
      timestamp = excluded.timestamp
  `).bind(pid, identity.actorId, identity.author, new Date().toISOString()).run();
}

// ── Analysis export ──────────────────────────────────────────────────────

async function readFeedbackExport(env) {
  const [notes, reactionResult, favouriteResult, properties] = await Promise.all([
    readNotes(env),
    env.DB.prepare(
      'SELECT property_id, actor_id, author, reaction, timestamp FROM reactions ORDER BY timestamp'
    ).all(),
    env.DB.prepare(
      'SELECT property_id, actor_id, author, timestamp FROM favourites ORDER BY timestamp'
    ).all(),
    readProperties(env),
  ]);
  return {
    notes,
    reactions: reactionResult.results,
    favourites: favouriteResult.results,
    properties,
  };
}
