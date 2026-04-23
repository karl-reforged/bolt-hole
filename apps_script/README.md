# Apps Script backend — deploy instructions

One file to paste, one redeploy, sheet becomes the self-contained DB for both notes *and* properties.

## What this unlocks

- `?action=properties` GET returns all property rows (source_id, suburb, address, first_seen, last_seen, status, listing_url, payload)
- `POST {action:"properties_upsert", properties:[…]}` batch upserts properties by `source_id`
- Legacy notes behaviour is unchanged (bare GET still returns `{"notes":[]}`, `POST {action:"note", …}` still appends)
- `payload` column (auto-added if missing) holds the full property dict as JSON so shortlist.py can reconstruct cards from sheet-only data
- `status` column is honoured for manual age-out — set a row to `withdrawn` / `sold` / anything other than `active` and shortlist.py drops it

## Steps (~60 seconds)

1. Open the spreadsheet: https://docs.google.com/spreadsheets/d/1JNOmQt3KWOVJTw96uMdENb1qkB4V34_i12YJ87Io9Lg/edit
2. Extensions → Apps Script
3. Select all the existing `Code.gs` content, delete it, paste the contents of `Code.gs` in this directory
4. Click **Save** (disk icon)
5. Click **Deploy** → **Manage deployments** → pencil icon on the existing Web app deployment
6. Version → **New version** → **Deploy**
7. Confirm the deployment URL is unchanged (it should be — same deployment, new version). If the URL *did* change, update `NOTES_SCRIPT_URL` in `.env` and push.

## Sanity check after deploy

```sh
curl -sSL "https://script.google.com/macros/s/AKfycby1EpSp4aOX0UdSLwRgLyDOBCfL7VBRhr_AsIwLQw8gnE3ds37c9-ducakspntlKpPb/exec?action=properties"
```

Should return `{"properties":[]}` (empty until first scrape runs). Then the next `python3 search.py` run will populate the `properties` tab in the sheet, and `python3 shortlist.py` will overlay sheet-only properties (if any are missing from the last 3 local JSONs but still within 21 days).

## Manual curation

Open the `properties` tab in the sheet — you can edit any of the first 7 columns by hand:

- **status** → set to `withdrawn` / `sold` / `off-market` to force age-out on the next shortlist render
- **address** / **suburb** → cleanups show up on the next scrape (scraper updates these fields, so your edits may be overwritten — edit `payload` instead if you want stable changes)

The `payload` column is JSON — don't hand-edit unless you know what you're doing.
