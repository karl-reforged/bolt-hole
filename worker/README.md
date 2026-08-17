# Bolt Hole database backend

The production backend is a Cloudflare Worker backed by D1 (SQLite). It stores:

- the current property records and full source payload;
- shared notes, including the optional display name and server timestamp;
- one reaction and favourite per feedback identity and property;
- stable idempotency keys so retrying a note cannot create duplicates.

Property reads and shared notes are public to the shortlist. Property writes and
the full feedback export require the private `ADMIN_TOKEN`. Feedback writes are
rate-limited, validated and accepted only from the configured production web
origin in browsers.

## Identity and multiple devices

A name is optional. The page offers George, Mary, Alex, Greg, Justin and
Anonymous. A named reaction or favourite is keyed by that selection, so choosing
the same person on another device loads the same choices. Anonymous feedback
uses a random browser ID and remains device-specific. Notes are shared
everywhere and show the selected name or `Anonymous`.

Names are labels, not verified accounts. Anyone who selects the same name can
see or change that name's reactions and favourites. This is appropriate for the
small trusted audience, but it should be replaced with real authentication if
the shortlist becomes broadly shared.

## Secure production setup

From `worker/`:

1. Create one strong admin token and put the same value in the Worker's
   `ADMIN_TOKEN` secret and the refresh machine's `BOLT_ADMIN_TOKEN` setting.
   On the production Mac, the refresh also supports the macOS Keychain service
   `Bolt Hole Admin Token`, avoiding a plain-text local secret.
2. Run the tests, take a D1 export, then apply migrations and deploy.
3. Exercise the production checks below.

The one-time legacy `0002` migration changes the reaction table shape and is
not a zero-downtime migration for the old Worker. Put the small private service
into a short maintenance window, take the backup, then apply the migrations and
deploy the new Worker back-to-back. If deployment fails, restore the export and
redeploy the previous Worker version before reopening writes. Production has
already completed this one-time transition.

```sh
npm test
npx wrangler d1 export bolt-hole --remote --output backups/bolt-hole.sql
npx wrangler secret put ADMIN_TOKEN
npx wrangler d1 migrations apply bolt-hole --remote
npx wrangler deploy
```

`PUBLIC_ORIGIN` is deliberately committed as
`https://karl-reforged.github.io`; no access secret is embedded in the static
site. Never commit `ADMIN_TOKEN` or the private feedback export.

## Production checks

```sh
# Public properties and notes
curl 'https://bolt-hole-backend.karl-582.workers.dev?action=properties'
curl 'https://bolt-hole-backend.karl-582.workers.dev'

# Private analysis export
curl -H "Authorization: Bearer $BOLT_ADMIN_TOKEN" \
  'https://bolt-hole-backend.karl-582.workers.dev?action=feedback_export'
```

The guarded refresh uses the admin token, requires the database to confirm the
full property count, exports feedback into the ignored
`data/feedback/latest_summary.json`, and only then rebuilds the shortlist.

## Backup and restore

Before a schema change, export D1 to an ignored local backup:

```sh
mkdir -p backups
npx wrangler d1 export bolt-hole --remote --output backups/bolt-hole.sql
```

The database URL is
`https://bolt-hole-backend.karl-582.workers.dev`. The old Apps Script remains a
legacy fallback only and is not written by the current pipeline.
