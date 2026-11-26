# Notice deadline calendar estimates

The title parser uses the crawl's KST calendar date. It keeps its existing
heuristic: an inferred month/day more than 90 days in the past moves to next
year. Both the original date and the rolled-over date must exist.

For example, on 2024-11-26 a title containing `~2/29` previously attempted
2025-02-29 and raised ValueError, stopping the entire board parse. The parser
now keeps the original notice (title, URL, ID, writer and posted date) without
adding due/dueText. It does not clamp to February 28, advance to March 1 or
invent a later leap year. Later notices and other boards continue normally.

Valid leap dates, ordinary December/January rollover, the 90-day threshold,
original title formats and date-free notices retain their behavior. This is an
estimate only; users must confirm the actual official deadline. Explicit years
in titles and the existing import-time TODAY policy are separate follow-up work.

Tests use generated HTML and temporary output files, block real HTTP, and never
update the tracked jobs/meal feeds. This change adds no package or service. Run:

```sh
python -m unittest discover -s tests -v
python -m compileall -q crawler tests
```

The dedicated calendar CI runs tests only, without crawling or committing data.
The scheduled update workflow and existing notice/meal preservation PRs remain
separate and unmodified.
