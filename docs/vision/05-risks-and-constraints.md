# Risks & Constraints

Read this before designing anything. Several product decisions are forced
here — they are not optional polish.

## Platform Terms of Service
- Automated scraping and automated actions violate Facebook's ToS. The
  prototype mitigates by (a) using the user's own session, (b) human-shaped
  pacing, (c) tiny volume, (d) human approval of every action. A product
  scales all of this up — mitigations must scale with it or the risk balloons.
- **Consequence that forces design**: keep the human in the loop for every
  state-changing action (post/comment/DM), and keep automation local to the
  user's own session where possible (the extension model, 04). Fully
  autonomous server-side mass action is the highest-risk shape — avoid or
  gate it heavily.

## Account safety (this is the user's asset you're risking)
- A banned Facebook account is a catastrophic outcome for the user, mid-search.
- Hard limits observed: ~10 message-requests/24h to non-friends; aggressive
  spam detection on identical repeated outbound; CAPTCHAs/checkpoints when
  behavior looks botlike.
- **Forced designs**:
  - Per-user, per-platform rate limits encoded as data; never exceed.
  - Vary every generated message; never send identical text N times.
  - Prefer comments (uncapped, public) over DMs (capped) — this is both safer
    and higher-converting.
  - Detect block/checkpoint/CAPTCHA signals and HALT that user's automation
    immediately, notify them, back off. Never solve CAPTCHAs.
  - Human-shaped cadence: daytime, jittered, small batches.

## NYC short-term rental law (product-shaping, tell users)
- NYC Local Law 18 heavily restricts whole-unit rentals under 30 days when the
  permanent occupant isn't present. This is why the prototype avoids Airbnb.
- Subletting a room in a shared apartment, or where arrangements are
  peer-to-peer, is the common and lower-risk pattern — but the product should
  surface a plain-language caveat and "check your lease" prompt, not give
  legal advice. Do not position the product as enabling illegal STRs.

## Credentials & privacy
- Never take the user's password. Extension model keeps the session on their
  device. If you ever store session cookies server-side (opt-in only):
  encrypt at rest, isolate per tenant, short rotation, breach = worst case.
- Candidate data is other people's personal info scraped from groups. Store
  the minimum, don't sell it, don't compile cross-source profiles beyond the
  match need, honor deletion. Have a clear data-retention policy.
- Gender/personal attributes: only when self-stated; never inferred from
  names or photos (the prototype enforces this — keep it).

## Scams in the wild (protect users from the ecosystem)
- These groups contain fake "group access fee" posts pointing at external
  payment sites, phishing links, and bot listings. The agent must never pay
  fees, never auto-answer participation questionnaires, and should flag
  suspicious inbound to the user rather than acting on it.

## Anti-abuse (protect the platform from your users)
- A product that posts on many accounts could be used for spam. Rate limits,
  content review, and per-tenant caps aren't just safety — they're what keeps
  YOU from becoming a spam vector and getting the whole operation blocked.

## Deliverability gap (known prototype weakness to close)
- Inbound replies land in the user's Messenger; surfacing them back into the
  CRM was manual in the prototype. In the product this needs a real path
  (extension reads the inbox with user consent) or leads get lost.

## Summary of forced decisions
1. Human approves every state-changing action.
2. Extension / own-session model preferred over stored server-side sessions.
3. Rate limits + message variation + halt-on-block, enforced in the queue.
4. Comments-first outreach strategy.
5. No password handling, minimal candidate-data retention, self-stated
   attributes only.
6. Plain-language legal caveat; no Airbnb-style whole-unit STR positioning.
