# Parts-catalog parser — planning doc

Product #1 of billy-ai (contracted). A local desktop app for non-technical
users that parses plumbing-parts **websites** and **catalog PDFs** into Excel
workbooks, optionally filtered to the part numbers in a user-supplied Excel
sheet.

This document records the design settled in the 2026-07-13 ideation session,
including spike results verified against the two reference sources:
`midlandindustries.com` (website) and the Fairview 2021 Master Catalog (PDF).
It is the entry point for per-ticket ideation — tickets must not contradict
it without updating it first.

## 1. Users and constraints

- **End users are non-technical.** They double-click an executable, drag
  files in, click Run. No terminal, no config files, no programmer-facing
  errors (see `.ai/rules/core.md` rule 5).
- **Windows-first**, but nothing may preclude macOS (development happens on
  a Mac).
- **Local-only.** No hosted components. All state lives on the user's
  machine.
- **General tool.** Midland and Fairview are reference sources, not
  hard-coded targets. New sources must work without code changes where
  possible (see structure discovery, §4.3).
- **Cost ceiling:** near-free per run. AI spend is bounded to structure
  discovery (once per new site) and PDF page extraction (once per unique
  catalog file, ~$1–2).

## 2. Design principles

1. **AI at the edges only.** AI discovers structure (websites) and extracts
   pages (PDFs). Volume work — crawling, API calls, filtering, Excel
   writing — is deterministic code. Never an LLM call inside a per-part loop
   on the web pipeline.
2. **Part numbers are verbatim.** Output cells are character-for-character
   what the source showed. Normalization exists only for matching.
3. **Learn once, reuse forever.** Everything AI learns is persisted in the
   run store (§6). A second run against a known source makes zero AI calls.
4. **Never guess silently.** Anything inferred (filter column choice,
   normalized-only matches, skipped pages) is reported in the output
   workbook where the user can see it.
5. **Errors self-heal or explain themselves.** Stale cached configs trigger
   automatic re-discovery; failures surface in plain language.

## 3. Architecture overview

```
┌────────────────────────── GUI shell (§8) ──────────────────────────┐
│  URL input │ PDF drag-drop │ filter-Excel drag-drop │ Run/progress │
└──────┬──────────────────────────┬──────────────────────────────────┘
       │                          │
  Web pipeline (§4)          PDF pipeline (§5)
  Playwright session          text extraction
  → platform API /            → page classification
    discovered selectors      → AI per page (LLM client §7)
       │                          │
       └───────────┬──────────────┘
                   ▼
        Shared output layer (§9)          Run store (§6)
        filter matching + Excel writer    site configs, PDF cache,
        + match-report sheet              run history
```

Two pipelines, one output layer, one persistent run store, one thin GUI.
Each box is a module boundary and a natural ticket seam (§11).

## 4. Web pipeline

### 4.1 Browser and Cloudflare (spike-verified)

Plain **headless bundled Playwright Chromium** passes Cloudflare on
midlandindustries.com; `curl` and plain HTTP fetches are blocked. After one
real page load establishes clearance cookies, `context.request` can call the
site's JSON API directly from the same session — no DOM scraping.

Rate limiting is mandatory (politeness + not tripping the bot wall):
throttled request rate, no parallel hammering. Full-site crawls are
expected to be slow; the GUI sets that expectation (progress + resumable).

### 4.2 Platform adapters — Insite first (spike-verified)

midlandindustries.com runs **Optimizely/Insite B2B Commerce**, a widespread
B2B distributor platform. Verified endpoints:

| Endpoint | Returns | Gotchas |
|---|---|---|
| `/api/v2/products/{guid}?expand=detail,specifications,attributes` | product object **at top level** (not nested): `productNumber`, `productTitle`, `attributeTypes[]` label/value pairs | — |
| `/api/v2/products?search=<term>&expand=attributes` | paginated search results with attributes | works from `context.request` |
| `/api/v1/categories/?maxDepth=3` | category tree (17 top-level on Midland) | products attach at **leaf** categories (~level 4); `categoryId=` on level-2/3 ids returns 0 items. Level-2/3 pages are tile fan-outs. Exact leaf-listing call: small open item, resolve during build by watching a leaf page's network calls |
| `sitemap.xml` | 404 on Midland | enumerate via category tree instead |

