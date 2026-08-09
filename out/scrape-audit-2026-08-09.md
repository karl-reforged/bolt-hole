# Bolt Hole scrape audit — 2026-08-09

First refresh since 4 June (66-day gap). Guarded run healthy on attempt 1 (~7 min),
sheet upserted via new `--upsert` flag, 137 properties published.

## Headline numbers

| Metric | 2026-08-09 | 2026-06-04 | Note |
|---|---|---|---|
| Domain Web raw | 254 | 277 | −23; one postcode failed (see below) |
| Passed gates | 138 | 150 | |
| Visible on page | 137 | 148 | REA suppressed (1) |
| **New vs last-sent baseline** | **45** | — | baseline = 14 May send |
| June listings gone | 51 | — | sold/withdrawn/expired over 9 weeks |
| Median score | 56.5% | — | max 94.5%, min 6% |

Sources: domain_web 124 · cre 7 · elders 5 · listing_loop 1 · rea_apify 1 (suppressed).
Rejections: land size 85 · drive time 69 · price 24 — distribution looks normal.

## Data quality

- **0** missing coordinates, **0** missing drive times (OSRM healthy all run)
- **13** visible listings lack descriptions (non-Domain sources — CRE/Listing Loop email alerts; expected)
- **21** without numeric price (auction / "contact agent" — display price shown instead)

## Failures & gaps

1. **Postcode 2787 (Oberon) — partial coverage.** Domain Web page-1 fetch returned an
   unparseable response (Akamai interstitial); no per-postcode retry exists. Only 3×
   2787 listings this run (Chatham Valley, Gingkin) vs 8 in June. **Remedy:** re-run
   after Domain's ~30-min cooldown — with the description cache now warm it only
   fetches the delta — or accept and let next week's run backfill.
2. **Domain API 403 / count 0** — long-standing sandbox block, not a regression.
   Domain Web is the primary source.
3. Nothing quarantined; no source errors; sanity gates all passed.

## Top 10 new since last send

| Score | Price | Acres | Drive | Suburb | Headline |
|---|---|---|---|---|---|
| 76% | $1,250,000 | 58 | 211m | Nerriga | Peaceful Rural Escape on 58 Acres |
| 72% | $690,000 | 55 | 198m | Taralga | 54 Acres of Rural Lifestyle, Sustainability |
| 70% | $1,290,000 | 43 | 134m | Tallong | Charm & Character with Far-Reaching Bush… |
| 70% | $1,750,000 | 99 | 163m | Tallong | A Private 40 Hectare Country Escape |
| 70% | $650,000 | 98 | 156m | Big Hill | Rural Lifestyle Property with Quality Improvements |
| 70% | $1,690,000 | 53 | 159m | Goulburn | Lifestyle, Space & Convenience on the Edge… |
| 68% | $850,000 | 62 | 225m | Murrumbateman | Close enough for convenience — far enough… |
| 68% | $920,000 | 185 | 225m | Crookwell | Grazing & Lifestyle |
| 67% | $1,250,000 | 199 | 161m | Windellama | 200 Acres, Graze, Ride, Enjoy & Build |
| 66% | $1,150,000 | 65 | 223m | Billywillinga | 'Elsewhere': Eco Delight Adjacent… |

New-listing suburb spread: Goulburn 4, Tallong 3, Windellama 3, Taralga 2, Crookwell 2,
Mongarlowe 2, Gingkin 2, Nerriga 1, + others.

Standouts: the two **Tallong** listings (134m/163m drive — among the closest in the set)
and **Taralga at $690k** (value pick, 72%). Big Hill at $650k/98ac is the cheapest
acreage-heavy new entry.

## State after this run

- Sheet DB: 273 rows, 138 stamped 2026-08-09 → description cache warm (next scrape
  fetches only new listings)
- `--mark-sent` run after this audit → baseline now 2026-08-09 (137 ids)
- Reactions backend deferred — reactions per-device until edm authorization or manual
  redeploy (see apps_script/README.md + task list)
