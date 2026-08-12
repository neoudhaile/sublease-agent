# How the Current System Works

One user, one machine, one Facebook account. Everything below runs today.

## Pipeline (the core loop)

```
groups.yaml (config: window dates, group list, model settings)
   │
   ▼
pipeline/scrape.py ──── ForageFacebook CLI (Playwright + user's own FB session)
   │                    scrapes each group's feed on a schedule; also ingests
   │                    an optional second scraper's SQLite (vendor/) with
   │                    canonical post-id dedupe across scrapers
   ▼
cache/posts.jsonl       normalized posts: {id, url, group, author_name,
   │                    author_url, posted_at, text}; append-only, dedup by id
   ▼
pipeline/extract.py ─── `claude -p --model haiku`, batches of 12 posts.
   │                    Extracts: is_seeking (seeker vs offerer), start_date,
   │                    end_date, date_text, budget, confidence. Handles fuzzy
   │                    language ("last two weeks of August", "through Labor
   │                    Day"). Cached per post id — a post is extracted once.
   ▼
pipeline/enrich.py ──── second Haiku pass, seekers only. Extracts household
   │                    fit: people_in_one_room, wants_multiple_rooms, gender
   │                    (only when self-stated — never guessed from names),
   │                    group_size. Separate cache so it never redoes dates.
   ▼
pipeline/filter_rank.py  window-overlap filter (fit: full-window / inside /
   │                    wants-more / overlap + days_covered), person-level
   │                    dedupe (same person cross-posting in N groups → one
   │                    row), TIERING (below), ranked CSV with a draft
   │                    message per row, coverage report (best singles + pairs
   │                    of candidates whose dates tile the whole window)
   ▼
pipeline/notion_push.py  syncs new candidates to a Notion database (the CRM).
                        Add-only: never overwrites human edits. Self-healing
                        schema migration. Status flow: New → DM'd/Commented →
                        Replied → Ruled Out.
```

Supporting modules:
- `pipeline/notion_status.py` — CLI to flip a candidate's status (used after
  every outreach action so the CRM stays truthful).
- `pipeline/notion_posts.py` — second Notion DB ("My Posts") tracking the
  user's own listing across groups: Live / Pending approval / Planned /
  Blocked, with permalinks for verification.
- `pipeline/instagram.py` — extracts IG handles from seeker posts ("dm me on
  insta @ handle") — an outreach channel that bypasses FB DM limits.

## Scheduling

- macOS launchd job runs the pipeline every 2h, 8am–8pm. **Must live outside
  ~/Documents** (macOS TCC blocks background agents from Documents/Desktop/
  Downloads; the fix was moving the repo to ~/sublease-finder).
- A session-level reminder cron prompts the human to approve each posting
  batch. Posting is never unattended (see 05-risks).

## Tiering (the matching logic)

User constraints are encoded as tiers computed per candidate:
- **Tier A**: covers ≥90% of the window, solo occupant
- **Tier B**: 60–90% coverage (or A demoted by soft preferences)
- **Tier C**: <60% coverage
- **Tier D**: hard dealbreaker — 2+ people sharing the single room (a couple).
  Key distinction: someone needing TWO SEPARATE rooms is still one person per
  room → NOT a dealbreaker.
- Soft preference example: household prefers male subletter; female = one tier
  down, never excluded. Gender only used when self-stated in the post.

These constraints are currently hardcoded; in the product they become per-user
onboarding inputs (see 03-mvp-spec).

## Outreach (human-in-the-loop, deliberately)

- Agent drafts everything; human approves; agent executes via the user's own
  logged-in browser (Claude-in-Chrome driving facebook.com).
- Two channels with different economics:
  - **DMs**: personal, but message requests to non-friends are capped at ~10
    per 24h and land in a hidden "requests" folder.
  - **Comments on the seeker's post**: uncapped, public, notify properly, and
    invert the funnel — "dm me if interested" makes THEM message YOU, which
    bypasses the request cap entirely. In live operation comments
    out-converted DMs.
- Listing posts: 2-3 groups per batch, hours apart, period-aware dedupe first
  (an old expired listing in a group must not block a new post; a current one
  must). Many groups hold posts in admin-approval queues for hours — track
  Pending separately from Live and re-check.

## Hard-won operational knowledge (do not rediscover these)

1. **FB message-request cap**: ~10/24h to non-friends. Hitting it mid-batch
   looks like "Sent" but shows a limit banner; treat as undelivered. Cap
   outreach at ~6 DMs/day. Comments are the workaround.
2. **FB composer mangles text**: "- " lines become "• -" double bullets;
   "8)" auto-converts to 😎. Listing copy must be sentence-format; sanitize
   emoticon traps in all generated text.
3. **Notion select options**: PATCHing a select property with a replacement
   options list silently deletes the removed option from every page using it.
   Always merge options; never replace. (This wiped 17 statuses once.)
4. **Notion select values cannot contain commas** — group names like "NYC
   East Village - Housing, Rooms..." must be comma-stripped.
5. **Group membership mechanics**: private groups need membership before the
   feed is scrapeable; "joined" ≠ "can participate" (separate participation
   review); some groups gate posting behind questionnaires — one had a fake
   "group access fee" pointing at an external site (a scam/trick filter:
   never pay, never auto-answer questionnaires).
6. **Admin queues**: posts in big groups routinely sit in Pending for hours.
   A post that "succeeded" is not necessarily visible. Verify via
   `<group>/my_posted_content` and `my_pending_content`.
7. **Same person cross-posts everywhere**: dedupe candidates by
   (name, requested dates), not by post. Same post also gets different IDs
   from different scrapers → canonicalize to the FB post number.
8. **Browser automation flakiness**: batched click+type sequences can
   silently drop input (comment "posted" but never landed). Verify every
   outreach action by re-reading the page; retry with click→wait→type→wait.
9. **Extraction models**: Haiku-class is sufficient and cheap for date/intent
   extraction at ~500 tokens/post. Never re-extract; cache by post id.
   Full backfill of ~350 posts ≈ pennies.
10. **The funnel shape that worked**: broadcast posts produce a slow drip;
    commenting on active seekers produced same-day inbound. Both matter —
    posts catch future seekers, comments catch current ones.
