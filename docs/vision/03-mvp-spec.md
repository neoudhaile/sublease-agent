# MVP Spec

Scope: one city (NYC), one platform (Facebook groups), one side (the person
subleasing). Everything designed so adding platforms/cities/sides later is
config + adapters, not a rewrite.

## Surfaces

### 1. Home / landing page
- One-liner: "AI finds your subletter. You approve, it does the legwork."
- 3-step explainer: (1) tell us your place & dates, (2) we post & search
  everywhere subletters already are, (3) approve outreach, pick from warm leads.
- Social proof slot (the prototype's real numbers work: "125 matches, 5
  conversations, full coverage in a day").
- Single CTA → onboarding. No public listings, no marketplace browse.

### 2. Onboarding flow (turns hardcoded config into per-user input)
Collect, in order, with good defaults:
1. **The place**: neighborhood, cross-streets, room vs whole unit, # bedrooms,
   shared/private bath, furnished, photos (multi-upload; auto-compress —
   platforms cap ~10MB/upload), amenities checklist (in-unit W/D, AC, desk,
   dishwasher, etc. — these become the highlight bullets).
2. **The window**: start date, end date, whether flexible, whether willing to
   split across multiple subletters (drives the pairing/coverage feature).
3. **Price**: nightly and total; auto-compute the other.
4. **Constraints (→ tiering)**: max occupants in the room, pets ok?, gender
   preference (optional, soft), full-duration-only vs will-split, deposit terms.
5. **The pitch**: auto-draft a listing from the above (sentence format, no
   bullets — see 01 lesson #2); let user edit. Save as their template.
6. **Connect Facebook**: the critical, delicate step (see 04 + 05). MVP:
   user connects via a browser extension that operates their own logged-in
   session. Never ask for their password.
7. **Group selection**: suggest the known-good NYC housing groups (seed list
   in this repo's groups.yaml); user confirms membership / joins missing ones.
   Show which they're already in vs need to join.

### 3. In-house CRM (replaces Notion)
The prototype used Notion; productionize means building this natively. It is
the heart of the app. Two linked boards:

**Candidates board** (people who might sublease from the user):
- Columns: Name, Tier (A/B/C/D + reason), Days covered, Wants start/end,
  Occupants, Gender (if stated), Budget, Group source, Post link, Profile
  link, Status, Draft message, Full post text.
- Status flow: New → DM'd / Commented → Replied → Ruled Out → Closed.
- Sort/filter by tier, date fit, status. "Coverage" view: best single
  matches + best complementary pairs whose dates tile the whole window.
- Every row has the pre-drafted outreach message; one click to
  approve-and-send (agent executes in the connected browser).
- Add-only from the pipeline; user edits never clobbered (learned from Notion).

**My Listings board** (the user's own posts across platforms):
- Group/site, post link, status (Live / Pending admin approval / Planned /
  Blocked-with-reason), engagement, date posted.
- Period-aware dedupe so the same group isn't double-posted (lesson #6).

### 4. The agent runtime (the engine, headless)
- Scheduled scrape of the user's groups (respect per-user cadence; default
  every few hours, daytime only, human-shaped).
- Extract → enrich → tier → dedupe → write to CRM (the current pipeline,
  multi-tenant — see 04).
- Outreach queue: agent proposes a batch (posts + comments + DMs within
  daily limits); user approves in-app; agent executes and updates CRM status.
- Inbound watch: surface replies landing in the user's Messenger back into
  the CRM (this was manual in the prototype — a real gap to close).

## What v1 deliberately cuts
- Multi-city (NYC only; city = config bundle of groups + rules).
- Multi-platform posting (FB groups only; architecture leaves adapter slots).
- The seeker side of the marketplace.
- Payments.
- Automated conversation past first contact — always hand to the human.

## Definition of done for MVP
A new NYC user can: sign up → onboard their place in <10 min → connect FB →
get a listing posted in the right groups → see a populated candidate CRM
within a day → approve outreach → receive inbound leads in the CRM. I.e.
reproduce what the prototype did for one user, self-serve, for a stranger.
