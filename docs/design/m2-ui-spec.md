# sublease-agent — UI spec for mockups (M2)

Everything here is grounded in the schema and engine that already exist on branch
`m1-core-engine`. Field names are real; the sample data is what the engine actually
produces from the repo's `fixtures/posts.json` against a 22-day window. Mock against
these and the result will be implementable.

---

## 1. What this is

A **local, self-hosted tool**. It runs on the user's own machine at
`http://localhost:7847`, opened by `sublease start`. There is no login, no account,
no other users, and no public surface. That single fact should shape the whole design:

- **No auth, no avatars, no "workspace", no billing.** Do not design a shell around them.
- **One person, one browser tab.** No multiplayer, presence, or sharing.
- **It is a workbench, not a marketplace.** There is no public inventory to browse.
- **Dense over airy.** The user is scanning 125 people to pick 5. This is closer to an
  email client or a bug tracker than a landing page.

**The job:** the user has a room free for a fixed window and loses real money if it sits
empty. The app finds people already looking for those dates, ranks them, and gets a
message in front of the right ones fast.

**Tone:** plain, quiet, factual. This tool tells someone their listing is blocked, or
that an account check has halted automation. It must never be chirpy about it.

---

## 2. Screens, in order of how much they matter

1. **Candidates board** — where the user lives. Design this first.
2. **Coverage** — the "who together covers my whole window" view.
3. **Outreach queue** — the doing-something screen. Two variants (see §7).
4. **Onboarding wizard** — seen once, but it is the first impression.
5. **My Listings** — where the user's own posts stand in each group.
6. **Run status / doctor** — is the machine healthy, what happened last run.
7. **Settings** — profile, constraints, templates, provider, execution mode.

---

## 3. Real data to mock with

This is genuine engine output. Window **Aug 18 – Sep 8 2026 (22 days)**, default
constraints (max 1 person per room, no gender preference, tier A ≥ 90%, tier B ≥ 60%).

| Tier | Name | Wants | Days | Fit | Occupants | Budget | Group | Status |
|---|---|---|---|---|---|---|---|---|
| A | Exact Emma | Aug 18 – Sep 8 | 22/22 | full-window | 1 | $1800 total | NYC Sublets | new |
| B | Open-End Omar | Aug 22 – open | 18/22 | inside | 1 | — | NYU Housing | new |
| B | Fuzzy Fiona | Aug 18 – Aug 31 | 14/22 | inside | 1 (+cat) | — | Ghostlight | dm'd |
| B | Labor-Day Lee | Aug 25 – Sep 7 | 14/22 | inside | 1 | — | NYC Sublets | replied |
| C | Inside Ivan | Aug 20 – Sep 1 | 13/22 | inside | 1 | $60/night | East Village | new |
| C | Numeric Nia | Aug 30 – Sep 8 | 10/22 | inside | 1 | — | NYU Housing | new |
| D | Overlap Owen | Aug 1 – Sep 1 | 15/22 | overlap | **2 in one room** | $2500 | Brooklyn | ruled out |

**Tier reasons** are generated strings shown verbatim in the UI:

- A — `covers 22/22 days`
- B — `covers 18/22 days`
- C — `covers only 10/22 days`
- D — `2 people sharing one room (limit is 1) — household dealbreaker`
- with a gender preference set — `covers 22/22 days; female (fine, ranked just below)`
- multi-room seeker — `covers 22/22 days; needs 2 rooms, only one person would take yours`

**A draft message** (generated per candidate, ready to send):

> Hi Emma! I saw your post in NYC Sublets looking for a place Aug 18 – Sep 8. I have a
> room available that overlaps your dates. Happy to send photos and details if you're
> still looking.

**Scale to design for:** a real run produced **533 posts → 125 candidates** across ~10
groups. Roughly 8 tier A, 25 B, 60 C, 30 D. Design the board for 125 rows, not 7.

---

## 4. Candidates board

**Purpose:** scan a ranked list, decide who to contact, contact them.

Default sort is tier, then days covered, then recency — already computed. The user should
be able to re-sort but rarely needs to.

**Fields available per row** (all real columns):