The pipeline is structured as **platform adapters**: an adapter knows how to
enumerate products and fetch attributes for one platform. Insite is the
first adapter. Detection ("is this site Insite?") is a cheap deterministic
probe (fetch `/api/v1/websites/current`, check the shape) tried before any
AI is spent.

### 4.3 Structure discovery for unknown sites

When no adapter matches, AI structure discovery runs **once**: load sample
pages in Playwright, capture the rendered DOM and network traffic, and ask
the LLM to produce a **site config** — either "this is actually platform X"
or a set of selectors/endpoints for enumeration, breadcrumb
(category/subcategory/series), part number, and attribute label/value pairs.
The config is a plain data artifact saved to the run store, consumed by
deterministic code. Discovery cost: a handful of LLM calls per new site,
ever.

### 4.4 Enumeration strategy

- **Filter sheet supplied (primary use case):** skip crawling entirely —
  query the site's search API once per part number. A 500-part sheet is 500
  fast calls, minutes not hours.
- **No filter sheet:** walk the category tree to leaf categories, page
  through each leaf's product listing.

### 4.5 Output schema (web)

One row per part:
`Part No | Category | Subcategory | Series | <attribute columns>`

Attribute columns are the union of attribute labels seen in the run
(~30–40 on Midland). A part missing a label gets a blank cell. Breadcrumb
maps as Home / **Category** / **Subcategory** / **Series** / part name.

## 5. PDF pipeline

### 5.1 Extraction (spike-verified)

The Fairview 2021 catalog is **digital text** — 276 pages, extracts cleanly
with pypdf; no OCR. Scanned PDFs are out of scope for v1: detect (near-zero
extractable text) and tell the user plainly.

Structure observed: TOC on early pages maps sections → page ranges;
category names sit at the front (Fittings & Adapters, Barbs & Hose Ends,
…); a parts page has a subcategory header ("BLACK IRON PIPE FITTINGS /
SCHEDULE 40"), repeating **series blocks** ("BUSHING", "90° ELBOW", "FORGED
NUT Long Standard Type"), each with `PART No. | size(s)` rows. Some tables
have two size columns (Tube + Pipe). Some pages mix marketing prose with a
few real parts (e.g. p.100).

### 5.2 AI-per-page extraction

Per-page LLM extraction (small/cheap model) rather than one global layout
rule set — catalog layouts vary page-to-page in ways a single rule set
won't survive. ~276 pages ≈ **$1–2 per catalog**, paid once per unique file
(cache, §6). The TOC is parsed first and passed as context so each page's
category is known.

Extraction rule: **a part exists only where a part number exists.** The
Description cell is whatever text belongs to that part's block — multi-size
columns combined with their labels (`Tube: 1/4, Pipe: 1/8`) or spec bullets
on prose-style pages. Pure-marketing blocks with no part numbers are
skipped.

### 5.3 Validation (deterministic, free)

- Every extracted part number must appear **verbatim in the page text** —
  outright hallucination check.
- Part-number shape sanity per section (consistent prefixes, e.g.
  `BI-…`), dedupe across pages, sequence monotonicity.
- Totals reported to the user (parts extracted, pages skipped, validation
  failures) — plus automated spot-checks on a random sample.

### 5.4 Output schema (PDF)

`Part No | Category | Subcategory | Series | Description | Sequence`

Sequence = order of appearance in the catalog, 1..N (~26k for Fairview).

## 6. Run store

Local persistent state in the OS app-data directory (`%APPDATA%\<app>` on
Windows, `~/Library/Application Support/<app>` on macOS) — never next to
the executable.

| Store | Key | Contents | Effect |
|---|---|---|---|
| Site configs | domain | platform id or discovered selectors/endpoints, attribute-label union | repeat web runs make zero AI calls |
| PDF cache | file hash | the **parsed parts**, not just structure | re-running the same catalog (e.g. with a different filter sheet) is instant and free |
| Run history | run id | timestamp, source, part count, output path, validation/spot-check results | powers resume + audit trail |

**Staleness guard:** at run start, validate a cached site config with one
probe (fetch a known part). If the response is empty/malformed, trigger
re-discovery automatically. The user never manages the cache.

## 7. LLM client

One provider-agnostic client module; no provider SDK calls or model names
anywhere else (`.ai/rules/core.md` rule 2).

- **Now:** operator's OpenAI key, small/cheap model for PDF pages.
- **Later:** end users paste their own key (OpenAI or Anthropic) into the
  GUI settings screen. Keys are stored locally (app-data), never committed,
  never bundled into the executable.

## 8. GUI

Minimal single window:

- Website URL input **or** PDF drag-and-drop (the two run modes)
- Optional filter-Excel drag-and-drop
- Run button, progress bar with plain-language status, cancel
- Resumable runs (web crawls can be long)
- Settings: API key entry
- Output lands in a user-visible location (e.g. next to the input file /
  Downloads), and the app offers to open it

Toolkit: **PySide6 (Qt)** — native drag-and-drop, decent progress UI,
PyInstaller-compatible, cross-platform. Heavier binary than Tkinter, which
is an acceptable trade for reliability in front of non-technical users.

Packaging: PyInstaller one-folder build. Known risk to spike early:
bundling Playwright's Chromium (either ship the browser in the bundle or
first-launch download with a progress prompt).

