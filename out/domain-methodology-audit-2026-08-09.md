# Domain scrape methodology audit — 2026-08-09

Three-agent sweep (failure handling · parsing fragility · anti-bot strategy) plus a
live probe. Verdict: **the methodology works but is brittle in a specific, fixable
way — it has one loud safety gate and many silent-loss paths beneath it.** The
health floors (240 raw / 110 passed / 90 described) catch catastrophic failure;
anything smaller passes unseen, and several failure modes actually push the
numbers *up*.

## Confirmed & fixed today

**First-postcode Akamai sacrifice (the "Oberon bug").** The first JSON fetch after
warm-up reliably eats an Akamai challenge page; the failed attempt itself sets the
challenge cookie, so a same-session retry succeeds. Verified live: attempt 1
unparseable, attempt 2 → 8 listings for 2787. Failed in **4 of 8 sampled runs**
(always the first postcode — 2787, hence "Oberon problem"). Fixed in `sources.py`:
one retry with 2s pause before a postcode counts as failed. Backfill run launched.

## Top findings by severity (consolidated)

### Structural — the safety net has holes

1. **`sanity_check` is unreachable in production.** The only code comparing today
   vs yesterday runs solely under `--email` (`search.py:851,872`); the guarded
   runner invokes bare `search.py`. The 50%-drop / score-drop / Domain-zero checks
   have never executed in a scheduled refresh. → Move the delta check into
   `run_search` or the runner's `health()`.
2. **Empty run resurrects yesterday's file as "healthy."** When a scrape returns
   nothing, `run_search` writes no file; `newest_search_after` falls back to
   `files[0]` — the runner health-checks *yesterday's* results, passes, prints
   COMPLETE, and (with `--upsert`) re-stamps stale rows as seen-today.
   → Delete the fallback (`run_guarded_domain_refresh.py:36`).
3. **Health floors are blind to composition.** ~40 listings of slack below the
   floors; per-postcode losses invisible (2787's 8→3 passed clean). The
   description floor is now satisfiable by *cache hydration* alone, so total
   failure to enrich new listings passes. → Gate on ratios
   (postcodes_succeeded/attempted, enriched/needed) recorded in `source_report`.

### Real bugs found

4. **OSRM failure latch disables the drive-time gate.** After 5 failures every
   property gets `drive_mins=None`, which *passes* the gate (by design for
   transient flake) and zeroes a 20-point score component — and more passing
   properties makes the health floors happier. HTTP-error path logs nothing.
   → Cooldown-reset the latch; fail the run if >X% missing drive times.
5. **Operator-precedence bug** (`sources.py` context-recreate condition,
   `A or B and C`): `MAX_CONTEXT_RECREATES` unenforced on the primary match;
   pagination twin is parenthesised correctly — they disagree.
6. **`_new_context()` returns `(None, page)`** — every `context.close()` raises
   into a bare except; the poisoned Akamai cookie jar is never actually dropped.
7. **Pagination failures are 100% silent** (`err2` computed, discarded); a missing
   `totalPages` silently defaults to 1 → pages 2–5 never fetched, across all
   postcodes, indistinguishable from a thin market.
8. **Phase-2 detail fetches still fire after the Phase-1 circuit breaker trips**
   (hammers a blocked session with ~26 concurrent bursts); a mid-phase page death
   cascades — no context recreation in Phase 2.
9. **Domain API 403 is invisible** — swallowed as `count: 0, error: None`. The
   agent notes the 403 text ("Operation not permitted on project") means the API
   project lacks the search entitlement — fixing *that* would remove the scraping
   arms race entirely. Worth one support email.

### Parsing fragility

10. **No diagnostics survive a break.** Unparseable bodies are discarded (120-char
    preview only); the raw listing payload collected at normalize time is
    explicitly deleted before writing. A break is undebuggable next morning.
    → Quarantine unparseable HTML to `data/logs/domain_raw/` (~15 lines); keep one
    `raw` sample per run for shape-diffing; count normalize drops (currently a
    bare `except: continue`).
11. **16 shape assumptions catalogued**, worst first: search URL params silently
    ignored if renamed (returns unfiltered state-wide listings — numbers go UP);
    `landUnit` strings (unit corruption → everything fails the land gate);
    `__NEXT_DATA__` presence; `listingsMap` path; address component shape;
    `isArchived` (rename ships sold listings to George).

### Anti-bot posture

12. **Load-bearing:** real installed Chrome, non-headless, default fingerprint,
    navigation-over-fetch. **Cargo-cult:** uniform 0.3s delays (zero jitter in the
    file — itself a volumetric tell), `AutomationControlled` flag.
    **Counterproductive:** `X-Requested-With: XMLHttpRequest` header on detail
    bursts (Domain's own frontend doesn't send it); 10-way concurrent XHR bursts
    (most plausible trigger of the 14-May tab-kill cascade).
13. **Single points of failure:** one IP, no proxy support, no degraded-publish
    mode (a Domain block kills the whole refresh even when Farmbuy/Elders/Apify
    returned data), retry ladder re-presents the same fingerprint every 30 min
    (trains Akamai's IP reputation — 14 May: 28 attempts over 9 hours).
    → Escalating cooldown (30m → 2h → 6h); persistent Chrome profile so Akamai
    cookies age across runs (~5 lines, biggest fingerprint win); Apify Domain
    actor (~$3.25/run) as the true fallback path.

## Recommended sequence (next session)

| Pri | Change | Effort |
|---|---|---|
| P0 | ✅ First-fetch retry (done today) | S |
| P0 | Fix precedence bug + real context recreation (real cookie-jar drop) | S |
| P0 | Drop `X-Requested-With`; skip Phase 2 after breaker trip | S |
| P0 | Delete `files[0]` fallback in runner | S |
| P1 | Ratio-based health gates via enriched `source_report` counters | M |
| P1 | Quarantine unparseable HTML + keep one raw shape sample per run | S |
| P1 | Jitter all delays; adaptive batch size (10→3 on first error) | S/M |
| P1 | OSRM latch cooldown + missing-drive-time gate | S |
| P1 | In-process delta check vs rolling median of healthy runs | M |
| P2 | Persistent Chrome profile; escalating cooldown; degraded-publish mode | M |
| P2 | Chase Domain API entitlement (kills the scraping problem at the root) | L |
| P2 | Widen/evaluate Apify Domain actor as lockout fallback | M |

Full agent reports available in session transcript; all findings carry file:line
citations there.