| Field | Example | Notes |
|---|---|---|
| `tier` | `A` | A/B/C/D. Encode as form, not just color. |
| `tier_reason` | `covers 22/22 days` | Plain-language *why*. Show it — it is the trust builder. |
| `author_name` | `Exact Emma` | May be missing; fall back gracefully. |
| `days_covered` | `22` | Out of `window.days`. |
| `fit` | `full-window` | One of `full-window`, `inside`, `wants-more`, `overlap`. |
| `wants_start` / `wants_end` | `2026-08-18` / `2026-09-08` | Either may be **null** = open-ended. |
| `group_name` | `NYC Sublets` | Where this sighting came from. |
| `also_posted_in` | `["NYU Housing", "Ghostlight"]` | Other groups. Often empty. |
| `budget` | `$1800 total` | Free text as they wrote it. Often null. |
| `status` | `new` | `new` / `dm'd` / `commented` / `replied` / `ruled out` / `closed` |
| `draft` | *(see above)* | Pre-written message. |
| `post_url` / `author_url` | | Open on Facebook. |
| `post_text` | | First 500 chars, newlines flattened. |
| `confidence` | `high` | `high`/`medium`/`low` — how sure the model was about the dates. |

**States to mock:**

- **Populated** — 125 rows, mixed tiers and statuses.
- **Empty, first run** — profile exists, no run yet. Primary action: run it.
- **Empty, after a run** — ran, found nothing matching. This is a real and demoralising
  outcome; say something useful (widen the window? add groups?), not "No results".
- **Running** — a scrape is in progress. Show progress, keep the stale list visible and
  usable rather than blanking it.
- **Stale** — last run was 3 days ago.

**Interactions that matter:**

- Filter by tier, by status, by "new since last run".
- Open a candidate → detail (below).
- Copy draft / open their post — one keystroke each. This is the hot path.
- Mark status inline.

**Design notes:**

- `tier` and `status` are different axes and must not share an encoding.
- Open-ended dates (`wants_end = null`) are common. `Aug 22 – open` needs a real
  treatment, not an em-dash that reads as missing data.
- **Tier D is not spam.** It is a person the household's own rule excludes. De-emphasise;
  do not hide or trash-can it.
- `confidence: low` means the model guessed the dates from vague language. Worth a quiet
  marker so the user knows to read the post themselves.

---

## 5. Candidate detail

Opened from a row. Drawer or split pane — mock whichever you prefer, but the list must
stay visible; the user is comparing.

Contents: name and profile link · the full `tier_reason` · requested dates against the
user's window (a small version of the coverage bar) · budget · the full `post_text` ·
which groups they posted in · the editable `draft` · actions (copy, open post, mark
status) · the outreach history for this person, if any.

---

## 6. Coverage

The second question the product answers, and its most distinctive idea: **not "who is
best" but "who, together, covers all of it".**

Two blocks:

1. **Near-complete singles** — candidates covering the whole window (± a couple of days).
2. **Best combination** — up to `max_split` people (default 3) whose dates tile the
   window, with the total days covered.

The natural form is a **horizontal timeline**: the window as the ruler, each person a bar
positioned by their dates. The combination stacks so the tiling is literally visible.

Mock the honest cases too:
- Full coverage by one person.
- Full coverage by two or three.
- **Partial** — best combination covers 19/22, leaving a visible gap. Show the gap; that
  is actionable information.
- Nothing covers anything.

---

## 7. Outreach queue — two variants

The execution mode is chosen at onboarding and changes this screen completely.

### Variant A — "I send" (default)

The app drafts, the human sends. The screen is a **worklist**, driven by keyboard, and
its whole job is to make 27 outreach actions a fast sitting rather than an afternoon.

Per item: who, why they matter, the draft, and two actions — *copy message + open their
post*, and *mark what I did* (DM'd / commented / skip). Progress: `3 of 27`.

Nothing is automated, so there is no approval concept and no risk surface. Keep it plain.

### Variant B — autopilot (opt-in)

The agent posts, comments, and messages on its own. This screen is a **monitor**, not a
worklist:

- What it did, when, and whether the action was verified as landed.
- Today's rate budget — e.g. `DMs 3 / 6 today`. This is a real Facebook cap (~10
  message-requests per 24h to non-friends) and the user needs to see headroom.
