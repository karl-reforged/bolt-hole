# Bolt Hole backend — Cloudflare Worker + D1

Replaces the Google Apps Script backend (../apps_script/ — now legacy/fallback).
Same API contract; see src/index.js header for endpoints.

- **URL**: https://bolt-hole-backend.karl-582.workers.dev
- **Deploy**: `cd worker && env -u CLOUDFLARE_API_TOKEN npx wrangler deploy`
  (the env prefix matters: a narrow CLOUDFLARE_API_TOKEN in the shell shadows the OAuth login)
- **Query DB**: `env -u CLOUDFLARE_API_TOKEN npx wrangler d1 execute bolt-hole --remote --command "SELECT ..."`
- **Manual age-out** (old sheet trick): `... --command "UPDATE properties SET status='withdrawn' WHERE source_id='...'"`
- **Free tier**: 5GB / 5M reads/day — no idle pausing.

Data imported from the Apps Script sheet 2026-08-09 (275 properties).
The old deployment remains live as a read-only fallback; the sheet is no longer written to.
