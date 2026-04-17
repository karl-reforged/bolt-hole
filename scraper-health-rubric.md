---
title: Scraper Health Rubric
version: 1.0
created: 2026-03-17
scope: Universal — applies to any automated data collection
---

# Scraper Health Rubric

A framework for evaluating, comparing, and improving automated data scrapers and API integrations. Use it before building (to choose an approach), after building (to track quality), and when things break (to diagnose where).

## How to use

**Adding a new source?** Score the planned approach against the six dimensions before writing code. If there are multiple options (scrape vs API vs email alerts), score each and compare. The gap between scores is the engineering cost — weigh that against financial cost, coverage, and viability context.

**Evaluating what's built?** Score each scraper periodically. Track scores over time. A dropping score means the source or your code is degrading.

**Something broke?** The dimension scores tell you where the weakness is and what class of fix is needed.

---

## Engineering Health Score (/30)

Six dimensions, each scored 1–5. Total /30.

### 1. Resilience

> Will it keep working when conditions change?

Covers: retry logic with backoff, graceful fallbacks, circuit breakers, breakage surface area (how many assumptions can change and break it), anti-bot detection risk. Silent failures are scored harshly — if it breaks, it must say so.

| Score | Meaning |
|-------|---------|
| 5 | Official stable API, versioned, documented. Minimal assumptions. |
| 4 | Stable unofficial API/JSON endpoint with retry and fallbacks. |
| 3 | Scraping with structured data (embedded JSON), retry logic, some fallbacks. |
| 2 | Scraping HTML/DOM, Playwright required, source actively evolves. |
| 1 | Source actively blocks automated access. Already broken or intermittent. |

### 2. Data Quality

> Is the extracted data complete and accurate?

Covers: field coverage of the normalised schema (what % of fields are filled vs null), parse accuracy (typed JSON field vs regex extraction from free text), unit conversion reliability (e.g. acres/hectares/sqm ambiguity).

| Score | Meaning |
|-------|---------|
| 5 | All fields from typed, structured source. No guessing. |
| 4 | Most fields filled. Minor inference needed (e.g. price from display string). |
| 3 | Core fields filled but gaps (no coords, no description, area ambiguous). |
| 2 | Sparse data. Multiple fields require heuristic extraction. |
| 1 | Minimal usable data. Heavy guessing or manual enrichment needed. |

### 3. Observability

> Do you know when it's broken before anyone tells you?

Covers: structured logging (info on success, warning on degradation, error on failure), per-source health reporting, scrape run history, admin-visible dashboards or status output.

| Score | Meaning |
|-------|---------|
| 5 | Health dashboard, per-run metrics, alerting on degradation, historical trends. |
| 4 | Structured log output with counts, errors surfaced in pipeline report. |
| 3 | Print-level logging — counts and errors visible in console output. |
| 2 | Minimal logging. Failures visible only if you read the code path. |
| 1 | No logging. Silent success or silent failure — you can't tell which. |

### 4. Testability

> Can you verify it works without hitting the live source?

Covers: mocked API/response tests, fallback path coverage, edge case tests (empty responses, missing fields, malformed data, zero results), ability to run the scraper in isolation.

| Score | Meaning |
|-------|---------|
| 5 | Full test suite with mocked responses, edge cases, fallback paths tested. |
| 4 | Core happy-path tests with mocks. Key edge cases covered. |
| 3 | Can run standalone with sample data. No automated tests. |
| 2 | Testable in theory but requires live network/browser. |
| 1 | No tests. Requires full pipeline run to verify. |

### 5. Maintainability

> When it breaks, how long does the fix take?

Covers: code complexity (lines of code, number of regex patterns, JSON traversal depth), dependency weight (requests-only vs Playwright vs IMAP), clean I/O (standard inputs and outputs), cognitive load to understand the code.

| Score | Meaning |
|-------|---------|
| 5 | < 50 LOC, requests-only, single JSON path, obvious logic. |
| 4 | < 150 LOC, minimal deps, straightforward parsing, few edge cases. |
| 3 | 150–300 LOC, some regex or multi-path parsing, manageable complexity. |
| 2 | 300+ LOC, Playwright dependency, multiple fallback parse paths, fragile regex. |
| 1 | 400+ LOC, deep coupling to browser state, speculative parsing, hard to reason about. |

### 6. Consistency

> Does it follow project patterns, or is it a one-off?

Covers: standard normalised output format, shared utilities (retry sessions, area/price parsers), integration with pipeline orchestration (fetch_all, deduplicate, or equivalent), follows project conventions (base class inheritance, scheduling, config-driven).

