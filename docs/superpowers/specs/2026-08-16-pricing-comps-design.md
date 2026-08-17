# Pricing comps — design

Date: 2026-08-16
Status: approved for implementation
Depends on: M1 core engine (complete, 353 tests)

## The problem

`init` asks the user what to charge. Many users do not know. Guessing low costs them real
money across a three-week window; guessing high leaves the room empty, which costs more.

## The insight

The engine already scrapes the answer and throws it away. A real run fetched 533 posts to
find 125 seekers — the other ~400 are largely people *offering* rooms, with prices, in the
same neighborhoods, for the same kind of short sublet. `ranking.py:42` skips every post
where `is_seeking` is false. Those posts are the best possible comps and they are already
cached in the `post` table.

They are better comps than any external source, because they price the same product.
StreetEasy prices twelve-month leases. Airbnb prices a hotel substitute — and NYC Local
Law 18 makes those comps actively misleading for a room in an occupied apartment. Neither
prices "one room, three weeks, shared apartment, sublet from the tenant".

## The constraint that shapes the design

This is offered during `init`, before any run. **At that moment the database is empty** —
there are zero local comps. The best data source is unavailable exactly when the user is
being asked the question.

So the feature has two modes, chosen by what data exists, not by user preference:

| Mode | When | Source | Presented as |
|---|---|---|---|
| **Estimate** | No local offers yet | The model's own knowledge of the neighborhood and unit type | An estimate, with its uncertainty stated |
| **Comps** | Local offers exist | Offers extracted from already-scraped posts | Real listings, shown individually |

Comps mode supersedes estimate mode automatically once data exists. The user never chooses
a source; they choose whether to ask at all.

## Scope

**In:**
- An optional, skippable step in `init` — skipped entirely if the user already knows their price.
- A `sublease price` command to re-check any time, which uses real comps once runs have collected them.
- A third extraction pass over non-seeker posts, producing structured offers.
- Normalization of every price to **per night**, the canonical unit.
- Neighborhood matching done by the model, not a hardcoded alias table.

**Out:**
- Web search. The estimate mode covers the zero-data case adequately and adds no dependency,
  no key, and no third-party ToS surface. Revisit only if estimates prove poor in practice.
- Airbnb, StreetEasy, or any external listing scrape. Different market; see above.
- Automatic price setting. The tool suggests; the user decides.
- Any price *tracking* over time. A snapshot is what's needed.

## Normalization to per night

The canonical field is `nightly_price`. Everything converts:

| As written | Converts by | Notes |
|---|---|---|
| `$60/night` | as-is | |
| `$1400/mo` | ÷ 30.4 | Average month length. |
| `$350/week` | ÷ 7 | |
| `$1800 for the period` | ÷ nights in the offer's own date range | Needs the offer's dates; if absent, the comp is unusable and is dropped rather than guessed. |

A comp whose price cannot be converted to a per-night figure is **excluded**, not estimated.
A wrong comp is worse than a missing one — it moves the median silently.

## Data model

One new table. Global scope, like the other extraction caches: offers are a property of a
post, not of a profile, so two profiles on one machine share them.

```sql
CREATE TABLE offer (
  post_id TEXT PRIMARY KEY REFERENCES post(id) ON DELETE CASCADE,
  price_amount REAL,          -- as stated
  price_unit TEXT,            -- night | week | month | period
  nightly_price REAL,         -- normalized; NULL when not derivable
  currency TEXT,              -- 'USD' unless stated otherwise
  neighborhood TEXT,          -- as written in the post
  unit_type TEXT,             -- room | whole_unit
  bedrooms INT,
  bath TEXT,                  -- shared | private
  furnished BOOL,
  start_date DATE,
  end_date DATE,
  model TEXT,
  error TEXT,
  extracted_at TIMESTAMP NOT NULL
);
```

Written once per post, never re-extracted — the same rule as `extraction` and `enrichment`.

## Matching a comp to the user's place

Three filters, in order of how much they matter:

1. **Neighborhood.** The model decides whether a post's neighborhood string refers to the
   same area as the user's, including abbreviations and colloquial names. No alias table.
   Adjacent-neighborhood comps are usable and are labelled as such rather than silently mixed in.
2. **Unit type.** A room does not compare to a whole apartment. Hard filter.
3. **Bedrooms.** Soft — used to rank comps by similarity, not to exclude.

## What the user sees

A median, a range, the count, and the comps themselves. The individual listings matter as
much as the number: a user who sees five real posts at $65–$80 believes the suggestion in a
way they will not believe a bare figure.

Sample shape:

```
14 comparable rooms in East Village and nearby
median $71/night · range $55–$95 · 22 nights → $1,562 total

  $95/night  private room, 2BR, furnished    Aug 15 – Sep 15   NYC Sublets
  $80/night  room in 3BR, private bath       Aug 20 – Sep 10   East Village
  $71/night  room in 2BR                     Aug 18 – Sep 8    NYU Housing
  …
```

Low confidence must be visible. Fewer than five comps is reported as thin rather than
presented as a median.

## Failure behavior

- No comps and no estimate available: say so plainly and move on. The user enters a price
  as they do today. This step never blocks `init`.
- Extraction failures are recorded per post in `offer.error` and never retried, consistent
  with the other passes.
- A comp missing a price, a neighborhood, or (for period pricing) dates is dropped from the
  calculation and counted in a "not usable" figure, so the user knows the sample was filtered.

## Testing

`normalize_nightly` and the comp-selection logic are pure functions and get table-driven
tests over every price form, including the ones that must be rejected. The model pass is
tested with `FakeProvider`, like every other extraction. No test touches the network.

The golden fixture set gains priced offer posts so the end-to-end path is exercised.

## Assumptions

1. **The model's neighborhood knowledge is good enough.** It handles NYC abbreviations well.
   If a user's market is one the model knows poorly, comps mode still works — only estimate
   mode degrades.
2. **USD only for now.** The field exists; conversion does not.
3. **`price_unit: period` requires dates.** Most such posts carry them, and dropping the rest
   is the honest choice.
