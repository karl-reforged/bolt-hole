/**
 * Bolt Hole — Apps Script backend
 *
 * Two sheets on the same spreadsheet:
 *   - notes:       id, property_id, author, timestamp, note
 *   - properties:  source_id, suburb, address, first_seen, last_seen, status, listing_url, payload
 *
 * Notes behaviour is unchanged (legacy: returns {"notes":[]} on bare GET).
 * Properties adds:
 *   GET  ?action=properties
 *   POST {action:"properties_upsert", properties:[{source_id, ...}, ...]}
 *
 * The `payload` column stores the full property dict as JSON so shortlist.py
 * can reconstruct cards from sheet-only data. Humans can still edit the
 * first 7 columns directly (e.g. set status="withdrawn" to force age-out).
 *
 * Deploy: Extensions → Apps Script → paste this file over Code.gs → Save →
 * Deploy → New deployment → Web app → "Anyone" access → copy URL (should
 * match the existing NOTES_SCRIPT_URL; if URL changes, update .env).
 */

const NOTES_TAB = 'notes';
const PROPERTIES_TAB = 'properties';
const NOTES_HEADERS = ['id', 'property_id', 'author', 'timestamp', 'note'];
const PROPERTIES_HEADERS = [
  'source_id', 'suburb', 'address', 'first_seen', 'last_seen',
  'status', 'listing_url', 'payload',
];

// ── Entry points ────────────────────────────────────────────────────────────

function doGet(e) {
  const action = (e && e.parameter && e.parameter.action) || '';
  if (action === 'properties') {
    return _json({ properties: _readProperties() });
  }
  return _json({ notes: _readNotes() });
}

function doPost(e) {
  let body = {};
  try { body = JSON.parse(e.postData.contents || '{}'); } catch (err) {}
  const action = body.action || '';

  if (action === 'note') {
    _addNote(body);
    return _json({ ok: true });
  }
  if (action === 'properties_upsert') {
    const n = _upsertProperties(body.properties || []);
    return _json({ ok: true, upserted: n });
  }
  return _json({ ok: false, error: 'unknown_action:' + action });
}

// ── Notes ───────────────────────────────────────────────────────────────────

function _readNotes() {
  const sheet = _sheet(NOTES_TAB, NOTES_HEADERS);
  const rows = sheet.getDataRange().getValues();
  if (rows.length < 2) return [];
  const headers = rows[0];
  const out = [];
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    if (!row[0] && !row[1]) continue;
    const obj = {};
    headers.forEach((h, j) => { obj[h] = _normalise(row[j]); });
    out.push(obj);
  }
  return out;
}

function _addNote(body) {
  const sheet = _sheet(NOTES_TAB, NOTES_HEADERS);
  const row = [
    Utilities.getUuid(),
    body.property_id || '',
    body.author || '',
    new Date().toISOString(),
    body.note || '',
  ];
  sheet.appendRow(row);
}

// ── Properties ──────────────────────────────────────────────────────────────

function _readProperties() {
  const sheet = _sheet(PROPERTIES_TAB, PROPERTIES_HEADERS);
  const rows = sheet.getDataRange().getValues();
  if (rows.length < 2) return [];
  const headers = rows[0];
  const out = [];
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    if (!row[0]) continue;
    const obj = {};
    headers.forEach((h, j) => { obj[h] = _normalise(row[j]); });
    // Inline the payload dict so callers get a flat record
    if (obj.payload) {
      try { obj.payload = JSON.parse(obj.payload); } catch (e) { obj.payload = null; }
    }
    out.push(obj);
  }
  return out;
}

function _upsertProperties(properties) {
  if (!properties || !properties.length) return 0;
  const sheet = _sheet(PROPERTIES_TAB, PROPERTIES_HEADERS);
  const rows = sheet.getDataRange().getValues();
  const headers = rows[0];

  // Build a row index by source_id for O(1) lookup
  const sourceIdCol = headers.indexOf('source_id');
  const indexBySourceId = {};
  for (let i = 1; i < rows.length; i++) {
    const sid = String(rows[i][sourceIdCol] || '');
    if (sid) indexBySourceId[sid] = i + 1; // 1-indexed sheet row
  }

  const nowIso = new Date().toISOString();
  let upserted = 0;

  // Batch new rows into appendRow for efficiency
  const newRows = [];
  properties.forEach(p => {
    const sid = String(p.source_id || '');
    if (!sid) return;
    const payloadJson = JSON.stringify(p);
    const firstSeen = p.first_seen || nowIso;

    const record = {
      source_id: sid,
      suburb: p.suburb || '',
      address: p.address || '',
      first_seen: firstSeen,
      last_seen: nowIso,
      status: p.status || 'active',
      listing_url: p.listing_url || '',
      payload: payloadJson,
    };

    if (indexBySourceId[sid]) {
      // UPDATE — keep existing first_seen, update everything else
      const rowNum = indexBySourceId[sid];
      const existing = rows[rowNum - 1];
      record.first_seen = existing[headers.indexOf('first_seen')] || firstSeen;
      // Preserve manually-edited status (non-default values) unless explicit
      const existingStatus = existing[headers.indexOf('status')];
      if (existingStatus && existingStatus !== 'active' && !p.status) {
        record.status = existingStatus;
      }
      const rowValues = headers.map(h => record[h] === undefined ? '' : record[h]);
      sheet.getRange(rowNum, 1, 1, headers.length).setValues([rowValues]);
    } else {
      // INSERT
      newRows.push(headers.map(h => record[h] === undefined ? '' : record[h]));
    }
    upserted++;
  });

  if (newRows.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, newRows.length, headers.length).setValues(newRows);
  }

  return upserted;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function _sheet(name, expectedHeaders) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.appendRow(expectedHeaders);
    return sheet;
  }
  // Ensure expected headers exist (auto-extend if new ones added)
  const currentHeaders = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getValues()[0];
  let changed = false;
  const merged = currentHeaders.slice();
  expectedHeaders.forEach(h => {
    if (merged.indexOf(h) === -1) {
      merged.push(h);
      changed = true;
    }
  });
  if (changed) {
    sheet.getRange(1, 1, 1, merged.length).setValues([merged]);
  }
  return sheet;
}

function _normalise(v) {
  if (v instanceof Date) return v.toISOString();
  return v;
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
