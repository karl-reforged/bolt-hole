/**
 * Bolt Hole backend — Cloudflare Worker + D1.
 *
 * Drop-in replacement for the Google Apps Script backend (apps_script/Code.gs).
 * The API contract is identical, so the shortlist page and Python scraper only
 * change their endpoint URL:
 *
 *   GET  ?action=properties  → { properties: [{source_id, ..., payload: {...}}] }
 *   GET  ?action=reactions   → { reactions: [{property_id, reaction}] }
 *   GET  (bare)              → { notes: [{id, property_id, author, timestamp, note}] }
 *   POST {action:"note", property_id, author, note}            → { ok: true }
 *   POST {action:"properties_upsert", properties:[{...}]}      → { ok: true, upserted: n }
 *   POST {action:"reaction", property_id, reaction}            → { ok: true }  (clear/'' deletes)
 *
 * Upsert semantics preserved from Code.gs:
 *   - existing first_seen is kept on update
 *   - a manually-set non-'active' status survives unless the incoming property
 *     carries an explicit status (the scraper never sends one)
 *
 * The page POSTs with a text/plain content type (no CORS preflight needed),
 * so the body is parsed as JSON regardless of Content-Type.
 */

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    try {
      if (request.method === 'GET') {
        const action = new URL(request.url).searchParams.get('action') || '';
        if (action === 'properties') return json({ properties: await readProperties(env) });
        if (action === 'reactions') return json({ reactions: await readReactions(env) });
        return json({ notes: await readNotes(env) });
      }

      if (request.method === 'POST') {
        let body = {};
        try { body = JSON.parse(await request.text() || '{}'); } catch (e) { /* mirror Apps Script: fall through */ }
        const action = body.action || '';

        if (action === 'note') {
          await addNote(env, body);
          return json({ ok: true });
        }
        if (action === 'properties_upsert') {
          const n = await upsertProperties(env, body.properties || []);
          return json({ ok: true, upserted: n });
        }
        if (action === 'reaction') {
          await upsertReaction(env, body);
          return json({ ok: true });
        }
        return json({ ok: false, error: 'unknown_action:' + action });
      }

      return json({ ok: false, error: 'method_not_allowed' }, 405);
    } catch (err) {
      return json({ ok: false, error: String(err && err.message || err) }, 500);
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

async function addNote(env, body) {
  await env.DB.prepare(
    'INSERT INTO notes (id, property_id, author, timestamp, note) VALUES (?, ?, ?, ?, ?)'
  ).bind(
    crypto.randomUUID(),
    String(body.property_id || ''),
    String(body.author || ''),
    new Date().toISOString(),
    String(body.note || '')
  ).run();
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
  if (!properties || !properties.length) return 0;
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

  const batch = [];
  let upserted = 0;
  for (const p of properties) {
    const sid = String(p.source_id || '');
    if (!sid) continue;
    batch.push(stmt.bind(
      sid,
      String(p.suburb || ''),
      String(p.address || ''),
      String(p.first_seen || nowIso),
      nowIso,
      String(p.status || 'active'),
      String(p.listing_url || ''),
      JSON.stringify(p),
      p.status ? 1 : 0
    ));
    upserted++;
  }
  // D1 batch runs as a single transaction; chunk to stay well under limits.
  for (let i = 0; i < batch.length; i += 50) {
    await env.DB.batch(batch.slice(i, i + 50));
  }
  return upserted;
}

// ── Reactions ────────────────────────────────────────────────────────────

async function readReactions(env) {
  const { results } = await env.DB.prepare(
    'SELECT property_id, reaction FROM reactions'
  ).all();
  return results.filter(r => r.property_id && r.reaction)
    .map(r => ({ property_id: String(r.property_id), reaction: String(r.reaction) }));
}

async function upsertReaction(env, body) {
  const pid = String(body.property_id || '');
  if (!pid) return;
  const reaction = body.reaction || '';

  // Neutral/clear removes the row (matches Apps Script semantics)
  if (reaction === 'clear' || reaction === '') {
    await env.DB.prepare('DELETE FROM reactions WHERE property_id = ?').bind(pid).run();
    return;
  }

  await env.DB.prepare(`
    INSERT INTO reactions (property_id, reaction, timestamp) VALUES (?, ?, ?)
    ON CONFLICT(property_id) DO UPDATE SET reaction = excluded.reaction, timestamp = excluded.timestamp
  `).bind(pid, String(reaction), new Date().toISOString()).run();
}