| Score | Meaning |
|-------|---------|
| 5 | Follows all project patterns. Drop-in addition to pipeline. Standard I/O. |
| 4 | Follows most patterns. Minor deviations justified by source constraints. |
| 3 | Output format matches but internal patterns diverge. |
| 2 | Custom approach. Partially integrated. Some manual wiring needed. |
| 1 | Standalone script. Doesn't integrate with existing pipeline. |

---

## Source Viability Context

These factors assess whether a source is *worth* building a scraper for. They are not scored on 1–5 — they are metadata tracked per source to inform the build-vs-buy-vs-skip decision.

### Legal Risk

Classification: **Low / Medium / High**

- **Low**: Public data presented to attract engagement (e.g. property listings, job postings, product prices). No auth bypass. No PII extraction.
- **Medium**: Data behind a free account. ToS explicitly prohibits scraping. Aggressive bot detection in place.
- **High**: Data behind paywall, involves PII, requires auth bypass, or jurisdiction has strong anti-scraping precedent.

If High — stop. Find an API, a data provider, or a manual process.

### Cost

Classification: **Free / Metered / Paid**

Track: cost per call, monthly cap, free tier limits.

When comparing a free scraper (scoring 15/30) against a paid API (scoring 25/30), the question becomes: is the quality and reliability gap worth the spend? The health score quantifies the gap; the cost tells you the price to close it.

### Data Freshness

Track: source update frequency, pipeline run frequency, and the resulting maximum staleness.

| Source updates | Pipeline runs | Max staleness |
|---|---|---|
| Real-time | Daily | 24 hours |
| Daily | Weekly | 7 days |
| Weekly | Weekly | 14 days |
| Monthly | Weekly | ~5 weeks |

Freshness is an output property, not a scraper quality. A perfectly engineered scraper run monthly still produces stale data. Track it to ensure your pipeline frequency matches the source's update cadence.

---

## Decision Framework

### When to scrape

Source has structured data (JSON/API), low legal risk, free or cheap, and you can build to score 20+ on the health rubric.

### When to pay for an API

Your scraper scores below 18 and the source offers a stable API. The cost of maintaining a fragile scraper (your time, breakage risk, data quality gaps) exceeds the API fee.

### When to use alerts/manual capture

Source actively blocks automation (health score capped at ~13). Use email alerts, saved searches, or manual capture and feed normalised data into the pipeline via a file-based loader.

### When to skip

Low volume source (< 10 listings), high legal risk, or would score below 12 on health rubric. The maintenance cost exceeds the data value.

---

## Scorecards

### REA via Apify

```
Source:          REA / realestate.com.au
Approach:        Apify actor (abotapi/realestate-au-scraper) — managed scraping service
Date scored:     2026-03-17

Resilience:      4/5  — Apify handles anti-bot, retries, browser management. Actor maintained by third party.
Data Quality:    4/5  — Structured JSON: address, coords, price, features, description, photos. Minor inference on price.
Observability:   4/5  — Apify dashboard shows run status, credits, duration. Pipeline logs counts and errors.
Testability:     3/5  — Can run standalone. No mocked tests yet. Requires live Apify run to verify.
Maintainability: 4/5  — ~150 LOC. Requests-only (no local Playwright). Clean async poll pattern.
Consistency:     5/5  — Standard normalised output. Integrated into fetch_all(). Uses shared retry session.
TOTAL:           24/30

Viability:
  Legal risk:    Low — Apify operates as a data service; no local scraping or auth bypass
  Cost:          Free tier ($5/mo credit) — estimated <$1/run for 27 filtered URLs
  Freshness:     Source updates real-time / pipeline runs weekly / max staleness 7 days

Notes:
  - URL-mode input pre-filters by postcode, price, land size — keeps cost low
  - Actor choice (abotapi) returns structured data including coordinates and descriptions
  - Key risk: actor deprecation. Mitigated by env var override (APIFY_REA_ACTOR)
  - Upgrade path: if volume grows, switch to Apify paid tier ($49/mo for more credits)
```

### Scorecard Template

Copy for each scraper evaluation:

```
Source:          [name]
Approach:        [API / JSON endpoint / HTML scrape / Playwright / Email parse / Manual]
Date scored:     [YYYY-MM-DD]

Resilience:      /5  —
Data Quality:    /5  —
Observability:   /5  —
Testability:     /5  —
Maintainability: /5  —
Consistency:     /5  —
TOTAL:           /30

Viability:
  Legal risk:    [Low / Medium / High]
  Cost:          [Free / $X per month]
  Freshness:     [source updates X / pipeline runs Y / max staleness Z]

Notes:
  [Key risks, improvement opportunities, or build-vs-buy considerations]
```
