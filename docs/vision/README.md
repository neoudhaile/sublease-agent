# Sublease Agent — Productionization Handoff

This folder is a handoff package for an agent (or team) building the SaaS
version of the prototype that lives in this repo. Read in order:

1. **01-current-system.md** — how the working prototype does it today, and the
   operational lessons learned the hard way (rate limits, platform quirks).
   Read this first; it is the most valuable file.
2. **02-product-vision.md** — what the product is, who it's for, positioning.
3. **03-mvp-spec.md** — the MVP surface: home page, onboarding, in-house CRM,
   matching engine. Scope guidance for v1.
4. **04-architecture.md** — high-level technical architecture for multi-tenant.
5. **05-risks-and-constraints.md** — ToS, legal, account-safety. Non-optional
   reading; several product decisions are forced by these.

## The one-sentence thesis

**Don't build a marketplace. Build the agent that works the marketplaces that
already exist.** Supply and demand for sublets already live on Facebook groups,
Craigslist, Leasebreak, Reddit, and university boards. The product is an AI
operator that posts your listing where seekers already look, finds seekers
where they already post, matches them against your constraints, and hands you
a warm shortlist — while you keep the relationships and the money.

## Prototype status (as of 2026-08-11)

Built and operating live for one user subleasing an East Village room
Aug 18 – Sep 8, 2026. In roughly one day of operation:

- 533 posts scraped from ~10 NYC Facebook housing groups on a 2-hour cron
- 125 matching candidates extracted, tiered, and synced to a Notion CRM
- Listing posted in 10 groups (~600K combined members), tracked with permalinks
- 27 candidates contacted (10 DMs, 17 comments)
- 5 inbound conversations, 1 video call, and a viable 3-person split covering
  the full window — within ~8 hours of first outreach

The prototype works. The job now is generalizing it.
