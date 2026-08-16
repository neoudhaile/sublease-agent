# sublease-agent

Finds people already looking for a sublet that matches your dates, ranks them against
your household's rules, and hands you a shortlist with a draft message for each one.

Self-hosted and open source. Everything stays on the machine you run it on — there is no
server, no account, and no copy of your data anywhere else.

> **Status: under construction.** The engine is being built in the open. Today it can
> gather posts and understand them; it cannot yet tell you who to message. See
> [Where this actually is](#where-this-actually-is) before cloning with expectations.

## The idea

Supply and demand for short sublets already live in Facebook housing groups, not on
listing sites. This is not another marketplace with a cold-start problem — it is an agent
that works the places people already post:

- Reads the groups you're a member of, through your own logged-in browser session.
- Uses a cheap model to turn unstructured posts into dates, intent, budget, and occupancy —
  including fuzzy phrasing like "the last two weeks of August" or "through Labor Day".
- Filters to people whose dates overlap your window, ranks them against your constraints,
  and collapses the same person's cross-posts into one row.
- Finds combinations: not just who covers your window, but which *two or three* people
  together tile all of it.
- Drafts a message per person. You send it, or — opt-in, behind a real disclosure — the
  agent does.

It grew out of a single-user prototype that filled one East Village sublease: 533 posts
scraped across ten NYC groups, 125 matching candidates, five conversations and a viable
three-person split inside a day.

## Where this actually is

**15 of 21 implementation tasks done. 241 tests passing.** Built and reviewed:

| Component | State |
|---|---|
| Profile & constraints (replaces every hardcoded value) | ✅ |
| SQLite store, atomic forward-only migrations | ✅ |
| Cross-scraper post normalization, canonical Facebook ids | ✅ |
| Source adapters — fixtures, ForageFacebook, Apify | ✅ |
| LLM providers — Anthropic, OpenAI, Ollama, claude-cli | ✅ |
| Extraction & enrichment, batched with bisect recovery | ✅ |
| Window overlap, tiering, person dedupe, draft rendering | ✅ |
| Coverage search, ranking | in progress |
| Pipeline orchestration, CLI | not yet |
| Web UI, outreach queue | later milestones |

There is **no `sublease` command on your PATH yet.** What exists is the library beneath
it. If you clone this today, you get a well-tested engine and no way to run it end to end.

## Design

- [Architecture and data flow](docs/superpowers/specs/2026-08-11-sublease-agent-m1-design.md) —
  what the engine is and why it's shaped this way.
- [UI spec](docs/design/m2-ui-spec.md) — screens, states, and real data shapes for the
  web interface.
- [Vision & risk docs](docs/vision/) — including the constraints that forced several
  product decisions.

## Your data

Everything lives under `$SUBLEASE_HOME` (default `~/.sublease`) in one SQLite file.

Two things leave your machine, and neither is that database: Facebook is read through the
session **you** logged into (no password is ever handled), and post text goes to whichever
model provider you configure. Choose a local Ollama and even that stays put.

The database holds posts and candidate records for real people scraped from public
groups — their names, profile links, and post text. It is not encrypted. Treat it as you
would any personal file, and delete it when your search is over.

## Legal & fair use, plainly

Automated scraping and automated posting are **against Facebook's Terms of Service.**
This tool is deliberately small-volume, human-paced, and drives your own session rather
than a farmed account. It never solves CAPTCHAs, never pays a group "access fee", and
halts on a checkpoint rather than pushing through.

None of that makes it compliant. It makes it low-risk for one person filling one room.
If you scale it up, you are taking on that risk knowingly.

Subletting may also be restricted by your lease and by local law — New York's Local Law 18
in particular constrains short-term whole-unit rentals. Check both. This is not legal
advice.

## Development

```bash
uv sync
uv run pytest
```

No test touches the network, shells out to a real binary, or calls a model.

## License

Not yet chosen — see [#license](https://github.com/neoudhaile/sublease-agent/issues).
Until one is added, default copyright applies.
