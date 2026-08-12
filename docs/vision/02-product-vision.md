# Product Vision

## The product in one paragraph

An AI subleasing agent. You tell it your place, your dates, and your
constraints; it goes to where sublet supply and demand already live — Facebook
groups first, then Craigslist, Leasebreak, Reddit, university boards — posts
your listing everywhere it should be, finds every person currently searching
for dates like yours, matches them against your constraints, reaches out with
your approval, and gives you a CRM of warm leads. You do the human part:
the conversation, the vibe check, the handshake.

**We are not a marketplace.** Marketplaces have a cold-start problem; the
existing platforms already have the liquidity. We're the operator layer on
top — the difference between "I spent a week posting and DMing strangers" and
"I approved a plan on Tuesday and picked between three good options Friday."

## Who it's for (initial ICP)

People with a NYC lease and a gap: internships elsewhere, long trips,
between-jobs travel, students leaving for a semester. Expand city-by-city.
- They lose $1.5–4K if the room sits empty. Real money, real motivation.
- The window is usually short (2-8 weeks) — exactly the segment that
  StreetEasy/traditional listings serve worst and Facebook groups serve best.
- Pain is acute and time-boxed: they need it filled by a specific date.

Second side (later): the seekers themselves. The same engine inverted —
"tell me your dates and budget, I'll watch every group and board and flag
matches within an hour of posting." Both sides strengthen matching data.

## Why now

- LLM extraction makes unstructured group posts machine-readable (dates like
  "through Labor Day", occupancy, budget) at ~zero marginal cost.
- Browser agents make "operate the platforms a human already uses" viable.
- The platforms themselves will never build cross-platform search; their
  incentive is lock-in.

## What was proven by the prototype

- Extraction quality is production-grade with a cheap model (dates, seeker vs
  offerer intent, occupancy, budget), with a per-post cost in fractions of a cent.
- Matching + tiering against household constraints produces a genuinely
  ranked shortlist a user trusts.
- The outreach loop converts: same-day inbound conversations, a video call
  within hours, and a full-window coverage plan (three seekers whose dates
  tile perfectly) from one day of operation.
- The human-approval model is not a compromise — it's the product. Users want
  control over who enters their home; platforms require a human pace.

## Business shape (hypotheses to validate, not commitments)

- **Success-aligned pricing**: flat fee per filled sublease (e.g. $49–99) or
  a small % of the sublet value. Free to set up; pay when it works.
- Unit economics are excellent: LLM cost per fill is dollars at most.
- The moat is operational knowledge (see 01, "hard-won knowledge") plus the
  per-market playbooks (which groups matter in each city, each group's rules).

## Non-goals (v1)

- Payments/escrow between parties — stay out of the money flow at first.
- Identity verification beyond what platforms provide.
- Being a listings site with SEO pages. No public inventory.
- Automating the final conversation. The human closes.
