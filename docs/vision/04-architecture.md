# Architecture (high level)

Goal: multi-tenant version of the single-user prototype. The prototype's
pipeline is the reference implementation; port its stages, don't reinvent them.

## The central problem: the Facebook session

Everything hinges on this. Scraping and posting happen through a real,
logged-in Facebook session. There is no official API for group feeds
(Meta removed it in 2024). Three models, in order of preference:

1. **Browser extension (recommended for MVP).** User installs an extension;
   it operates their own logged-in FB tab locally, driven by commands from
   your backend. The session never leaves the user's machine; you never hold
   their credentials. This is the same trust model as the prototype
   (Claude-in-Chrome) and the safest legally. Downside: requires the user's
   browser to be open for actions; design around intermittent availability.
2. **Server-side session with user-provided cookies.** User does an OAuth-like
   handoff; you store session cookies and run headless Playwright server-side.
   More convenient (runs 24/7) but you now hold sensitive sessions and carry
   the ToS/account-safety risk squarely (see 05). Encrypt at rest, per-user
   isolation, and treat breaches as catastrophic.
3. **Managed accounts** — do not do this. Renting/farming FB accounts is the
   fast path to bans and legal exposure.

Recommendation: ship (1). Offer (2) only to power users who explicitly opt in,
with clear risk disclosure.

## Components

```
┌─────────────┐   ┌──────────────┐   ┌─────────────────────────┐
│  Web app    │   │  API / core  │   │  Agent workers          │
│ (home,      │◄─►│  auth,       │◄─►│  scrape · extract ·     │
│  onboarding,│   │  tenants,    │   │  enrich · tier · dedupe │
│  CRM UI)    │   │  CRM store,  │   │  · outreach exec        │
└─────────────┘   │  queue       │   └───────────┬─────────────┘
                  └──────────────┘               │
                                        ┌────────▼────────┐
                                        │ Platform adapter│
                                        │ layer           │
                                        │  - facebook     │  ← extension or
                                        │  - craigslist   │    headless
                                        │  - leasebreak   │
                                        │  - reddit       │
                                        └─────────────────┘
```

- **Web app**: home page, onboarding wizard, the two CRM boards, outreach
  approval UI. This is the product users touch.
- **Core/API**: multi-tenant. Users, their listings, their config (window,
  constraints, groups, templates), the CRM data, a job/outreach queue.
- **Agent workers**: the prototype pipeline, parameterized per tenant. Stages
  are already cleanly separated (scrape/extract/enrich/rank) — keep that.
  Extraction = an LLM call per batch; cache by post id per tenant.
- **Platform adapter layer**: the key abstraction for growth. Each platform
  implements a common interface: `search(criteria) → posts`,
  `post_listing(listing) → permalink`, `send_message(target, text)`,
  `comment(post, text)`, `check_post_status(permalink)`. Facebook is the first
  adapter; the whole "add another site" story is "write an adapter."

## Data model (sketch)

- `tenant` (user), `listing` (place + window + price + constraints +
  template + photos), `platform_connection` (per user per platform: extension
  token or encrypted session, health), `group`/`source` (per platform, with
  per-source rules: needs_membership, has_participation_review, admin_queue),
  `candidate` (extracted seeker: dates, occupancy, budget, tier, source,
  post/profile links, status, draft, dedupe key = name+dates), `my_post`
  (user's own listing per source: status, permalink), `outreach_action`
  (type=post/comment/dm, target, text, status, sent_at — enforces rate caps).

## Multi-tenancy & safety wiring
- Per-tenant rate limiters on the outreach queue (FB DM cap ~10/24h etc. —
  encode as data, per platform).
- Per-tenant scrape cadence, daytime-shaped, jittered.
- Human-approval gate on any state-changing action (post/comment/dm). The
  queue holds "proposed" actions; the UI approves; the worker executes.
- Idempotency + verification: every executed action re-reads to confirm it
  landed (lesson #8), updates CRM status truthfully.

## Reuse map (what to port vs rebuild)
| Prototype piece | In product |
|---|---|
| scrape/extract/enrich/rank pipeline | Port ~as-is, parameterized per tenant |
| Tiering + dedupe logic | Port; expose constraints as onboarding inputs |
| Notion push/status/posts | Rebuild as native CRM + DB |
| launchd cron | Replace with a job scheduler / queue |
| ForageFacebook + Claude-in-Chrome | Replace with the extension adapter |
| POSTING_SOP.md rules | Encode as data (rate caps, dedupe, sanitizers) |
| Emoticon/comma sanitizers | Port verbatim — they're battle-tested |

## Suggested stack (opinion, not mandate)
- Web: Next.js + a component lib; the CRM is the hard UI part (board views,
  inline edit, approval flows) — consider a table/kanban library.
- Backend: TypeScript or Python API; a durable job queue (the pipeline is
  naturally a DAG of async stages); Postgres for tenant/CRM data.
- LLM: cheap model for extraction (Haiku-class proven sufficient); one
  provider abstraction so it's swappable.
- Browser adapter: extension (MV3) that receives action commands and reports
  results; keep the automation logic thin and the policy server-side.