## 9. Output layer and filter matching

### 9.1 Excel writer

`openpyxl`-based writer shared by both pipelines. Sheet 1 = parts (schema
per pipeline, §4.5 / §5.4). Part numbers verbatim, always.

### 9.2 Filter matching

- **Column auto-detect:** find a header like `Part`, `Part No`,
  `Part Number`, `Item` (case-insensitive); fall back to the first column.
  The choice is reported.
- **Normalized-key matching:** uppercase + strip all non-alphanumerics on
  both sides (`bi-110-ba` ↔ `BI110BA` match). Handles Excel's usual damage:
  dropped leading zeros, numeric coercion, stray whitespace, unicode
  dashes.
- **Match-report sheet (always present when a filter is supplied):** every
  filter row → matched (exact vs normalized-only) or unmatched; the column
  used; collisions (two source parts normalizing to one key) flagged rather
  than silently resolved.
- **Web + filter:** matching drives enumeration (§4.4) — search per part
  number. **PDF + filter:** parse everything (cached anyway), filter at
  write time.

## 10. Testing and accuracy bar

- Unit tests on the deterministic core: normalization, filter matching,
  Excel writing, validation rules, Insite response parsing (recorded JSON
  fixtures — no live site in tests).
- PDF pipeline: golden-file tests on a handful of Fairview pages with
  hand-checked expected rows.
- Acceptance per source: automated spot-check sample passes; manual
  spot-check by the user is the final gate (their standard, per ideation).

## 11. Ticket seams (candidates — final decomposition at `/ideate`/`/ticket`)

1. **Scaffold**: uv + Python 3.12 project, package layout matching §3
   boundaries, LLM client stub, run-store skeleton, CI (ruff + pytest).
   Establishes conventions → creates `.ai/context/core.md` + first recipes.
2. **Output layer**: Excel writer + filter loading/auto-detect/matching +
   match-report sheet. Pure-deterministic, highly testable.
3. **Web pipeline / Insite adapter**: Playwright session + CF clearance,
   category enumeration (resolve leaf-listing call), search-per-part mode,
   product detail → rows.
4. **PDF pipeline**: extraction, TOC parse, page classification,
   AI-per-page extraction, validation suite, PDF cache.
5. **Run store**: site configs + staleness probe + run history (skeleton
   from ticket 1 made real).
6. **Structure discovery**: AI site-config generation for unknown,
   non-Insite sites.
7. **GUI shell**: PySide6 window wired to both pipelines, progress,
   settings/API key.
8. **Packaging**: PyInstaller build, Playwright browser strategy, Windows
   smoke test.

Rough order: 1 → 2 → 3/4 (parallel) → 5 → 7 → 8, with 6 anytime after 5.

## 12. Out of scope

- The email-native order agent (deferred product #2 — see repo docs/memory)
- Any P21 integration
- Scanned-PDF OCR (v1 detects and declines gracefully)
- Hosted key proxy or any server-side component
- Auto-update mechanisms