- **A halt state.** If a checkpoint or CAPTCHA is detected, automation stops immediately
  and the user must be told plainly: what stopped, why, what happens next, what to do.
  Design this state properly — it is the most important screen in autopilot and the
  easiest to leave as an afterthought.
- A kill switch that is always reachable.

Also needed: the **opt-in moment**. Autopilot is enabled behind an explicit risk
disclosure — the user's own Facebook account is what is at stake. That is a real consent
UI, not a checkbox with fine print.

---

## 8. Onboarding wizard

Seen once. Goal: a working profile in under ten minutes. Steps, in order:

1. **The place** — neighborhood, room vs whole unit, bedrooms, bath, furnished,
   amenities, photos (multi-upload; auto-compressed).
2. **The window** — start, end, flexible?, would you accept several subletters covering
   different dates? (`allow_split`, default yes) and up to how many (`max_split`, default 3).
3. **Price** — nightly or total; the other is computed.
4. **Constraints** — max people sharing the room (default 1) · accept someone who needs
   two separate rooms? (default yes) · gender preference (optional, soft) · pets ·
   deposit terms.
5. **The pitch** — a listing post auto-drafted from the above, editable. Constraint:
   **sentence format, no bullet lines.** Facebook's composer turns a leading `- ` into a
   double bullet.
6. **Model provider** — Anthropic (key), OpenAI (key), local Ollama (nothing to enter),
   or an existing Claude Code install. Show the cost honestly: a few hundred posts is
   well under a dollar; Ollama is free and keeps posts on the machine.
7. **Groups** — the known-good NYC housing groups as suggestions; the user confirms
   membership or joins the ones they are missing. Show which they are already in.
8. **Execution mode** — "I send" or autopilot. See §7.

**Copy note for step 4:** the gender preference needs care. It is soft — one tier down,
never exclusion — and it only applies when a seeker states their own gender in their own
post. It is never inferred from a name or a photo. The UI should say so.

---

## 9. My Listings

The user's own post in each group. Fields: `group_name`, `permalink`, `status`,
`blocked_reason`, `posted_at`.

`status` is one of **live · pending admin approval · planned · blocked**.

"Pending" is the interesting one and needs to feel like a normal state, not an error:
large groups routinely hold posts in an approval queue for hours, so a post that
"succeeded" may not be visible yet. `blocked` carries a reason — e.g. a membership
questionnaire not completed, or a group demanding an "access fee" (a scam the tool
refuses to pay and flags).

---

## 10. Run status / doctor

Two things, possibly one screen.

**Doctor** — a pass/fail list run before a scrape: model provider reachable · scraper
installed · Facebook session still valid · database writable · profile parses. Each row
is `ok` or a specific failure with the fix. Sessions expire roughly monthly, so
"re-authenticate" is a routine, expected outcome, not a crisis.

**Last run** — posts scraped, new posts, how many extracted, candidates found, new
candidates, and any per-source failures. One broken scraper does not stop a run, so
partial failure is a normal state to display.

---

## 11. Constraints on the design

- **Light and dark both.** This is a developer-adjacent local tool; dark will be used.
- **Keyboard-first on the board and the queue.** The hot path is scan → copy → open →
  mark → next.
- **Semantic color is separate from tier color.** Tier is an ordered ramp; ok/warning/
  halted is a different axis; status is a third. Three encodings on one row is the hard
  part of this design — solve it deliberately.
- **Dense tables need real table craft:** tabular figures, sticky header, a row height
  that fits 125 rows without exhausting the reader.
- **Photos exist** (the user's own listing) but there are no candidate photos. Do not
  design a card grid that wants faces.
- **No empty-state mascots, no confetti.** Someone is trying not to lose $3,000.

## 12. Out of scope — do not design these

Public listing pages · search or browse of other people's rooms · a marketplace ·
messaging inside the app (conversations happen on Facebook) · payments or escrow ·
identity verification · multi-user or team features · a mobile app (Notion sync covers
phone access).
