# Preserve complete meal snapshots

The crawler publishes only after all requested dates complete without exceptions
and at least one date contains a menu. Any request/parser exception, or an entirely
empty result, leaves the existing bytes and updated timestamp unchanged and exits
with status 1. The first failed/empty run publishes nothing.

An individually empty date remains a valid closed/no-menu date. The parser cannot
distinguish changed HTML that silently yields no menu from a legitimate closure;
this change does not prove source completeness or freshness. The Monday-through-
(today + 7 days) range and parser/schema remain unchanged. Complete runs replace
old snapshots rather than merging stale menus into closed dates.

A successful run writes UTF-8 JSON to a unique temporary file in the destination
directory, flushes, keeps existing permissions (0644 for a new feed), fsyncs, closes,
and replaces the destination with os.replace. Write/serialization/chmod/fsync/
replacement failure cleans its temporary file and propagates a nonzero exit while
preserving the old destination. Only crawler-created temporary files are removed.
This is atomic reader visibility, not a backup, distributed lock or guarantee of
power-loss durability (the parent directory is not fsynced).

The existing workflow runs jobs, meals, then a combined data commit. A meals
failure now stops that run before the data commit, so a successful jobs result also
waits for a later complete run. The workflow is deliberately unchanged; independent
publication/retry policy needs a separate review. Jobs safety PR #2 is independent
and not included here.

Verification uses temporary synthetic files and intercepted HTTP only:

    PYTHONPATH=/path/to/test-dependencies python3 -m unittest discover -s tests -v
    python3 -m compileall -q crawler tests

Python 3.13 local tests cover parsing, date boundaries, closed/empty/failed days,
CLI success/failure, retry, old-byte/mtime preservation, write failures, permissions
and reader visibility. Desktop/mobile Chromium consumer tests use snapshots from
the actual modified crawler with synthetic auth/data. They are not live source,
production Auth/RLS or iPhone Safari verification. No feed data is migrated or
published by the tests.

References: https://docs.python.org/3/library/os.html#os.replace and
https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile
